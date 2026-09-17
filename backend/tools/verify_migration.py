"""Read-only migration verifier: compares SOURCE and TARGET MongoDB databases.

Usage:
  SOURCE_URI="mongodb+srv://..." TARGET_URI="mongodb+srv://..." DB_NAME="<name>" \
    python tools/verify_migration.py [--samples 5]

Only find/count/aggregate/index reads are issued. Nothing is written.
Exit code 0 = all checks match, 1 = differences found.
"""
from __future__ import annotations

import argparse
import base64
import os
import random
import sys

from pymongo import MongoClient

EXPECTED_INDEXES = {
    "users": {"email_1": {"unique": True}},
    "magic_links": {"token_1": {"unique": True}, "email_1": {},
                    "expires_at_dt_1": {"expireAfterSeconds": 3600}},
    "memberships": {"user_email_1_offer_id_1": {"unique": True}},
    "webhook_events": {"provider_1_external_event_id_1": {"unique": True}},
    "scenes": {"owner_email_1": {}},
    "dictionary_entries": {"word_1": {"unique": True}, "status_1": {}},
    "caption_transcript_cache": {"caption_fulltext": {}},
}

MAGIC = {
    "audio/wav": (b"RIFF", "RIFF header"), "audio/x-wav": (b"RIFF", "RIFF header"),
    "audio/webm": (b"\x1a\x45\xdf\xa3", "EBML header"),
    "audio/ogg": (b"OggS", "Ogg header"),
    "audio/mp4": (None, ""), "audio/m4a": (None, ""),
    "audio/mpeg": (None, ""), "audio/mp3": (None, ""),
}


def connect(uri: str, name: str):
    c = MongoClient(uri, serverSelectionTimeoutMS=15000)
    c.admin.command("ping")
    return c[name]


def counts(db) -> dict:
    return {c: db[c].count_documents({}) for c in sorted(db.list_collection_names())}


def audio_stats(db) -> dict:
    ac = db["audio_cache"]
    by_type = {r["_id"] or "(none)": r["n"] for r in ac.aggregate([
        {"$match": {"manual_override": True}},
        {"$group": {"_id": "$content_type", "n": {"$sum": 1}}}])}
    total_bytes = next(ac.aggregate([
        {"$match": {"manual_override": True}},
        {"$group": {"_id": None, "b": {"$sum": {"$strLenBytes": {"$ifNull": ["$audio_b64", ""]}}}}}]),
        {"b": 0})["b"]
    return {"overrides": ac.count_documents({"manual_override": True}),
            "by_content_type": by_type, "base64_bytes": total_bytes,
            "generated": ac.count_documents({"manual_override": {"$ne": True}})}


def dict_stats(db) -> dict:
    de = db["dictionary_entries"]
    return {"done": de.count_documents({"status": "done"}),
            "skipped": de.count_documents({"status": "skipped"}),
            "with_audio": de.count_documents({"status": "done", "has_audio": True}),
            "custom_ipa": de.count_documents({"ipa_custom": True}),
            "pronunciation_prefs": db["pronunciation_prefs"].count_documents({})}


def index_report(db) -> dict:
    out = {}
    for coll, expected in EXPECTED_INDEXES.items():
        have = db[coll].index_information() if coll in db.list_collection_names() else {}
        for name, props in expected.items():
            info = have.get(name)
            ok = info is not None and all(info.get(k) == v for k, v in props.items())
            out[f"{coll}.{name}"] = "OK" if ok else f"MISSING/WRONG ({info})"
    return out


def sample_words(db, n: int) -> list:
    words = [d["word"] for d in db["audio_cache"].find({"manual_override": True}, {"word": 1})]
    random.seed(42)
    return sorted(random.sample(words, min(n, len(words))))


def recording(db, word: str) -> dict:
    d = db["audio_cache"].find_one({"word": word, "manual_override": True})
    if not d:
        return {"present": False}
    raw = base64.b64decode(d.get("audio_b64") or "")
    ct = d.get("content_type") or ""
    magic, label = MAGIC.get(ct, (None, ""))
    header_ok = True if magic is None else raw.startswith(magic)
    return {"present": True, "content_type": ct, "bytes": len(raw),
            "byte_size_field": d.get("byte_size"), "header_ok": header_ok, "header": label}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()
    src_uri, tgt_uri, name = os.environ.get("SOURCE_URI"), os.environ.get("TARGET_URI"), os.environ.get("DB_NAME")
    if not (src_uri and tgt_uri and name):
        print("Set SOURCE_URI, TARGET_URI and DB_NAME environment variables.")
        return 2
    src, tgt = connect(src_uri, name), connect(tgt_uri, name)
    problems = 0

    def section(title):
        print(f"\n== {title}")

    def compare(label, a, b):
        nonlocal problems
        ok = a == b
        problems += 0 if ok else 1
        print(f"  {'OK ' if ok else 'DIFF'}  {label:44} source={a!s:>12}  target={b!s:>12}")

    section("Collection document counts")
    sc, tc = counts(src), counts(tgt)
    for coll in sorted(set(sc) | set(tc)):
        compare(coll, sc.get(coll, "absent"), tc.get(coll, "absent"))

    section("audio_cache recordings")
    sa, ta = audio_stats(src), audio_stats(tgt)
    compare("manual overrides", sa["overrides"], ta["overrides"])
    compare("generated (ElevenLabs cache)", sa["generated"], ta["generated"])
    compare("override base64 bytes total", sa["base64_bytes"], ta["base64_bytes"])
    for ct in sorted(set(sa["by_content_type"]) | set(ta["by_content_type"])):
        compare(f"content_type {ct}", sa["by_content_type"].get(ct, 0), ta["by_content_type"].get(ct, 0))

    section("Dictionary")
    sd, td = dict_stats(src), dict_stats(tgt)
    for k in sd:
        compare(k, sd[k], td[k])

    section("Indexes / TTL on target")
    for k, v in index_report(tgt).items():
        ok = v == "OK"
        problems += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {k:44} {v}")

    section(f"Recording integrity sample ({args.samples})")
    for w in sample_words(src, args.samples):
        a, b = recording(src, w), recording(tgt, w)
        same = a == b
        problems += 0 if same else 1
        flag = "OK " if same and a.get("header_ok") else "FAIL"
        if same and not a.get("header_ok"):
            problems += 1
        print(f"  {flag}  {w:20} {a.get('content_type','?'):12} bytes={a.get('bytes')} "
              f"header={'valid' if a.get('header_ok') else 'BAD'} target_match={same}")

    print(f"\nRESULT: {'ALL CHECKS MATCH' if problems == 0 else f'{problems} DIFFERENCE(S) FOUND'}")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
