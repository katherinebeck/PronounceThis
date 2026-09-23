import os, asyncio, requests, secrets
from motor.motor_asyncio import AsyncIOMotorClient

API = [l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")][0]
SB = os.environ["SUPABASE_URL"] + "/auth/v1"; ANON = os.environ["SUPABASE_ANON_KEY"]
H = {"apikey": ANON, "Content-Type": "application/json"}
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]; loop = asyncio.get_event_loop()


def sb_signup(email, pw):
    return requests.post(f"{SB}/signup", headers=H, json={"email": email, "password": pw})

def sb_login(email, pw):
    return requests.post(f"{SB}/token?grant_type=password", headers=H, json={"email": email, "password": pw})

def me(token):
    return requests.get(f"{API}/api/auth/me", headers={"Authorization": f"Bearer {token}"})

tag = secrets.token_hex(3)
a, b = f"ptqaa{tag}@gmail.com", f"ptqab{tag}@gmail.com"
pw = "Passw0rd!" + tag

r = sb_signup(a, pw); assert r.ok, r.text; tok_a = r.json()["access_token"]; print("signup A ✓ (session issued → email confirmation is OFF)")
r = sb_signup(b, pw); assert r.ok, r.text; tok_b = r.json()["access_token"]
m = me(tok_a).json(); assert m["authenticated"] and m["email"] == a and m["trial_word_used"] == 0, m; print("backend /me via Supabase token ✓", m["email"])
u = loop.run_until_complete(db.users.find_one({"email": a}, {"_id": 0, "supabase_sub": 1, "trial_word_used": 1})); assert u and u["supabase_sub"]; print("Mongo user linked by supabase_sub ✓")

r = sb_login(a, "wrong-password-1"); assert r.status_code == 400, r.status_code; print("wrong password rejected ✓")
r = sb_login(a, pw); assert r.ok; print("login with correct password ✓")

# usage is enforced server-side per authenticated user
for w in ["one", "two", "three", "four", "five"]:
    assert requests.get(f"{API}/api/pronounce", params={"word": w}, headers={"Authorization": f"Bearer {tok_a}"}).status_code == 200
assert requests.get(f"{API}/api/pronounce", params={"word": "six"}, headers={"Authorization": f"Bearer {tok_a}"}).status_code == 402
assert requests.get(f"{API}/api/pronounce", params={"word": "six"}, headers={"Authorization": f"Bearer {tok_b}"}).status_code == 200
print("5-word limit enforced for A, independent for B ✓")

# isolation: B cannot read A's scene
scene_id = "iso-" + tag
loop.run_until_complete(db.scenes.insert_one({"id": scene_id, "title": "A's scene", "owner_email": a, "tokens": [], "turns": [], "raw_text": ""}))
assert requests.get(f"{API}/api/scenes/{scene_id}", headers={"Authorization": f"Bearer {tok_a}"}).status_code == 200
assert requests.get(f"{API}/api/scenes/{scene_id}", headers={"Authorization": f"Bearer {tok_b}"}).status_code == 404
assert requests.get(f"{API}/api/scenes/{scene_id}").status_code == 401
print("User B / anonymous cannot access A's scene ✓")

# forged / tampered tokens
assert me(tok_a[:-4] + "abcd").json()["authenticated"] is False
assert me("eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4IiwiZW1haWwiOiJ4QHkuY29tIn0.").json()["authenticated"] is False
print("tampered + alg=none tokens rejected ✓")

# existing (legacy) user linked by email on first Supabase login
legacy = f"ptqalegacy{tag}@gmail.com"
loop.run_until_complete(db.users.insert_one({"email": legacy, "email_key": legacy, "trial_word_used": 3, "trial_scene_used": 1, "created_at": "2026-01-01", "last_login_at": "2026-01-02"}))
loop.run_until_complete(db.memberships.insert_one({"user_email": legacy, "status": "active", "offer_title": "TEST_legacy", "source": "manual_grant", "subscription_end_at": None}))
r = sb_signup(legacy, pw); tok_l = r.json()["access_token"]
m = me(tok_l).json(); assert m["subscription_status"] == "active" and m["trial_word_used"] == 3, m
print("legacy account keeps membership + usage after first Supabase login ✓")


# logout = revoke session
requests.post(f"{SB}/logout", headers={**H, "Authorization": f"Bearer {tok_a}"})
print("logout call ✓ (client also clears local session)")

loop.run_until_complete(db.users.delete_many({"email": {"$in": [a, b, legacy]}}))
loop.run_until_complete(db.memberships.delete_many({"user_email": legacy}))
loop.run_until_complete(db.scenes.delete_many({"id": scene_id}))
loop.run_until_complete(db.trial_devices.delete_many({"emails": {"$in": [a, b, legacy]}}))
print("ALL OK — note: Supabase test users", a, b, legacy, "remain in Supabase Auth (delete in dashboard or via service key)")
