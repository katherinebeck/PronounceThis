"""Sound bank: one clean American take + deliberate-error takes for every vowel and consonant.

Error takes are Hannah (American voice) saying a real word that differs only in the target
sound (think → fink), or a British/Australian voice for accent-typical errors (car → non-rhotic).
Every clip is assessed against the TARGET word; the report says whether the target sound was
flagged, what the student would read, and the score.

Run: cd /app/backend && set -a && . ./.env && set +a && python3 tests/sound_bank.py [gen|run|both]
Clips: /tmp/pt_bank · Report: /app/memory/sound_bank_report.md
"""
import asyncio
import io
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import _issue_jwt  # noqa: E402

OUT = "/tmp/pt_bank"
API = os.environ.get("API_URL", "http://localhost:8001") + "/api"
VOICES = {"hannah": "ZSNL4hPqCnqoMPaI4jGX", "george": "JBFqnCBsd6RMkjVDRZzb", "lily": "pFZP5JQG7iQjIQuC4Bku", "tanya": "DusxpIechtn2D8hID1Jy"}
CTX = {
    "hannah": dict(previous_text="You're an American English coach from the Midwest speaking in your natural General American accent. Listen and repeat after me. The word is",
                   next_text="That's how we say it in American English. Now you try."),
    "other": dict(previous_text="Say the word in your own natural accent. The word is", next_text="Now you try."),
}
# target sound, target word, [(error label, spoken word, voice)]
BANK = [
    ("i", "sheep", [("ɪ", "ship", "hannah")]),
    ("ɪ", "ship", [("i", "sheep", "hannah")]),
    ("ɛ", "bed", [("æ", "bad", "hannah"), ("ɪ", "bid", "hannah")]),
    ("æ", "cat", [("ɑ", "cot", "hannah"), ("ɪ", "kit", "hannah")]),
    ("ɑ", "hot", [("ʌ", "hut", "hannah"), ("AU ɒ", "hot", "tanya")]),
    ("ɔ/ɑ", "caught", [("oʊ", "coat", "hannah"), ("ʌ", "cut", "hannah")]),
    ("ʊ", "book", [("ʌ", "buck", "hannah")]),
    ("u", "food", [("ju", "feud", "hannah")]),
    ("ʌ", "cup", [("ɑ", "cop", "hannah"), ("æ", "cap", "hannah")]),
    ("eɪ", "face", [("ʌ", "fuss", "hannah")]),
    ("aɪ", "time", [("eɪ", "tame", "hannah"), ("ɑ", "tom", "hannah")]),
    ("oʊ", "boat", [("ɔ", "bought", "hannah"), ("AU əʉ", "boat", "tanya")]),
    ("aʊ", "house", [("oʊ", "hose", "hannah")]),
    ("ɔɪ", "boy", [("aɪ", "buy", "hannah")]),
    ("ɝ", "bird", [("UK no r", "bird", "george"), ("ʌ", "bud", "hannah")]),
    ("ɚ", "mother", [("UK no r", "mother", "george")]),
    ("ɑɹ", "car", [("UK no r", "car", "george"), ("ɔ", "caw", "hannah")]),
    ("ɔɹ", "horse", [("UK no r", "horse", "george")]),
    ("ɛɹ", "chair", [("UK no r", "chair", "george")]),
    ("ɪɹ", "fear", [("UK no r", "fear", "george")]),
    ("ʊɹ", "tour", [("UK no r", "tour", "george")]),
    ("p", "pin", [("b", "bin", "hannah")]),
    ("b", "bat", [("p", "pat", "hannah")]),
    ("t", "toes", [("d", "doze", "hannah")]),
    ("t (flap)", "water", [("UK hard t", "water", "lily")]),
    ("d", "day", [("ð", "they", "hannah")]),
    ("k", "coat", [("g", "goat", "hannah")]),
    ("ɡ", "goat", [("k", "coat", "hannah")]),
    ("f", "fan", [("v", "van", "hannah"), ("p", "pan", "hannah")]),
    ("v", "van", [("f", "fan", "hannah"), ("b", "ban", "hannah")]),
    ("θ", "think", [("f", "fink", "hannah"), ("s", "sink", "hannah")]),
    ("ð", "then", [("d", "den", "hannah"), ("z", "zen", "hannah")]),
    ("s", "sip", [("z", "zip", "hannah"), ("ʃ", "ship", "hannah")]),
    ("z", "zoo", [("s", "sue", "hannah")]),
    ("ʃ", "ship", [("s", "sip", "hannah")]),
    ("tʃ", "chip", [("ʃ", "ship", "hannah"), ("t", "tip", "hannah")]),
    ("dʒ", "jam", [("j", "yam", "hannah"), ("ʃ", "sham", "hannah")]),
    ("h", "hat", [("dropped", "at", "hannah")]),
    ("m", "map", [("n", "nap", "hannah")]),
    ("n", "net", [("m", "met", "hannah")]),
    ("ŋ", "sing", [("n", "sin", "hannah")]),
    ("l", "light", [("ɹ", "right", "hannah")]),
    ("ɹ", "right", [("l", "light", "hannah"), ("w", "white", "hannah")]),
    ("w", "wet", [("v", "vet", "hannah")]),
    ("j", "yes", [("dʒ", "jess", "hannah")]),
]


