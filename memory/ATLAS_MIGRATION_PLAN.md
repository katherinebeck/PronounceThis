# Phase 2 — Move production MongoDB to your own Atlas: audit + migration plan

Status: AUDIT + PLAN ONLY. Nothing changed. Awaiting explicit approval before any step in §8.

## 1. Current production database
- **Hosting**: Emergent-managed MongoDB Atlas shared cluster (`mongodb+srv://…`), provisioned by the platform. Separate from preview (local `mongodb://localhost:27017`, Mongo 7.0.43).
- **Connection**: `server.py:70-72` → `AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]`; `prewarm.py:54-55` same. No other connection code, no hard-coded hosts.
- **Where the values live**: Republish → Secrets → **System keys** (`MONGO_URL`, `DB_NAME`); editable, persist across redeploys.
- **DB name / sizes / live counts**: NOT VERIFIABLE from the preview pod (no network path / no URL). Get them from Republish → Database → Database Manager, or paste the prod `MONGO_URL` for a read-only `collStats` report.

## 2. Compatibility
Standard MongoDB documents via `motor`/`pymongo`. No GridFS, no external file references, no ObjectId leakage, no Emergent SDK, no proprietary IDs (UUID strings + emails as keys). `mongodump`/`mongorestore` sufficient.

## 3. Collections (17, from code) — all restore as-is
users, memberships, scenes, audio_cache (recordings inline base64 + `content_type` per row: wav/webm/mp3), dictionary_entries, pronunciation_prefs, payment_transactions (Stripe checkouts), webhook_events (Stripe idempotency), magic_links, turn_audio_cache, caption_transcript_cache, caption_search_cache, caption_channel_cache, ipa_lookup_cache, hidden_videos, ingest_status, tts_log.

## 4. Indexes
users.email (unique); magic_links.token (unique), magic_links.email, **magic_links.expires_at_dt TTL 3600 s**; memberships (user_email, offer_id) unique; webhook_events (provider, external_event_id) unique; scenes.owner_email; dictionary_entries.word (unique), dictionary_entries.status; caption_transcript_cache text index `caption_fulltext`. All are in dump metadata (mongorestore recreates them) AND recreated idempotently at app startup.

## 5. Backups (before anything else)
A. Database Manager → Dump DB → local copy. B. Second copy to separate cloud storage. C. `MONGO_URL` + `DB_NAME` into password manager. D. Emergent DB untouched throughout. E. Keep My Dictionary CSV+audio zip as a third, format-independent backup; re-export as the library grows.

## 6-7. Atlas
M10 dedicated, GCP us-central1, MongoDB 7.0, storage auto-scaling ON, Cloud Backup + Continuous (PITR) ON; user `pronounce_app` readWrite on the one DB; allowlist Emergent egress IPs (https://app.emergent.sh/ip-addresses) + your IP; alerts on disk >70%. Sizing: 10k × (50–150 KB ×1.33 base64) ≈ 0.7–2.0 GB audio + caches → 2–4 GB over 2–3 yrs; M10 = 10 GB base, auto-scales, no cluster migration needed. Constraint: 16 MB/document cap irrelevant (one word per doc).

## 8-11. Cutover / smoke test / rollback / downtime
See chat response of this date (same content); freeze window ≈ 15–30 min; rollback = restore saved System keys + republish; writes during window need manual reconciliation (users/memberships/audio_cache/dictionary_entries/webhook_events).
