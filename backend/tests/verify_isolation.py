"""Security verification: scene ownership isolation, gating, rate limits, CORS.
Run: python3 /app/backend/tests/verify_isolation.py  (uses preview backend)."""
import asyncio, json, os, subprocess, sys
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

API = [l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")][0]
ADMIN = "katherine@katherinebeck.com"
B, C = "student-b@example.com", "student-c@example.com"
SCENE = "4b23e55d-67be-42bc-a397-4eb4085bdb2e"
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def curl(args, jar=None, method="GET", data=None, headers=()):
    cmd = ["curl", "-s", "-o", "/tmp/_o", "-w", "%{http_code}", "-X", method]
    if jar: cmd += ["-b", jar]
    if data: cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    for h in headers: cmd += ["-H", h]
    cmd.append(args if args.startswith("http") else f"{API}/api/{args}")
    code = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    try: body = json.load(open("/tmp/_o"))
    except Exception: body = open("/tmp/_o", errors="ignore").read()[:120]
    return int(code), body


async def login(email, jar):
    await db.users.update_one({"email": email}, {"$setOnInsert": {"email": email, "trial_word_used": 0, "trial_scene_used": 0}}, upsert=True)
    curl("auth/request-magic-link", method="POST", data={"email": email})
    link = await db.magic_links.find_one({"email": email, "consumed": False}, sort=[("created_at", -1)])
    subprocess.run(["curl", "-s", "-c", jar, "-o", "/dev/null", f"{API}/api/auth/verify?token={link['token']}"])


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    return cond


async def main():
    ok = True
    await login(ADMIN, "/tmp/jA"); await login(B, "/tmp/jB"); await login(C, "/tmp/jC")

    # Legacy scene: admin yes, students no
    ok &= check("admin can read legacy scene", curl(f"scenes/{SCENE}", "/tmp/jA")[0] == 200)
    ok &= check("student B cannot read legacy scene", curl(f"scenes/{SCENE}", "/tmp/jB")[0] == 404)
    ok &= check("admin sees unowned list", curl("admin/scenes", "/tmp/jA")[1].get("count", 0) >= 1)

    # Admin assigns legacy scene to B
    code, body = curl("admin/scenes/assign", "/tmp/jA", "POST", {"scene_id": SCENE, "email": B})
    ok &= check("admin assigns scene to B", code == 200, str(body)[:60])
    ok &= check("B lists exactly own scene", [s["id"] for s in curl("scenes", "/tmp/jB")[1]] == [SCENE])
    ok &= check("C lists nothing", curl("scenes", "/tmp/jC")[1] == [])
    for ep, m in [(f"scenes/{SCENE}", "GET"), (f"scenes/{SCENE}/laundry-list?sound=v_ih", "GET"),
                  (f"scenes/{SCENE}/turns/0/tts", "POST"), (f"scenes/{SCENE}/reparse", "POST"),
                  (f"scenes/{SCENE}/download-lines?character=X", "GET"), (f"scenes/{SCENE}", "DELETE")]:
        code, _ = curl(ep, "/tmp/jC", m)
        ok &= check(f"C blocked: {m} {ep.split('?')[0].replace(SCENE,'<id>')}", code in (402, 404), str(code))
    ok &= check("B can read own scene", curl(f"scenes/{SCENE}", "/tmp/jB")[0] == 200)
    ok &= check("B laundry list works", curl(f"scenes/{SCENE}/laundry-list?sound=v_ih", "/tmp/jB")[0] == 200)
    ok &= check("scene still exists after C's delete attempt", await db.scenes.count_documents({"id": SCENE}) == 1)

    # Usage endpoints
    ok &= check("caption-search requires login", curl("caption-search?q=harry")[0] == 401)
    ok &= check("caption-search works logged in", curl("caption-search?q=harry", "/tmp/jB")[0] == 200)
    ok &= check("anon pronounce unknown word -> no LLM", curl("pronounce?word=Qzxvbnmp")[1].get("source") == "none")

    # Magic-link rate limits: 5/email/hour and 20/IP/hour -> 429
    codes = [curl("auth/request-magic-link", method="POST", data={"email": C})[0] for _ in range(6)]
    ok &= check("magic-link per-email limit -> 429", codes[-1] == 429, str(codes))
    codes = [curl("auth/request-magic-link", method="POST", data={"email": f"flood{i}@example.com"})[0] for i in range(22)]
    ok &= check("magic-link per-IP limit -> 429", 429 in codes, f"first 429 at #{codes.index(429)+1 if 429 in codes else '-'}")
    await db.users.delete_many({"email": {"$regex": "^flood"}}); await db.magic_links.delete_many({"email": {"$regex": "^flood"}})

    # CORS
    def cors(origin):
        r = subprocess.run(["curl", "-s", "-D", "-", "-o", "/dev/null", "-X", "OPTIONS", f"{API}/api/scenes",
                            "-H", f"Origin: {origin}", "-H", "Access-Control-Request-Method: GET"], capture_output=True, text=True).stdout.lower()
        return "access-control-allow-origin" in r
    ok &= check("CORS: allowed origin gets ACAO", cors("https://app.katherinebeck.com"))
    ok &= check("CORS: evil origin gets no ACAO", not cors("https://evil.example"))

    # Cleanup test users + restore scene to legacy (do not alter content)
    await db.scenes.update_one({"id": SCENE}, {"$set": {"owner_email": None, "legacy": True}, "$unset": {"assigned_by": "", "assigned_at": ""}})
    for e in (B, C):
        await db.users.delete_one({"email": e}); await db.magic_links.delete_many({"email": e})
    print("\nALL PASS" if ok else "\nSOME FAILURES")
    sys.exit(0 if ok else 1)

asyncio.run(main())