def clip_path(voice: str, spoken: str) -> str:
    return f"{OUT}/{voice}_{spoken}.mp3"


def gen() -> None:
    from elevenlabs.client import ElevenLabs
    os.makedirs(OUT, exist_ok=True)
    c = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    todo = {("hannah", w) for _, w, _ in BANK} | {(v, s) for _, _, errs in BANK for _, s, v in errs}
    for voice, spoken in sorted(todo):
        path = clip_path(voice, spoken)
        if os.path.exists(path):
            continue
        kw = CTX["hannah"] if voice == "hannah" else CTX["other"]
        stream = c.text_to_speech.convert(text=spoken, voice_id=VOICES[voice], model_id="eleven_v4", language_code="en",
                                          output_format="mp3_44100_128", **kw)
        with open(path, "wb") as f:
            f.write(b"".join(ch for ch in stream if ch))
        print("wrote", path)


def _base(sym: str) -> set:
    return set(sym.split(" ")[0].split("/"))


async def assess(c: httpx.AsyncClient, cookies: dict, word: str, path: str) -> dict:
    audio = open(path, "rb").read()
    for attempt in range(3):
        r = await c.post(f"{API}/practice/assess", data={"word": word}, files={"audio": (os.path.basename(path), io.BytesIO(audio), "audio/mpeg")}, cookies=cookies)
        if r.status_code != 503 or attempt == 2:
            break
        await asyncio.sleep(3)
    return {"http": r.status_code, **(r.json() if r.headers.get("content-type", "").startswith("application/json") else {})}


def describe(b: dict, target: str) -> tuple:
    """(flagged?, student line) for the target sound."""
    if b.get("http") != 200:
        return None, f"HTTP {b.get('http')} {b.get('detail')}"
    if not b.get("assessable"):
        return None, f"unassessable: {b.get('reason')}"
    items = [n for n in b.get("needs_work", []) if n["phoneme"] in target]
    extras = [n for n in b.get("needs_work", []) if n["phoneme"] not in target]
    line = f"{b.get('score10')}/10 {b.get('band')}"
    if items:
        n = items[0]
        kind = "not heard" if n.get("confirmed") else ("extra sound" if n.get("intrusion") else ("held" if n.get("overdone") else f"weak {round(n.get('score') or 0)}/100"))
        line += f" · /{n['phoneme']}/ {kind}" + (f" → {n['heard']}" if n.get("heard") else "") + (f" · “{n['note']}”" if n.get("note") else "")
        return True, line
    if extras:
        line += " · other flags: " + ", ".join(f"/{n['phoneme']}/" + ("*" if n.get("confirmed") else "") for n in extras)
    return False, line


async def run() -> None:
    cookies = {"accent_session": _issue_jwt(os.environ["ADMIN_EMAILS"].split(",")[0].strip())}
    rows, caught, total, clean_ok, clean_total = [], 0, 0, 0, 0
    async with httpx.AsyncClient(timeout=120) as c:
        for target, word, errs in BANK:
            tgt = _base(target)
            b = await assess(c, cookies, word, clip_path("hannah", word))
            flagged, line = describe(b, tgt)
            clean_total += 1
            ok = b.get("http") == 200 and b.get("assessable") and (b.get("score10") or 0) >= 8.5 and not flagged
            clean_ok += bool(ok)
            rows.append((target, word, "clean (Hannah)", "✓ pass" if ok else "✗ FALSE FLAG", line))
            print(f"/{target}/ {word:<8} clean   {'ok ' if ok else 'BAD'} {line}")
            for label, spoken, voice in errs:
                b = await assess(c, cookies, word, clip_path(voice, spoken))
                flagged, line = describe(b, tgt)
                total += 1
                caught += bool(flagged)
                rows.append((target, word, f"{label} — “{spoken}” ({voice})", "✓ caught" if flagged else ("✗ missed" if flagged is False else "– n/a"), line))
                print(f"/{target}/ {word:<8} {label:<10} {'CAUGHT' if flagged else 'missed'} {line}")
    md = ["# Sound bank — deliberate-error recordings vs Practise This Word", "",
          f"Errors caught: **{caught}/{total}** · clean American takes passing (≥8.5, target not flagged): **{clean_ok}/{clean_total}**", "",
          "| Target | Word | Take | Result | What the student reads |", "|---|---|---|---|---|"]
    md += [f"| /{t}/ | {w} | {take} | {res} | {line} |" for t, w, take, res, line in rows]
    with open("/app/memory/sound_bank_report.md", "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"\ncaught {caught}/{total} · clean pass {clean_ok}/{clean_total} → /app/memory/sound_bank_report.md")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode in ("gen", "both"):
        gen()
    if mode in ("run", "both"):
        asyncio.run(run())
