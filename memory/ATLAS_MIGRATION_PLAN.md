# Phase 2 — Move production MongoDB to your own Atlas (audit + plan)

Status: PLAN ONLY. Nothing has been changed. Awaiting approval.

## 1. Current production database (audit)

| Item | Finding | How verified |
|---|---|---|
| Deployment | Emergent-managed **MongoDB Atlas** shared cluster (`mongodb+srv://…`). Separate from the preview DB (preview = local `mongodb://localhost:27017`, Mongo 7.0). | Emergent platform docs via support |
| Connection | `server.py:70-72` → `AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]`. `prewarm.py` same. No other connection code. | code |
| Where the prod URL lives | Republish → **Secrets → System keys** (`MONGO_URL`, `DB_NAME`). Editable; changes persist across redeploys. | support |
| DB name | Production `DB_NAME` is shown in System keys (pattern `accent-coach-pro-<name>`). Confirm there. | support |
| Real data | All 17 collections below are read/written only through `db.<collection>`; production holds the live users, memberships, scenes, recordings, prefs, Stripe records. I cannot query production from the preview pod — sizes must be read from Republish → Database → Database Manager. | code |

### Collections the app uses (from code), what they hold, migration notes

| Collection | Holds | Preserve? | Notes |
|---|---|---|---|
| `users` | accounts, trial counters, `stripe_customer_id` | **YES** | unique index `email` |
| `memberships` | subscription rows (Stripe + manual grants) | **YES** | unique index `(user_email, offer_id)` |
| `scenes` | uploaded scenes, tokens, `owner_email` | **YES** | index `owner_email` |
| `audio_cache` | **your recordings** (`manual_override:true`, base64 audio) + ElevenLabs word cache | **YES** | no custom index; audio is inline base64 → dumped intact |
| `dictionary_entries` | My Dictionary index (word, IPA, status) | **YES** | unique `word`, `status` |
| `pronunciation_prefs` | preferred ARPABET per word | **YES** | none |
| `payment_transactions` | Stripe checkout sessions | **YES** | none |
| `webhook_events` | Stripe webhook idempotency | **YES** | unique `(provider, external_event_id)` |
| `magic_links` | pending sign-in tokens | yes (ephemeral) | unique `token`, `email`, **TTL** `expires_at_dt` 3600 s |
| `turn_audio_cache` | ElevenLabs line audio cache | nice-to-have | regenerates on demand (costs credits) |
| `caption_transcript_cache` | Real Speakers index (largest) | nice-to-have | **text index** `caption_fulltext` on `full_text`; re-ingest is hours |
| `caption_search_cache`, `caption_channel_cache`, `ipa_lookup_cache`, `hidden_videos`, `ingest_status`, `tts_log` | caches / small ops | yes | none |

All indexes above are (re)created automatically at app startup (`ensure_indexes`, `load_custom_ipa`, `_startup_indexes`, `ensure_local_indexes`) — and `mongorestore` also restores them from the dump's metadata. TTL index included.

### Portability
- Plain BSON documents, standard `motor`/`pymongo` driver, no `ObjectId` exposed, no GridFS, no Emergent object storage, no proprietary IDs. Audio is inline base64 in `audio_cache` → included in `mongodump` byte-for-byte.
- `mongodump` / `mongorestore` is fully sufficient. Preview-size reference: 27 MB total (17.5 MB captions, 8.6 MB line audio, 0.7 MB recordings). Production will be larger; each recording ≈ 50–150 KB.

## 2. Backup / rollback point (before anything changes)
1. Republish → **Database** tab → "Go to database" → Database Manager → **Dump DB** → download and keep `prod-backup-<date>` locally (and a copy in cloud storage).
2. Also copy the current `MONGO_URL` + `DB_NAME` values from System keys into a password manager (this is the rollback pointer).
3. Emergent keeps hourly/daily/PITR (7-day) backups of the managed DB; the old DB is not auto-deleted when `MONGO_URL` changes.
4. Optional belt-and-braces: Admin → My Dictionary → **CSV + audio (zip)** so the recordings also exist as plain files.

## 3. Atlas setup (you create; I don't need credentials until cutover)
- **Cluster**: M10 (dedicated, ~$0.08/h) if you want automatic backups + PITR; M0/M2 is fine to test but M0 has 512 MB cap and no backups. Region: same as Emergent (GCP us-central1) for latency. MongoDB 7.0+.
- **Database user**: `pronounce_app` with role `readWrite` on the app DB only (not Atlas admin). Strong password without `@ : / ? #` (URL-safe) or URL-encode it.
- **Network access**: allowlist **all** Emergent egress IPs from https://app.emergent.sh/ip-addresses (10 IPs as of now) **plus** your own laptop IP for the restore. Do not use 0.0.0.0/0 except briefly for testing.
- **Backups**: enable Cloud Backup + Continuous (PITR) on M10+.
- **Security**: TLS is on by default; leave Data API / public access off; enable Atlas alerts (connections, disk).
- Note connection string: `mongodb+srv://pronounce_app:<pwd>@<cluster>.mongodb.net/?retryWrites=true&w=majority`.

## 4. Cutover (est. 10–15 min user-visible read-only window, see §6)
1. **Freeze**: announce/pick a quiet time; no admin recording during cutover.
2. **Dump**: Database Manager → Dump DB (fresh, right before cutover).
3. **Restore**: from your laptop: `mongorestore --uri="<atlas-uri>" --nsFrom="<prodDb>.*" --nsTo="<newDb>.*" --drop ./dump` (or same DB name; keep `DB_NAME` consistent).
4. **Verify** (I'll give you a script or run it with the Atlas URI you paste in chat): per-collection document counts equal; `audio_cache` count with `manual_override:true` equal; sample 3 recordings decode to valid WAV/WebM; indexes present (`db.magic_links.getIndexes()` shows TTL).
5. **Switch**: Republish → Secrets → System keys → set `MONGO_URL` = Atlas URI, `DB_NAME` = restored db name → Save → **Re-publish changes**.
6. **Smoke test on app.katherinebeck.com**: `/api/` health; request magic link + sign in; `/api/auth/me` shows correct membership; open a scene; play a word that has your recording (must be your voice); My Dictionary progress count matches; Admin user table loads; Stripe: run a $0 test via Stripe test mode is not possible on live keys — instead check Admin → Payment health is green and trigger "Sync from Stripe" for one member; Real Speakers search returns clips.
7. **Watch** Atlas metrics + app logs for 24 h.

## 5. Rollback
- Republish → System keys → restore the saved original `MONGO_URL`/`DB_NAME` → Re-publish. The Emergent DB is untouched during the whole process, so this returns production to the exact pre-cutover state (plus any writes made to Atlas during the window — e.g. a new sign-up — which you'd re-apply manually or via a reverse dump/restore of just `users`/`memberships`).

## 6. Downtime
- Restore + redeploy typically 5–15 min. Writes made to the old DB between dump and switch would be lost, so the safe approach is a short **freeze window** (late night US time): dump → restore → switch → verify. Reads keep working throughout (old DB stays live until the redeploy). Zero-downtime live-sync (mongomirror/Live Migrate) is not available for the Emergent-managed source, and isn't worth the complexity at this size.

## 7. After cutover
- Old Emergent DB: ask support@emergent.sh about retention; keep it ~2 weeks as fallback, then request deletion.
- Preview environment stays on its local Mongo (unaffected).
- Future "Replace deployment → New DB" would overwrite your custom `MONGO_URL`; always choose "Existing DB".
