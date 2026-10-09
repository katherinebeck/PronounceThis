# The Accent Workbench — PRD

## Original problem statement
> I am an American accent coach help me design something that helps my students. I want to take a pdf of an audition scene and transcribe it for the actor in the sounds of the american accent with the phonetic symbols and also sounds so they can press on a word and hear how it is pronounced. I want to be able to make laundry lists of particular sounds from the scene. for example a list of all the words that contain the consonant l so the actor can practice the consonant l within those words outside of speaking the scene.

## User personas
- **The accent coach** — uploads a student's audition PDF, scans phonetic transcriptions, and assembles targeted drills.
- **The actor / student** — reads the scene with IPA, taps individual words to hear the General American pronunciation, and grinds focused sound lists.

## Architecture
- **Frontend**: React (CRA) + Tailwind, design system "Editorial Linguistics Workbench" (Cormorant Garamond / Crimson Text / IBM Plex Mono on a warm-paper palette). Dual-pane layout (Scene Library | Scene Reader | Laundry Lists). No auth — scenes persist server-side and load on visit.
- **Backend**: FastAPI under `/api` prefix. MongoDB (`scenes`, `audio_cache` collections). pypdf for text extraction.
- **Phonetics engine** (`backend/phonetics.py`): `pronouncing` (CMU) → ARPABET → custom IPA mapping; classifier detects rhotic R, light/dark L, flap T, schwa, diphthongs, and per-phoneme consonants.
- **LLM fallback**: Claude Sonnet 4.5 via `emergentintegrations` for words not in CMU.
- **TTS**: ElevenLabs (`eleven_multilingual_v2`, voice `21m00Tcm4TlvDq8ikWAM` — Rachel). Per-word base64 mp3 cached in MongoDB.

## Core requirements (static)
1. Upload a text-based PDF and parse it into ordered tokens (words + punctuation/whitespace preserved).
2. Each word carries: text, IPA, ARPABET phones, sound categories, source ("cmu" | "llm" | "none").
3. Click any word → ElevenLabs audio playback, cached locally + server-side.
4. Build laundry lists by sound category with practice mode (prev/next, click-to-hear).
5. Scene library: list, open, delete; auto-loads most recent scene on visit.

## Implemented (May 3, 2026)
- Backend endpoints: `GET /api/`, `GET /api/sound-categories`, `POST /api/scenes/upload`, `GET /api/scenes`, `GET /api/scenes/{id}`, `DELETE /api/scenes/{id}`, `GET /api/scenes/{id}/laundry-list?sound=...`, `POST /api/tts`.
- 19 sound categories with linguist-grade detection (light vs dark L, intervocalic flap T/D, AH0 → schwa, etc.).
- React UI matching the design guidelines exactly (verified via screenshot): word blocks with English+IPA, hover/active states, scene highlighting from active list, practice card with arrow nav.
- 20 backend pytest cases (100% pass) at `/app/backend/tests/test_accent_coach.py`.

## Added (Feb 2026)
- **Custom Real-Speaker Caption Search** replaces the YouGlish widget entirely.
  - `GET /api/caption-search?q=<word>` searches a curated allowlist of 19 American-English YouTube channels (NPR, CBS News, PBS, ABC, CNN, 60 Minutes, Fallon, Ellen, Conan, Kimmel, Colbert, Hot Ones, Vanity Fair, GQ, Variety, TED-Ed, Vox, CrashCourse, WIRED).
  - Uses YouTube Data API v3 (parallel per-channel search) → `videos.list` embeddability check → yt-dlp caption download → server-side word/timestamp match.
  - Aggressive Mongo caching: 30-day TTL for successful hits, 1-hour miss TTL so temporary YouTube rate limits self-heal.
  - Hybrid fallback: if transcript is unavailable, still returns the video with `has_timestamp=false` so users see results.
  - Custom `<CaptionSearchModal>` embeds the youtube-nocookie player at the exact caption timestamp — zero third-party branding, zero Fluently promo.
  - 6 new pytest cases at `/app/backend/tests/test_caption_search.py` (all passing).

## Known limitations
- The provided **ElevenLabs key is on the Free tier**, which the provider blocks from cloud datacenter IPs ("detected_unusual_activity"). Upgrading the ElevenLabs plan unlocks real audio playback. All other features are unaffected.
- **YouTube throttles cloud-provider IPs** for caption fetches. First-time transcript fetches may fall back to whole-video mode until the cache warms. Repeat queries are instant (Mongo cached).

## Backlog
### P0 (blocked on user action)
- Upgrade ElevenLabs subscription (or supply a paid key) to enable audio.

### P1
- Pre-warm TTS cache: on scene upload, pre-generate audio for the top-N most relevant words (e.g. all words in the largest laundry list).
- Adjustable playback speed (0.5×, 0.75×, 1×) for slow-down practice.
- Voice selector (Rachel / Adam / Bella) and accent variants.

### P2
- Stress-syllable highlighting in the IPA (color the ˈ-marked syllable nucleus).
- Compare-and-record: actor records themselves, side-by-side with the model audio.
- PDF export of a laundry list as a printable practice handout.
- Multi-coach accounts (would introduce auth — Emergent Google login is a clean drop-in).

## Added (Feb 5, 2026)
- **YouGlish-style Real Speakers modal redesign** (`CaptionSearchModal.jsx`).
  - Removed the text-heavy sidebar entirely.
  - Single video player fills the modal, autoplayed and cued to the exact caption timestamp.
  - `Prev` / `Next` buttons (and ← / → arrow keys) cycle through the cached list of clips.
  - Filters out non-timestamped "full video" fallbacks — only cued clips shown.
  - Minimal footer: `CHANNEL · CLIP n OF N` + compact "Open on YouTube" link.

## Added (Feb 5, 2026 — Admin panel)
- Owner admin panel at `/admin` — accessible only to emails in the `ADMIN_EMAILS` env var (currently `katherine@katherinebeck.com`).
- Backend `/api/admin/*` routes: `whoami`, `memberships`, `memberships/cancel`, `memberships/grant`, `users`, `events`.
- Purpose: manual cancellation on Kajabi plans without Public API access (Basic/Growth), plus manual grants for group-coaching students and refunds.
- Frontend: `AdminPage.jsx` with a searchable user table, per-user Cancel button, and a Grant Access form (email + offer title + optional expiry in days).

## Added (Feb 5, 2026 — Production launch)
- Deployed to production at **https://accent-coach-pro.emergent.host** ✅
- Monthly offer configured: `https://www.katherinebeck.com/offers/tHhcLLoy`
- Annual offer configured: `https://www.katherinebeck.com/offers/VWxogPVj`
- Per-offer Purchase Created webhook wired for both offers (Kajabi Path A).
- Kajabi setup guide `/app/memory/KAJABI_SETUP.md` updated with production URLs.

## Added (Feb 5, 2026 — Phase 1: Kajabi-gated subscriptions)
- **Magic-link email auth** via Resend (`/app/backend/auth.py`, `/app/frontend/src/lib/auth.jsx`).
  - `POST /api/auth/request-magic-link` sends a 15-min one-tap link, rate-limited to 1/min per email.
  - `GET /api/auth/verify?token=…` consumes the link and sets a httpOnly JWT session cookie.
  - `GET /api/auth/me` returns auth state + subscription state + trial counters + Kajabi offer URLs.
  - `POST /api/auth/logout` clears the cookie.
- **Trial model** — every logged-in user gets 1 free word TTS + 1 free scene upload before hitting the paywall.
- **Kajabi webhook receiver** (`/app/backend/kajabi.py`).
  - `POST /api/kajabi/webhook?token=…` handles Purchase Created + Payment Succeeded events. Bearer-token protected (Kajabi doesn't sign webhooks). Idempotent via `webhook_events` collection.
  - `POST /api/kajabi/cancel?token=…` receives the cancellation Automation trigger; honors `subscription_end_at`.
  - Auto-creates a shell `users` row if a customer buys on Kajabi before signing into the app.
- **Access gate** wired to `POST /api/tts` (word trial), `POST /api/scenes/upload` (scene trial), and `GET /api/scenes/{id}/download-lines` (subscribers only).
- **Frontend** — `LoginModal`, `PaywallModal`, `VerifyPage`, `AccountChip`, `AuthProvider`. Global axios interceptor opens login on 401 / paywall on 402.
- **Kajabi setup guide** at `/app/memory/KAJABI_SETUP.md` — step-by-step instructions the user can follow to create offers + hook them into our webhooks.

## Added (Feb–Sep 2026 session)
- **Rebrand → "American Accent Prep"** across UI, emails, Stripe products.
- **Magic-link auth via Resend** with 90-day sessions (`/app/backend/auth.py`).
- **Standalone Stripe subscriptions** ($9/mo, $90/yr) — replaced Kajabi as the payment gateway (`/app/backend/stripe_payments.py`). Kajabi env vars kept for backward compat but no longer used.
- **Admin panel** at `/admin` — manual grants, cancellations, user list, webhook events, pronunciation overrides, and **Stripe resync** (new).
- **Welcome walkthrough modal** for first-time signed-in users.
- **Real Speakers** feature: YouGlish-style single-video player with prev/next, 58 curated American-speaker YouTube channels + all-of-YouTube fallback when the allowlist returns nothing.
- **Manual pronunciation overrides**: admin uploads MP3s for words ElevenLabs mispronounces (bypasses TTS entirely for those words).
- **Custom domain** `app.katherinebeck.com` linked.
- **Resend production sender**: `login@katherinebeck.com` (verified in Resend dashboard).
- **Stripe self-heal** — `/api/auth/me` now silently resyncs from Stripe (rate-limited 5 min) if a user has no active membership row. Also exposed as an admin utility: `POST /api/admin/stripe/sync {email}` + UI button on the admin panel.
- **Stripe SDK v15 compatibility fix (Sep 6 2026)** — SDK v15 removed dict-style `.get()` from StripeObject; all our webhook + sync code was silently failing. Added `_to_dict()` helper that flattens Stripe objects to plain dicts at every boundary. Root cause of the "paid but shows Free Trial" bug for `info@katherinebeck.com`.
- **Payment health monitoring** — `GET /api/admin/payment-health` lists users with a Stripe customer but no active membership AND any webhook events with handler errors. Rendered as a red banner at the top of `/admin` when anything is off, with per-user "Fix" buttons. Webhooks that fail processing now return 500 so Stripe retries automatically.
- **Copy magic link** button on the admin user list — mints a 15-min single-use sign-in URL per row for in-person student handoffs.
- **Contact support** display (`info@katherinebeck.com`) in the account dropdown menu.
- **Regression tests** (`/app/backend/tests/test_stripe_sdk_compat.py`) — lock in the Stripe v15 `.get()` fix so it can't regress silently.

## Next tasks
1. **[P1]** Add playback speed toggles (0.5× / 0.75× / 1×).
2. **[P2]** Session notes: coach jots homework alongside words/scenes.
3. **[P2]** Homework link: shareable read-only URL for students.
4. **[P2]** Merriam-Webster audio integration (waiting on API key).
5. **[P2]** Full local caption index (ingest transcripts to MongoDB to bypass YouTube API limits).
6. **[Refactor]** Split `server.py` (~1150 lines) into `routes/` + `services/`.


## 2026-06 — Portability / vendor-lock-in audit
- Audit result: MongoDB, Stripe SDK, Resend, ElevenLabs, YouTube Data API, JWT auth, base64 audio overrides in Mongo are all standard/portable. Only Emergent-specific runtime dependency was the LLM fallback.
- Added `backend/llm.py`: provider-agnostic `complete(system, user)`; prefers official `anthropic` SDK via `ANTHROPIC_API_KEY`, falls back to `emergentintegrations`/`EMERGENT_LLM_KEY` only when Anthropic key is unset. `server.py` dialogue extraction + IPA fallback now use it.
- Removed hardcoded `sk_test_emergent` Stripe placeholder (fail-fast on missing key).
- Rewrote `/app/README.md` as a hand-off doc: stack, run-anywhere instructions, full env var table, mongodump/mongorestore export, collection inventory, Stripe data ownership note.
- To fully drop the Emergent key: set `ANTHROPIC_API_KEY` in backend env; `emergentintegrations` then becomes unused and can be removed from requirements.

- ANTHROPIC_API_KEY added to preview backend/.env; LLM calls verified hitting api.anthropic.com directly (Emergent key no longer used when set). User must add same var to production deployment secrets.
- Custom domain verified: app.katherinebeck.com/api live; magic links, admin links, Stripe return URLs all derive from request Origin; sender login@katherinebeck.com.
- Added Admin "Your data" section: GET /api/admin/export/users.csv and /memberships.csv (admin-gated, Content-Disposition filename with date). Verified via curl + browser download.

## 2026-06 — Real Speakers accuracy pass
- APP_PUBLIC_URL in backend/.env now https://app.katherinebeck.com (ships with next re-publish; secrets are set via chat + re-publish on this platform).
- caption_search.py: removed non-curated "top-up" pool in live YouTube search; removed unverified (no-timestamp) fallback results; local index results now require curated channel_id + embeddable check (flag persisted per video); cached query results are filtered at read time to verified + currently-curated only (auto re-search if none left); _scan_video persists channel_meta; channel ingest checks embeddability first.
- Curated list trimmed 81 → 72: removed TED, TED-Ed, Numberphile, Linus Tech Tips, Kurzgesagt, Bloomberg, Lex Fridman, Genius, NPR Music (non-American / international / music-heavy).
- CaptionSearchModal: shows caption line with the word highlighted + "Said at h:mm:ss"; playback starts 1s before the cue.
- Known limitation: US news channels can still feature non-American interviewees/correspondents; accent cannot be detected from captions.

## 2026-06 — YouGlish-parity pass (word-level cueing, ranking, deeper index)
- Parsers (json3 + VTT) now capture per-word timestamps into `w` on each segment; `_find_word_in_transcript` cues to the word (precise) or interpolates within the segment; returns rank metadata.
- `_score_hit` ranking: precise cue +3, short segment +2, 4–14 words +1.5, penalize `>>`/`[Music]`. `_rank` round-robins channels.
- Query cache versioned (`CACHE_VERSION=2`) so old segment-level results are recomputed.
- Ingest: per_channel_limit 50 → 200 (cron + admin), stores `has_word_timing`/`embeddable`; entries lacking word timing are re-fetched on next ingest. Livestreams >30k segments drop `w` to stay under 16MB.
- Fixed 4 unresolved handles: joerogan, SaturdayNightLive, timferriss, HISTORY (72/72 resolve).
- Frontend: lead-in 1s for precise cues, 2s for interpolated.
- Reporting/thumbs-down explicitly declined by user.

## 2026-06 — Misspellings, TTS accuracy, hero copy
- Spelling fallback: `suggest_spelling()` (Claude) in server.py. `/api/caption-search` retries with the corrected word when zero results and returns `corrected_query` (modal shows "Showing results for …"). `/api/pronounce` returns `suggestion` on CMU misses when the corrected form is in CMU; UI shows clickable "Did you mean …?".
- TTS: `/api/tts` now uses `eleven_turbo_v2` with CMU-Arpabet `<phoneme>` tags per dictionary word (`_phoneme_markup`), so audio matches the on-screen IPA. `TTS_VERSION=2` — non-override cached audio regenerates lazily (costs ElevenLabs credits once per word). Manual overrides untouched. Scene-line TTS (`_synthesize`) unchanged (multilingual_v2). Verified "Harry" audio via transcription: natural American, rhymes with hairy/carry.
- Caveat: CMU errors now propagate to audio (e.g. CMU has Hermione as her-mee-OH-nee). Use Admin override for such names.
- Hero copy: "Pronounce it." / "Scene preparation." with kickers updated; H1/H2 reduced to text-3xl/4xl/5xl. Header brand "American Accent Prep." left unchanged.

## 2026-06 — Laundry list categories reduced to coach's set
- SOUND_CATEGORIES now: L, T, Rhotic R; vowels i ɪ ɛ æ ə ʌ u ʊ ɔ ɑ; diphthongs eɪ aɪ oʊ aʊ ɔɪ each as its own list. Removed light/dark L, flap T, TH/SH/ZH/CH/NG/D/S/Z, combined "Diphthongs".
- `classify_word` rewritten (ARPABET map; AH0→ə, AH1/2→ʌ); new `classify_ipa` for LLM-transcribed words. `_refresh_categories` recomputes categories on GET scene + laundry-list so old scenes use the new scheme.
- Removed "Did you mean" from pronounce (user request); caption-search auto-correct kept.

## 2026-06 — TTS hybrid (fix "because"/"in" sounding wrong)
- Root cause: turbo_v2 + CMU tags for ALL words; CMU's first entry for "because" is B IH0 K AO1 Z (be-CAWZ) and isolated function words rendered unnaturally.
- Hybrid: `TTSRequest.phonetic` flag. Proper nouns (scene `is_proper_noun`, laundry-list `is_proper_noun`, Pronounce page `looksProper`) → eleven_turbo_v2 + phoneme tags, cached under `word#ph` (tts_version 2). Ordinary words → original eleven_multilingual_v2 plain, cached under `word` (tts_version 3; legacy no-version entries accepted; v2 turbo renders rejected & regenerated).
- `PREFERRED_ARPA` in phonetics.py overrides CMU first entry ("because" → B IH0 K AH1 Z → bɪkˈʌz). `_refresh_categories` also refreshes IPA/arpabet for CMU tokens on scene load so saved scenes show the corrected IPA.

## 2026-06 — Preferred Pronunciations (Admin), Wiktionary IPA, scene-line phonemes
- Admin section `PronunciationPrefs.jsx`: look up word → CMU variants with IPA → click to set, or custom ARPABET with live preview. Endpoints: GET /api/admin/pronunciations, GET /api/admin/pronunciations/options?word=&arpabet=, POST /api/admin/pronunciations, POST /api/admin/pronunciations/delete. Stored in `pronunciation_prefs`; loaded into `phonetics.PREFERRED_ARPA` at startup; set/delete invalidates `audio_cache` (word, word#ph) and `turn_audio_cache` lines containing the word (turn cache now stores `text`).
- Words in PREFERRED_ARPA force phonetic TTS (turbo_v2 + tags). Scene lines containing a preferred word are rendered with inline phoneme tags on eleven_turbo_v2 (`_preferred_markup`); other lines unchanged (multilingual_v2). Verified "because Mary's the smart one" → be-CUZ.
- `wiktionary.py`: GA IPA for CMU misses (parses English section, prefers US-tagged / non-British / stressed forms; caches in `ipa_lookup_cache`). Order: CMU → Wiktionary → Claude. Source "wiktionary" on tokens and /pronounce.
- User waiting on Merriam-Webster commercial license; recording queue idea discussed (user willing to record) — not built yet.

## 2026-06 — Trial 3 words + admin delete user
- TRIAL_WORD_LIMIT 1 → 3 (auth.py); copy updated in LoginModal, WelcomeModal, PaywallModal, AccountChip; auth.jsx default 3.
- POST /api/admin/users/delete {email}: deletes user + memberships + magic links (refuses self). Trash button per user row in Admin.

## 2026-06 — Real Speakers coverage: 115 channels, auto re-ingest
- Curated list 72 → 115 (TED re-added at user request; Fox News, WaPo, WSJ, NYT, GMA, The View, Dr. Phil, MrBeast, Mark Rober, Emma Chamberlain, Khan Academy, Stanford, Harvard, MIT OCW, Yale, NASA, The Atlantic, ABC/CBS/NBC, Netflix, BuzzFeedVideo, NFL Network, NBC Sports, Club Shay Shay, Call Her Daddy, Mel Robbins, Bill Maher, Aspen Institute, Talks at Google, Gizmodo, ScreenRant, CinemaSins, Johnny Harris, Wendover, PolyMatter, Cleo Abram, Smithsonian American Art Museum (@americanartmuseum), Smithsonian, SciShow Space, Obama White House, White House). All 115 resolve.
- Live search: videoCaption=closedCaption, scans 16 candidates, 6s budget.
- Startup supervisor re-runs full ingest when the channel-list signature (`ingest_status.channel_sig`) changes — no manual click needed after deploy. Ingest is ~23k videos; runs hours in background; yt-dlp 429s are cached as 1h misses and retried on the next pass.
- Open: "intoxication" still 0 until the deeper index is built (title search can't find words only spoken in captions).

## 2026-06 — Recording Queue + Hidden videos
- `tts_log` {word,count,last_at,phonetic,dismissed}: written on every synthetic /api/tts play (not overrides). GET /api/admin/recording-queue (excludes words with manual overrides), POST /api/admin/recording-queue/dismiss.
- `RecordingQueue.jsx` (Admin): MediaRecorder mic capture → preview → Save & next (POST /admin/pronunciation-overrides multipart, now accepts "audio/webm;codecs=opus") → Skip. /api/tts now returns the override's real mime.
- `hidden_videos` {video_id, reason, title, channel_title}: GET/POST /api/admin/hidden-videos, POST /api/admin/hidden-videos/delete. CaptionSearchService filters hidden ids in cached reads, local index and live results (60s in-memory cache). `HiddenVideos.jsx` in Admin. Hidden: _Sjvjvbz5X0 (CBS, "Gavin" speaker) — in PREVIEW DB only; user must re-hide in production via Admin (or I add it as a seed).

## 2026-06 — Admin links never expire + editable access end date
- Admin-issued magic links (POST /api/admin/magic-link) now expire in 10 years (still single-use); response expires_at=null. Emailed self-service links remain 15 min.
- POST /api/admin/memberships/set-end {email, subscription_end_at: 'YYYY-MM-DD'|null}: edits/creates the manual_grant membership end (null = no end); refuses Stripe-paid members. Admin "Ends" column is click-to-edit (date input + save/cancel).

## 2026-06 — Security hardening (authorized after audit)
- Scenes: `owner_email` + `legacy` fields. Upload stamps owner. `_load_owned_scene` gate (owner or admin; 404 otherwise) on GET/reparse/DELETE/laundry-list/download-lines/turn TTS. GET /scenes scoped to owner. Startup migration marks pre-existing scenes owner_email=None, legacy=True (content untouched). Admin: GET /api/admin/scenes?unowned_only, POST /api/admin/scenes/assign; `LegacyScenes.jsx` in Admin. Frontend: server list authoritative (App.js refreshScenes → listScenes on auth change).
- No claim-by-possession (user declined). Legacy scenes admin-only until assigned.
- Gating: caption-search requires login (60/h/user, refresh 10/h). pronounce: 60/min/IP, Claude fallback only for logged-in users (30/h). Turn TTS owner-gated.
- Rate limits (in-process sliding window, auth.py `rate_limit`): magic-link 5/email/h + 20/IP/h (429) before the existing 1/min silent limiter.
- CORS: explicit list from CORS_ORIGINS (fallback APP_PUBLIC_URL); wildcard ignored. Preview .env set to app.katherinebeck.com + preview URL. PRODUCTION: set CORS_ORIGINS secret (or rely on APP_PUBLIC_URL fallback).
- Stripe: past_due keeps access (dunning) until subscription.deleted/unpaid/canceled.
- Verification script: backend/tests/verify_isolation.py (21 checks, ALL PASS).
- Scene storage: avg 20 KB / max 84 KB per scene; 100+ scenes/user is negligible (turn audio cache ~89 KB per line is the larger cost).

## 2026-06 — Laundry lists: r-colored vowels are Rhotic R only
- `phonetics.classify_word` / `classify_ipa`: a vowel or diphthong followed by ER, or by a syllable-closing R (R not followed by a vowel), is dropped from its vowel/diphthong list and counted under Rhotic R only (star, for, air, here, poor, card, fire, hour, player). Vowel + R across a syllable boundary keeps the vowel (very, sorry, Mary, hero, starry) — per coach's choice.
- Existing scenes update automatically via `_refresh_categories` on load. Tests: `backend/tests/test_r_colored_vowels.py` (16 pass). Verified live on the "Little House" scene.

## 2026-06 — My Dictionary builder + recording clean-up
- `frontend/src/lib/audioTrim.js`: every mic take is decoded, the first/last 120 ms (Record/Stop click) hard-cut, leading/trailing silence trimmed (adaptive −38 dB / 4× noise floor), 8 ms fades, resampled to 24 kHz mono WAV. `lib/useRecorder.js` hook shared by RecordingQueue + DictionaryBuilder.
- `backend/dictionary.py` (router `/api/admin/dictionary/*`): queue (A→Z through 124,911 clean CMU headwords, skipping done/skipped), word, entry (multipart word+ipa+optional audio), skip, entries (search), entries/delete, audio, export.csv, export.zip (csv + audio/<word>.ext). Collection `dictionary_entries` {word, ipa, cmu_ipa, ipa_custom, categories, has_audio, content_type, status done|skipped}. Audio still stored as `audio_cache` manual_override (served by /api/tts). Startup `load_custom_ipa` backfills entries from existing overrides.
- `phonetics.CUSTOM_IPA` (coach-typed IPA) wins over CMU in `transcribe_word` and `_refresh_categories` → scenes, laundry lists, Pronounce page show her IPA; categories via classify_ipa.
- Admin UI `DictionaryBuilder.jsx` (+ `IpaPalette.jsx`, `DictionaryTable.jsx`): progress bar, jump-to-word, big word, editable IPA prefilled from CMU with click-to-insert palette, Record/Stop/Listen/Save & next/Skip, Space = record toggle, Enter = save, cursor remembered in localStorage; searchable table with play/delete + CSV/zip export. RecordingQueue now saves through the dictionary endpoint (so its recordings appear in the table).
- Tested: iteration_21 (backend 18/18, frontend flows pass; mic flow not testable headlessly — user to verify trim quality). Merriam-Webster integration now unnecessary (user's own recordings).

## 2026-06 — Removed "Unassigned scenes" section from Admin (user request)
- `LegacyScenes.jsx` deleted; `/api/admin/scenes` endpoints kept. Legacy scenes remain admin-only in the data.

## 2026-06 — Rebrand → "Pronounce This" + hero copy
- All UI/brand strings, index.html title/meta, magic-link email sender/subject/body, FastAPI title, Stripe product names, README, backend/.env SENDER_NAME → "Pronounce This". (Production: re-publish; existing Stripe products keep their old names unless renamed in Stripe dashboard.)
- PronouncePage hero: kicker "Pronounce This · The General American Accent Pronunciation Tool Specifically Designed For Actors"; H1 "Pronounce This."; sub "Type any word, name or location…". Scene block: H2 "Prepare for your next audition. Hear how to pronounce every word." + new paragraph (upload PDF, IPA, click to hear, laundry lists, download dialogue audio).

## 2026-06 — Trial 3 → 5 free words
- TRIAL_WORD_LIMIT=5 (auth.py); copy in LoginModal, WelcomeModal, PaywallModal; auth.jsx default 5. /api/auth/me returns trial_word_limit 5.

## 2026-06 — Redesign: Dark Cinematic Studio (A24 × Apple × Linear)
- design_guidelines.json rewritten by design agent. Implemented via Tailwind token remap (stage #0A0A0C, paper #121316, surface #1A1B20, elevated #252730, rule #2D303B, ink #F1F2F6 (text), muted2 #989DAE, rust→amber #E5A93C, crimson #E54D42, sage #38D39F) + index.css rewrite (CSS vars, dark shadcn HSL, spotlight radial + grain, amber btn-primary, pill nav, .glass-bar, .tally rec light, .reveal stagger). Fonts: Syne (display), American Typewriter → Courier Prime fallback (font-serif/body), JetBrains Mono (mono/IPA) via Google Fonts in index.html.
- Header: sticky glass bar, pill tab nav, pill Sign in. Hero: amber kicker, "Pronounce This." with amber period, staggered reveal, search box with white-ish border + amber focus glow. Scene block: H2 "Scene Preparation." (same size as H1), sub "Prepare for your next audition…" text-xl/2xl, paragraph, amber CTA.
- Modals overlay bg-stage/75; CaptionSearchModal player area bg-stage, highlight mark amber. Recording indicators use .tally (crimson) + crimson Stop button.
- Tested: iteration_22 frontend regression (all pass except CaptionSearchModal contrast — fixed).

## 2026-09 — Upload error triage
- User saw 'No spoken dialogue detected' on production. Preview upload of the same script works (Claude 200). Root cause (very likely): production still runs the OLD Anthropic key which expired 2026-09-15 → Claude returns 401 → regex fallback can't parse that PDF layout → 400. Fix = set new ANTHROPIC_API_KEY in production secrets + re-publish.
- Hardening: build_dialogue_only_scene now returns 503 'script reader temporarily unavailable' when the LLM failed AND regex found nothing, instead of blaming the PDF.

## 2026-09 — Sales readiness (code side) — approved by user
- Sales page lives in Kajabi: https://www.katherinebeck.com/pronounce-this (user builds). Checkout links for its buttons: GET /api/payments/checkout?plan=monthly and ?plan=annual (303 → Stripe Checkout, no login; rate-limited 20/h/IP; origin from APP_PUBLIC_URL).
- POST /api/payments/checkout no longer requires login (optional_login reuses Stripe customer when signed in). `_session_email` reads customer_details.email for guests; `_grant_from_session` creates the user + membership. `/payments/status` returns `email`.
- PaymentSuccessPage: if not logged in after payment → auto-requests a magic link to the checkout email, shows "Payment received. Check your inbox." + Resend (enabled after 60 s to respect the 1/min limiter).
- Plan-change fix: `_sub_lookup_key` uses subscription.items[0].price.lookup_key (metadata fallback); `_supersede_stripe_rows` keeps one active stripe:* membership per user (old row → cancelled/superseded). `sync_from_stripe_customer` counts past_due as active.
- Tests: backend/tests/test_sales_flow.py (5) + testing agent iteration_23 (10/10 backend, frontend success page). Real Stripe Checkout UI completion not automated — user to run one $9 test-mode purchase.
- Audit docs: /app/memory/SALES_READINESS_AUDIT.md. Remaining (user, Stripe Dashboard): save Customer Portal config (cancel at period end, switch monthly↔annual, card update, invoices), rename product to "Pronounce This", live prices with same lookup_keys, live webhook https://app.katherinebeck.com/api/stripe/webhook, live keys + STRIPE_MODE=live in production secrets; Kit: native Stripe→Kit integration + tags + welcome sequence.

## 2026-09 — Real Speakers channels + auto-hide, frequency-ordered dictionary, "Sound lists"
- caption_search.CURATED_HANDLES: +30 American channels (SAG-AFTRA Foundation, EW, People, E! News, Extra, MTV, Vulture, Jennifer Hudson, LIVE Kelly & Mark, Tamron Hall, Inside Edition, FOX 5 NY, Breakfast Club, Hot 97, Complex, REVOLT, Lex Fridman, Lewis Howes, The Moth, Pod Save America, Daily Stoic, MFM, Basement Yard, Casey Neistat, DeFranco, Ryan Trahan, Dude Perfect, Jubilee, Try Guys, Colin & Samir, Great Big Story). Skipped non-GA speakers (Diary of a CEO, Ali Abdaal, Peter McKinnon, Jay Shetty) and unresolvable handles (Sway, Marc Maron). 153 channels total; daily cron indexes new ones.
- Unplayable clips: CaptionSearchModal now uses the YouTube IFrame API (ClipPlayer.jsx); onError → POST /api/caption-search/unplayable {video_id, code} → hidden_videos (auto:true, reason player_error_N) + caption_transcript_cache.embeddable=false; modal drops the clip and moves on.
- My Dictionary queue order = wordfreq Zipf frequency desc (phonetics.cmu_words_by_frequency), rare/never-seen words alphabetical at the back; jump-to-word positions by rank. `wordfreq` added to requirements.
- UI copy: "Laundry lists" → "Sound lists" (panel title, hero/upload paragraphs, welcome modal). API route names unchanged.

## 2026-09 — ElevenLabs voices → Jessica Anne Bogart (lxYfHSkYm1EzQzGhdbfc) + Tim Hook (apOzcbHULxCnvWfHPd41)
- server.DEFAULT_VOICE_ID = Jessica for single words / untargeted lines (ELEVENLABS_VOICE_ID env no longer read; .env value updated for tidiness). READER_VOICES = jessica/tim (old adam key removed; SceneReader clears stale saved pref).
- audio_cache + turn_audio_cache entries now carry voice_id; entries from another voice are treated as misses and regenerate on first play (agreed cost). Manual recordings (manual_override) unaffected and always win.
- Verified: reader-voices lists Jessica/Tim; word 'beautiful' regenerated with Jessica then cached; turn TTS voice=tim OK, voice=adam → 400.

## 2026-09 — Header: Sign in + Get started
- Logged-out header shows outline "Sign in" (magic-link modal) + amber "Get started" pill → PaywallModal reason "join" ("Join Pronounce This" + Monthly/Annual cards → guest checkout). LoginModal has "Ready to join? See plans →". data-testids: header-signin, header-get-started, login-see-plans.

## 2026-09 — Male voice → David (Zv7P8CISODgj9wDHyyI9); pickers redesigned
- READER_VOICES: jessica (Female voice) / david (Male voice); labels are generic per user request. Old 'tim' key removed (SceneReader clears stale pref).
- SceneReader CharacterPicker/VoicePicker: prominent elevated cards with amber labels "Choose your character" / "Choose your scene partner's voice", display-font values, appearance-none selects. Voice select defaults to first voice (Female).

## 2026-09 — Mobile pass + long-script upload robustness
- Header: brand + AccountChip on row 1; TabNav hidden on mobile, full-width segmented tab bar below header (data-testid mobile-tab-bar). No more wrapped Sign in on the left.
- Modals (Login, Paywall, Welcome, CaptionSearch): bottom-sheet on phones (items-end), solid bg-stage/90 overlay without backdrop-filter on <sm (iOS Safari fixed+blur bug), blur on sm+; max-h-[92dvh] overflow-y-auto; Escape closes Login/Paywall.
- Upload 503 root cause (likely): Claude JSON output truncated at max_tokens=4096 on long scripts → parse fail → None → "script reader unavailable". Fix: max_tokens=16000 for dialogue extraction + _repair_truncated_json salvages complete items. Not mobile-specific; the same PDF failed regardless of device.

## TO-DO (user-requested reminders)
- **Reliability session** (after first ~20 paying members): background upload queue with progress + auto-retry; Admin "Scene uploads" health line (24h uploads / AI failures / salvage events); failure email to coach with PDF name; weekly Anthropic + ElevenLabs credit watchdog email.
- **Phase 2 Atlas migration**: NOT started; database still on Emergent-managed Mongo. Plan in /app/memory/ATLAS_MIGRATION_PLAN.md; verification script at backend/tools/verify_migration.py. Waiting on user to create cluster + provide DB_NAME + approve cutover.

## 2026-06 — Anthropic key rotation
- ANTHROPIC_API_KEY replaced in backend/.env (old key expires 2026-09-15). Only that line changed. Verified by testing agent (iteration_20: 6/6 pass) — api.anthropic.com 200, no Emergent fallback. User must re-publish for production.


## 2026-06 (June) — Onboarding & copy updates
- Get Started modal: header "Try it free" → email capture (magic link) → "Join Pronounce This" + monthly/annual plans (unchanged).
- Sign in modal: removed "New here?" cards (Try it free / Join $9).
- Anonymous visitors no longer get an auto-opened sign-in popup on load (App.js skips listScenes when unauthenticated).
- Scenes tab: "Pronounce This Scene" upload panel now always pinned at the top of the page, above the library + reader.
- Copy: "Upload a scene. Hear it pronounced in an American accent." (Word page).
- Production: user confirmed new ANTHROPIC_API_KEY works after redeploy. Design changes need a fresh Publish to go live.

## 2026-06 — Limits, Real Speakers inline, IPA syllables
- IPA now Cambridge-style: syllable dots (·), stress before syllable, ɝ (stressed) vs ɚ (unstressed). Existing scenes recompute on read.
- Scene uploads capped at 10 pages (MAX_SCENE_PAGES); scenes auto-expire after 90 days (TTL on expires_at_dt, backfilled).
- Real Speaker Examples now embedded inline under word results (no button/modal on Word page); scene promo hidden once a result shows.
- Admin-only "Not American · hide" button on clips (POST /admin/hidden-videos). /me now returns is_admin.
- Auto-hide of unplayable clips now needs 2 distinct reporters (unplayable_reports collection) — single browser glitches no longer hide clips globally.
- Caption ranking: news channels -2.0, scripted/late-night/explainer channels +1.5.
- Copy: eyebrow without "General"; "Hear it spoken in an American accent"; sidebar "Scenes are kept for 90 days".
- Pricing note: raise prices by editing setup_stripe.py amounts and re-running; existing subscribers stay grandfathered.

## 2026-06 — Heteronyms + Real Speakers index fix
- Heteronyms (produce/record/read/minute/-ate words…): /pronounce returns `variants` [{label, gloss, ipa, arpabet, categories}]; Word page shows two cards each with its own Hear button. /tts accepts `arpabet` for phoneme-exact audio (cache key word#PHONES). Table in phonetics.py (_STRESS_SHIFT_WORDS auto from CMU + _MANUAL_HETERONYMS).
- ROOT CAUSE of thin YouTube results: ingest job stuck with running=True since Sep 8 (426 videos/25 channels). Fixed: stale lock (no progress 30 min) is taken over; fresh process clears lock on boot; weekly refresh checked at startup. Index now growing across 146 channels.
- Admin: channel index section shows videos indexed, channels with videos / curated, this run, last full pass, stale warning + resume, per-channel breakdown. New Hidden clips section (paste URL to hide, restore).
- Known dev quirk: hot reload can hang while ingest threads (yt-dlp) are running → `sudo supervisorctl restart backend`.

## 2026-06 — Domain + context-aware heteronyms
- Production domain now https://pronouncethis.us (app.katherinebeck.com unlinked). Secrets APP_PUBLIC_URL / CORS_ORIGINS updated by user; Stripe webhook URL updated. Needs Republish for secrets to apply.
- Scenes: heteronyms resolved per sentence at upload (`_resolve_heteronyms_in_context`, Claude batch label + neighbour-word fallback). Token gets `variant_label`; `_refresh_categories` preserves it; WordBlock/LaundryList play with token arpabet.
- Link preview: index.html title/og/twitter = "Pronounce This - The American accent pronunciation tool".

## 2026-06 — Admin cleanup
- Removed "Prewarm popular words" section from Admin UI (channel index makes it redundant; backend endpoints left in place).
- Single "Hidden clips" section (HiddenVideos.jsx) placed under the channel index; duplicate removed.
- All users: Search button (email or plan title), 25 per page with Prev/Next; GET /admin/users?q=&page=&limit= returns total/page/limit.
- Dictionary builder IPA validator now accepts "·" and nasal tilde; palette has "·".

## 2026-06 — Reader track download
- Scenes: "Download My Reader's Lines" button → GET /scenes/{id}/download-lines?mode=reader: whole scene in order, partner lines audible, selected character's lines replaced by silence = 1.1× line duration (+0.4s beat between turns). Filename *_reader.mp3. Subscriber perk like the existing bundle.

## 2026-06 — Scene controls + login hardening
- Scene header controls: Choose your character · Choose my voice · Play My Lines · Download My Lines · Choose my reader's voice (defaults to the other voice) · Download My Reader's Lines. prefs.readerVoice persisted per scene.
- Download filenames: `{PDF name}_{CHARACTER}.mp3` and `{PDF name}_readers-lines.mp3`.
- Magic link verify: 120s grace window (re-issuing cookie if same token retried after a lost response); VerifyPage retries transient (network/5xx/429) errors 3× and shows friendly messages for used/expired links.
- Deployment agent static scan flagged the 90-day scenes TTL as "destructive" — it is an explicit user requirement; keep.

## 2026-06 — Dictionary → ElevenLabs voice
- Coach recordings are no longer played to members. Saving a dictionary entry converts its IPA → ARPABET (`phonetics.ipa_to_arpabet`), stores it in `pronunciation_prefs` (source="dictionary") + PREFERRED_ARPA, deletes generated audio; ElevenLabs then renders the word via phoneme tags (word lookups, scene word clicks, scene lines). Human take archived as audio_cache `{word}#human`.
- Startup migration converts any legacy manual_override recordings (dictionary or old "tricky words" uploader) the same way. Verified with seeded 'interior'.
- Admin: removed "Record your own for tricky words" section; My Dictionary's Jump box is the single place to fix a word. Copy updated.
- UploadDropzone scene-library copy updated per user.

## 2026-06 — Speech-to-speech re-voicing (user choice a)
- Dictionary save WITH a recording: take archived as `{word}#human`, then ElevenLabs speech-to-speech (`eleven_multilingual_sts_v2`, Jessica voice) → stored as audio_cache override `{word}` (source=speech_to_speech). Members hear her pronunciation in the app voice (Word page + scene word clicks). Scene *lines* still use IPA→ARPABET phoneme tags.
- Save WITHOUT recording: IPA-driven only (prefs). Startup task `_revoice_archived_takes` re-voices legacy #human takes lacking an override (non-fatal).
- GET /admin/dictionary/audio?word=&which=human|eleven. STS verified working on user's ElevenLabs plan (1.6s/word).

## 2026-06 — Admin: queue removed, custom words, pager; visitor gating
- Removed "Record the words students actually hear" (RecordingQueue) from Admin.
- My Dictionary: Jump box accepts words/names not in CMU (queue endpoint puts them first, `custom: True`); save allows recording-only (ipa Form default ""). Verified 'oner' → STS override, member tts manual_override=True.
- All users: numbered pager (1 … 4 [5] 6 … N with ‹ ›), "Displaying 1 - 25 of N accounts" always shown.
- Word page: unauthenticated Pronounce / Upload a scene open Get Started (paywall "join") modal.
- Scene header restored to original 4 controls + compact Reader Female|Male toggle attached to Download My Reader's Lines.
- audio.js: withRetry (3 tries) on transient 5xx/network for word + line TTS; friendly message instead of Cloudflare HTML.

## 2026-06 — Owner notifications
- notify.py: notify_owner(subject,title,lines) via Resend → ADMIN_NOTIFY_EMAIL (default info@katherinebeck.com). Hooks: first sign-in (auth verify, last_login_at was None) → "New free trial"; checkout.session.completed first grant → "New member"; subscription cancel scheduled (first time cancel_at seen) → "Cancellation"; subscription.deleted → "Subscription ended". Fire-and-forget.
- Scene controls redesigned into two panels: Step 1 · My lines (character, my voice, play, download) and Step 2 · Reader track (reader's voice, download).

## 2026-06 — Visitor gating v2, default tab, 520 mitigation
- App always opens on Word tab (no localStorage memory of tab).
- openPaywall("trial") → trial-only popup (email capture, no plans, footer pointing to Sign in / Get Started). Used by Pronounce, Upload a scene promo, Upload PDF, + New Scene for anonymous users. Header Get Started keeps full modal ("join").
- Real Speakers panel: 3× retry on 5xx/network, friendly error text (no Cloudflare HTML).
- server.py middleware sets `Connection: close` on every response to avoid LB↔uvicorn keep-alive races (suspected cause of intermittent Cloudflare 520s in production).
- Session: JWT cookie 90 days (JWT_DAYS=90), no re-login needed on same browser.
- Testing: /app/test_reports/iteration_24.json — all pass.
- PENDING user input: ConvertKit integration (needs API key + form/tag IDs for trial + member).

## 2026-06 — Kit (ConvertKit) tagging
- `backend/kit.py`: Kit v4 API (`X-Kit-Api-Key`, api.kit.com/v4). `tag_subscriber(email, tag)` fire-and-forget: create-or-get tag by name (cached) → upsert subscriber → tag by email; 3× backoff on 429/5xx. Blank `KIT_API_KEY` = disabled, never blocks a request.
- Tags: "PT Trial" (first sign-in, auth.py), "PT Member" (first Stripe grant), "PT Cancelled" (cancel scheduled + subscription.deleted) — same hooks as notify_owner.
- `KIT_API_KEY=""` added to backend/.env + README env table. USER: paste the v4 key (Kit → Settings → Developer → V4 Keys) into the Secrets panel, then Republish.
- Tests: backend/tests/test_kit.py (3 pass, mocked HTTP). Live Kit call not verified until the key is set.

## 2026-06 — Free-trial anti-abuse (option a: alias collapse + disposable block + per-device)
- `auth.canonical_email`: strips `+tag` on all domains; Gmail/googlemail also drop dots → one inbox = one account. Users get `email_key` (startup `backfill_email_keys`). `resolve_account_email` prefers legacy exact email, then alias match, else canonical — existing accounts keep their data. Magic link is *delivered* to the address as typed; account keyed on canonical. Stripe `_grant_from_session` resolves the same way.
- `backend/data/disposable_email_blocklist.conf` (8.9k domains, repo-stored, from disposable-email-domains project). request-magic-link → 400 `disposable_email`; LoginModal + TrialSignupForm show friendly copy. Paid checkout not blocked.
- Per-device: httpOnly cookie `pt_device` (400 days) set by `/auth/me` and request-magic-link. `trial_devices` {device_id, trial_word_used, trial_scene_used, emails[]}. `require_access` uses max(account, device) usage; `consume_trial` increments both; `/me` reports the effective counters. No cookie → per-email only.
- Not built (user chose a): per-IP cap, Admin "trial abuse" view. Tests: tests/test_trial_abuse.py (7) + e2e (/tmp/e2e_trial.py: alias→same account, 5 words then 402, second email same device 402).

## 2026-06 — Get Started modal copy + plan-card fallback
- Headlines: Get Started (join) → "Ready to join Pronounce This?"; trial-only popup → "New here? Try it for free".
- Plan cards ($9/mo, $90/yr) now render from a static FALLBACK_PRICES list when `/me` hasn't loaded or failed (user saw them missing in production — likely a 520 on /me). Verified via screenshot.

## 2026-06 — Magic link "already used" fix
- Root cause (production report, iPhone Mail): mail apps / link scanners open the verify URL before the person taps it; the old single-use rule (120s grace) then rejected the human click.
- Fix: a link stays valid for its full 15-min TTL, capped at MAGIC_LINK_MAX_USES=5 opens (`use_count`, `consumed_at`=first, `last_used_at`). Error detail is now `{code, email}` so VerifyPage prefills a one-tap "Send me a fresh link" form (data-testid verify-resend-*). test_subscription_auth updated; verified live (5×200, 6th 400, expired 400) + screenshot.

## 2026-06 — Landing / sales page at "/" + app moved to "/app"
- `components/landing/LandingPage.jsx` + `landing.css` port the coach's HTML 1:1 (copy, colors, layout; 3 screenshots in `public/landing/`). Fonts switched to the app's set per user: Syne (display, amber period on hero), Courier Prime (body), JetBrains Mono (labels). Fraunces/Inter removed from index.html.
- Routing (App.js): `/` → HomeGate: signed-out → LandingPage, signed-in → replaceState `/app` + App. `/app` → App. VerifyPage / PaymentSuccess / PaymentCancel / Admin "back" links now go to `/app`. Stripe success/cancel URLs unchanged (/payment/*).
- Landing CTAs ("Try Pronounce This.") → openPaywall("trial"); "Already a member? Sign in" (.link-quiet) → LoginModal.
- PaywallModal: reason "join" = title "Join Pronounce This" + subhead + plan cards + Stripe footer (no trial form). Trial-only popup title "New here? Try it for free". Both show spam/junk-folder note (paywall-spam-note). Header button renamed "Join Pronounce This" (testid header-get-started unchanged).
- Tested: iteration_25 (backend 5/5, all frontend flows pass). Production: Republish required; if the host needs SPA fallback config for `/app`, it already works for `/admin` so no change expected.

## 2026-06 — Landing polish round 2
- "Already a member? Sign in" moved to top-right of hero (.top-bar). Struggle h2 → "You've got the audition. Your accent isn't there yet." (one line on desktop), section heads full width (Ways to use… one line), subhead max 72ch (2 lines).
- Testimonial back to Fraunces italic (Fraunces ital 500 re-added to index.html). Closing CTA redesigned: dark ink panel (no border), one-line "Get ready for your next role." with amber period; footer sits on the same dark panel.
- Trial popup footer links are live: "Sign in" → LoginModal, "Join Pronounce This" → join popup with plans (testids paywall-trial-signin / paywall-trial-join). Verified via screenshot.

## 2026-06 — Scene controls cleanup
- Panels stacked vertically, width = script column (max-w-[78ch]). Labels: "My Lines" / "Reader's Lines" (no Step numbers).
- New "Play My Reader's Lines" (btn-primary, testid play-reader-lines-button): plays the other characters' turns in order in the reader voice, pausing ~0.42s/word ×1.1 + 0.4s where my lines fall; Stop toggles. Download buttons disabled while either playback runs.

## 2026-06 — Audio reliability + trial rules (distinct words)
- "Audio server hiccupped" root cause: transient 5xx/520 (platform edge or ElevenLabs) with only 3 quick retries. Fixes: ElevenLabs SDK `request_options={"max_retries":3,"timeout_in_seconds":60}` on word + line synthesis; frontend `withRetry` 4 tries, 1s/2s/3s backoff, also retries 429; copy "Our audio server is busy right now…".
- "Request failed 520 — reader's lines" root cause: download-lines synthesized every line sequentially inside ONE request (>60–100s on long scenes → proxy timeout). Fixes: frontend pre-warms each turn via /turn TTS (3 parallel, button shows "Preparing n/N"), then the bundle call only stitches cached audio; backend synthesizes uncached turns 4-at-a-time (asyncio.Semaphore).
- Trial rules (user spec): words and scenes are independent counters; a word counts ONCE whether searched (/pronounce) or heard (/tts) — `trial_words` set on user + device (`trial_word_key`), legacy counters honoured via max(). /pronounce now requires login and is trial-gated. 6th distinct word → 402 on search and hear; already-counted words remain free. After 5 words the scene upload still works (and vice-versa).
- Exhausted popups now use the Join layout: title "Join Pronounce This", subhead prefixed "You've used your 5 free words." / "You've used your free scene upload.", plan cards. Fixed React crash (402 detail object rendered in toast) in PronouncePage, ScenesSidebar, UploadDropzone — 401/402 are silent (modals handle them).
- Magic link: MAGIC_LINK_MAX_USES 5 → 10; VerifyPage guards StrictMode double-invoke (useRef).
- Verified: /tmp/e2e_trial_rules.py (searches counted, 6th blocked on both endpoints, re-hear allowed), screenshot of Join popup on 6th word, reader download with "Preparing 1/2" progress.

## 2026-06 — ElevenLabs cost controls + credit watchdog
- Reader track no longer synthesizes the user's own lines; silence = words × 420 ms × 1.1 (MS_PER_SPOKEN_WORD). Frontend pre-warm skips my lines too. ~40% cheaper reader downloads.
- TRIAL_MAX_SCENE_PAGES = 2 for non-subscribers (members keep 10); 400 message explains the limit; a rejected upload does not consume the scene trial.
- `backend/watchdog.py`: every 6h reads ElevenLabs subscription (user.subscription.get); emails owner at ≥80% once per billing cycle, weekly summary every Monday, one-time email if the key lacks permission. State in `system_state` {key: elevenlabs_watchdog}. GET /api/admin/credits → Admin "Audio budget" card (CreditMeter.jsx).
- BLOCKER for the watchdog: current ELEVENLABS_API_KEY lacks the "User → Read" permission (401 missing_permissions user_read). User must edit the key in ElevenLabs → API Keys (or create a new key with TTS + Speech-to-Speech + User read) and update the secret.
- Verified: 3-page PDF as trial → 400 with trial copy; reader download still works; Admin card renders (shows permission message until key is fixed).

## 2026-06 — Supabase Auth (email/password) — Option A, COMPLETE (preview verified; production needs republish + SUPABASE_SERVICE_ROLE_KEY)
- Decision: Supabase Auth for identity/passwords/sessions only; MongoDB stays the data store keyed by email; ownership checks stay in FastAPI (no RLS possible — data isn't in Supabase). Audit delivered to user (no Supabase existed before; magic-link JWT cookie was the auth).
- Backend: `supabase_auth.py` — verify_access_token (ES256 via JWKS at $SUPABASE_URL/auth/v1/.well-known/jwks.json; HS256 only if SUPABASE_JWT_SECRET set), resolve_user_email (sub → users.supabase_sub, else alias-collapsed email link, else create trial shell; first login fires notify/Kit), admin_create_user + link_existing_users (startup, needs SUPABASE_SERVICE_ROLE_KEY), send_password_reset. `auth.caller_email()` is now the single identity resolver: Bearer Supabase token first, legacy cookie fallback (admin-issued links still work). Unique sparse index users.supabase_sub.
- Env: backend SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY (blank, user to add), SUPABASE_JWT_SECRET (blank, unused with ES256). Frontend REACT_APP_SUPABASE_URL, REACT_APP_SUPABASE_ANON_KEY. `@supabase/supabase-js@2.49.4` (pinned: newer needs Node 22).
- Frontend: lib/supabase.js (client + passwordProblem: 8+ chars, letter+number); api.js request interceptor adds Bearer; auth.jsx listens onAuthStateChange (PASSWORD_RECOVERY → /auth/reset), logout = supabase.signOut + cookie clear. AuthForm.jsx (signin/signup/forgot), LoginModal rewritten, TrialSignupForm = signup form, ResetPasswordPage at /auth/reset (also "Change password" in account menu), PaymentSuccessPage guest flow → create password with checkout email. VerifyPage kept for legacy admin links (resend form removed). Magic-link endpoints still exist server-side (admin "Copy magic link" works) but no public UI.
- BLOCKED on user's Supabase dashboard: (1) Confirm email is ON (signup returns over_email_send_rate_limit) → turn OFF; (2) Resend SMTP not configured; (3) Redirect URLs; (4) service-role key. Supabase also rejects test domains (email_address_invalid) → e2e must use real-domain emails.
- Test script: backend/tools/e2e_supabase.py (signup, /me via token, wrong password, 5-word limit per user, A≠B scene isolation, tampered token, legacy link keeps membership, reset request, logout). NOT yet passing due to blockers above. Frontend flows untested.
- Migration plan for existing users: startup pre-creates confirmed Supabase users (no password) once service key is set → they use "Forgot password?" to set one; data stays keyed by email, supabase_sub stamped on first login. No deletions.
- 2026-06 update: Supabase dashboard configured by user (Confirm email OFF, redirect URLs, Resend SMTP login@katherinebeck.com, rate limit). Backend e2e tools/e2e_supabase.py ALL OK. Frontend testing_agent iteration_26 all flows pass; fixed logout race (refresh seq guard + optimistic setMe in doLogout). Supabase rejects fake-domain emails → QA uses gmail.com addresses; QA Supabase users (ptqa*@gmail.com) remain in Supabase Auth — delete in dashboard.
- Remaining for user: Republish → paste SUPABASE_SERVICE_ROLE_KEY in Secrets → redeploy (enables pre-creation of legacy members so "Forgot password?" works for them). Legacy sessions (cookie) keep working until they expire.
- NOTE: editing files under /app/backend (incl. tools/) triggers uvicorn reload which can wedge → `sudo supervisorctl restart backend`.

## 2026-06 — Batch: reader copy, Kit plan tags, light popups/Admin, dictionary lists
- SceneReader: removed "Play My Reader's Lines" (download kept); Reader's Lines copy → "Download the other character's lines to use as practice as you rehearse speaking your lines."
- Kit: tags now PT Trial / PT Monthly / PT Annual / PT Cancelled (`kit.member_tag(lookup_key)`; "year"/"annual" in lookup key → Annual). Fires on first login (supabase_auth.resolve_user_email + legacy auth.verify), first Stripe grant, cancel scheduled, subscription deleted. KIT_API_KEY must be set in production Secrets — preview blank (disabled).
- Light theme: `.theme-light` CSS scope (index.css) applied to LoginModal, PaywallModal panel, AdminPage root (data-testid admin-page). Main app stays dark.
- Trial popup: subline "Get 5 free words + 1 free scene…" directly under title; spam note removed there (kept on join/login). Sign-in modal: "New here? Create account" link removed. Sign-up auto-signs-in (confirm email OFF).
- Dictionary builder: list tabs (Dictionary / First names 1000 / Surnames 250 / US places 50 states+300 cities / Countries+capitals / Brands & chains 78) from backend/data/wordlists/*.txt via `curated_list()`; each tab has its own search + cursor. Multi-word labels split into tokens (hyphens kept: chickfila) with "from “Los Angeles, California”" label. `GET /admin/dictionary/queue?list=&include_start=`; `POST /admin/dictionary/undo` restores snapshot (entry, pronunciation_prefs, audio_cache docs) taken before every save/skip (`dictionary_history`, last 30). UI: Hear it (current app TTS), Back to previous word (client history), Undo last change.
- Verified via screenshots + curl (lists, include_start, save→undo restores). 

## 2026-06 — Support modal, Kit checker, reset page light
- "Contact support" now opens SupportModal.jsx (portal, light theme): email info@katherinebeck.com + Copy + mailto (subject "Pronounce This support"). Old mailto-only link "did nothing" without a mail client.
- /auth/reset (Choose a new password) + VerifyPage use .theme-light.
- Admin: KitStatus card — GET /api/admin/kit/status (enabled, key prefix, looks_v4) + POST /api/admin/kit/test {email} runs kit.tag_subscriber_now(PT Trial) and surfaces Kit's exact error. Deployment agent static "blockers" (TTL indexes, CORS) are intentional/false positives — production CORS_ORIGINS is set in Secrets.

## 2026-06 — LIGHT THEME (whole app)
- User chose light mode app-wide. Implemented at the Tailwind level: tailwind.config.js palette flipped (stage #F4F1EA, paper #FAF8F3, surface #FFF, elevated #EFECE4, ink #17140F, muted2 #5D5648, rule #DDDAD2, rust #B3761F, rustDeep #E5A93C, crimson #B8382E, sage #1F8F68) so all variants (hover:, /opacity) follow. index.css "Light theme" block: CSS vars, glass-bar, btn-primary dark text, inverted .bg-ink pills keep white text, modal backdrops dim, placeholder #6b6659. `.theme-light` class no longer needed (harmless).
- Testing agent iteration_27 found contrast defects (account chip open, btn-primary cream-on-amber, Join button white-on-amber, plan card subtext) — all fixed by the palette flip; verified via screenshots.
- Landing images regenerated for light mode: public/landing/word-tool.jpg + scene-tool.jpg are real screenshots; hero-devices.jpg is an AI composite (laptop = Scene page, phone = Word page) — small on-screen text is approximate; user may supply a real mockup. Old dark hero kept as hero-devices-dark.jpg.
- Join popup copy updated (no more "no password, ever").
- TODO if user reports any remaining dark/unreadable spots: grep for hardcoded hex or `text-stage`/`text-surface` usages.

## Added (Sep 23, 2026 — Alias-conflict login fix + light landing images)
- **Bug**: a valid Supabase login whose inbox (alias-collapsed, e.g. `name+tag@gmail.com` ↔ `name@gmail.com`) resolved to a Mongo account already linked to a *different* Supabase identity was silently treated as a visitor → trial popup after sign-in (reported by Katherine with gabkatbeck@gmail.com on pronouncethis.us).
- **Fix**: `supabase_auth.IdentityConflict` → `caller_email` stamps `request.state.auth_error="inbox_already_linked"` → `/api/auth/me` returns `auth_error`. Frontend `AuthForm` awaits `refresh()` after sign-in/sign-up and shows an inline error; `AuthProvider.refresh` signs out of Supabase and toasts when a stale conflicting session is found. Account-takeover guard is intentionally kept (no auto-relink).
- **Admin**: `POST /api/admin/users/unlink-login {email}` ($unset supabase_sub) + Unlink icon in Admin → Users (shown for rows with a linked login). Delete-user also clears a conflict.
- Landing page: hero (`/landing/hero-devices.png`, transparent, trimmed), `word-tool.jpg`, `scene-tool.jpg` replaced with the user's own light-theme images (cache-busted `?v=light`).

## Added (Sep 23, 2026 — Real Speakers profanity screen)
- **Revised same day (user):** swearing must stay (actors need it) — filter is now **slurs only**; `CACHE_VERSION` restored to 2 and slur videos are excluded via `hidden_video_ids()` so cached results are reused (the v3 bump had made every word re-search YouTube = sluggish).
- `backend/profanity.py` (original two-tier design, superseded): **Slurs** (n-word etc.) anywhere in a transcript → whole video excluded (`has_slur=True` on `caption_transcript_cache`). **Profanity** (f/s-words, etc.) and YouTube's `[ __ ]` bleep marker → only the ±20 s clip window is checked; `_find_word_in_transcript` picks the best *clean* occurrence or skips the video.
- Applied in both search paths (local Mongo index + live YouTube scan); `CACHE_VERSION` bumped to 3 so stale cached query results are re-filtered. Startup background `backfill_slur_flags()` stamped all 6,553 cached transcripts (4 flagged). Surnames "Coons"/"Dyke" deliberately excluded from the slur list (false positives on news channels).
- Hard-coded list per user choice; Admin "hide video" remains the backstop. Tests: `backend/tests/test_profanity.py` (5 passing).
- Dev note: uvicorn hot-reload sometimes hangs after edits (startup ingest task) — `sudo supervisorctl restart backend` fixes it.

## Backlog — saved by user (Sep 23, 2026) "save these ideas for later"
- **Report This Clip** (P1): student flags a Real Speakers clip as inappropriate from the player → appears in Admin with one-tap Hide.
- **Blocked Words Editor** (P2): editable slur/profanity lists in Admin (currently hard-coded in `backend/profanity.py`).
- **Merge Alias Accounts** (P2): Admin merges a `+tag`/dotted alias account into the main one, carrying over trial counts and scenes.
- **Linked Login Column** (P2): Admin → Users shows whether each account has a Supabase password login yet.
- **Trial Abuse View** (P2): Admin view of devices that created several trial accounts.
- **Playback Speed** (P2): 0.5× / 0.75× / 1× controls for words and scene lines.
- Still queued from earlier: MongoDB Atlas migration (on request), Upload queue with retry (after first 20 paying members), PWA, split `server.py` into routers.

## Added (Sep 23, 2026 — Report clip · Blocked words · Trial abuse · YouTube backoff) — iteration_28 all pass
- **Report This Clip**: `POST /api/caption-search/report {video_id, reason, query}` (login + rate limit 20/h) → `clip_reports` (status open, reporters[], reasons[]), owner emailed via `notify_owner`. Player footer "Report clip" → 4 reason buttons (Offensive language / Not an American speaker / Wrong word or timing / Other), clip skipped locally. Admin: `GET /admin/clip-reports`, `POST /admin/clip-reports/resolve {video_id, action: hide|dismiss}`; `ClipReports.jsx` section.
- **Blocked Words Editor**: slur list stored in `settings{key:"blocked_words"}` (seeded from `profanity.DEFAULT_WORDS`, loaded at startup). `GET/POST /admin/blocked-words` — POST replaces the list and runs `rescan_slur_flags()` over all transcripts (sync, ~seconds). `BlockedWords.jsx` chips + add + reset.
- **Trial Abuse View**: `GET /admin/trial-devices` (devices with ≥2 emails or blocked), `POST /admin/trial-devices/block {device_id, blocked}` → sets `trial_devices.blocked` and `users.trial_blocked` on its emails (admin email excluded). `require_access` returns 402 trial_exhausted for blocked user/device; subscribers unaffected. `TrialDevices.jsx` table with Block/Unblock.
- **YouTube rate-limit rectification**: `caption_search.RateLimited` + 30-min circuit breaker (`_yt_backoff_until`) tripped on 429/403/"sign in to confirm"; yt-dlp errors captured via quiet logger (no more ERROR spam); "no captions" cached 7 days (was 1 h); rate-limited misses expire with the backoff; ingest sleeps 3–5 s with jitter, stops the pass when throttled and does NOT stamp last_full_finished_at (retries next day). Optional `YTDLP_PROXY` env (yt-dlp `proxy`) for a residential proxy later.
- Admin page section order: ClipReports, BlockedWords, HiddenVideos, TrialDevices, then Users.
- Backlog notes from testing agent (non-blocking): blocked-words rescan is synchronous; startup ingest runs on every restart (dev annoyance).

## Changed (Sep 25, 2026 — scene-line voice stability)
- User reported ElevenLabs glitch: "a difficult couple of years" rendered as "couple you've years" (word echo). Root cause: random model glitch, not text. Per user: no re-record button / no STT self-check — **only** steadier voice settings for scene lines.
- `_synthesize` (scene lines only; word TTS untouched) now passes `VoiceSettings(stability=0.65, similarity_boost=0.8, style=0.0, use_speaker_boost=True)`. Verified regenerated line reads "of" correctly with natural, expressive delivery.
- Note: already-generated lines are cached (`turn_audio_cache`); the Wayward Mr Turner line will re-render with the new settings only if the cache entry is cleared or the scene re-uploaded.
- **Reverted (Sep 25)**: user disliked the changed delivery and the glitch recurred on prod (which was still running old code anyway). `_synthesize` back to default voice settings. Experiment: the isolated sentence rendered 4/4 correctly with defaults → glitch likely depends on the exact turn text as parsed from the PDF. Awaiting the PDF to reproduce with the real turn text.
- Sep 25 repro attempt with the real PDF: parser yields Leila's turn exactly as "Look, the whole faculty knows that you've had a difficult couple of years." Rendered 16× (Jessica ×10, David ×6) with default settings in preview → 16/16 correct. Could not reproduce; prod may be on older code (not republished) or unlucky. Advised: Republish, delete + re-upload, retest. If it recurs → only reliable fix is the STT line self-check (backlog).

## Added (Sep 25, 2026 — Scene-line self-check, "listen back and re-do bad takes")
- `backend/line_check.py`: after ElevenLabs renders a scene line, transcribe it back with **OpenAI whisper-1** (emergentintegrations `OpenAISpeechToText`, `EMERGENT_LLM_KEY`) and compare word-by-word with the script (`mismatches()`); bad takes are re-rendered (max 3 renders). Voice settings unchanged → delivery identical. If STT is unavailable/missing key → first take is used (never blocks playback).
- Forgiveness rules (to avoid wasted re-renders): punctuation, contractions (you've/you have…), numbers, parentheticals, filler noise, homophones via CMU phones (Abbie/Abby, counsellor/counselor), name spelling drift by consonant skeleton (Leila/Layla), compound splits (openminded/open-minded), dropped contracted auxiliaries (we'd→we). Identical mismatch on two consecutive takes = STT bias → stop retrying. Caught: swapped words ("couple you've years" → replace of→you have), dropped words, wrong names (Turner/Werner), of/off, dropped "not".
- Wired into both `POST /scenes/{id}/turns/{i}/tts` and `GET /scenes/{id}/download-lines` via `_synth_line` (global `asyncio.Semaphore(3)` — ElevenLabs plan allows 3 concurrent requests; retries on `concurrent_limit_exceeded`). `turn_audio_cache.check` stores {renders, verified, heard, gave_up?, stt_bias?}.
- Measured on the Wayward Mr Turner PDF: 10-line reader track incl. verification 14 s; simulated glitch caught and re-rendered on take 2; ~+2–3 s per first play of a line. Tests: `tests/test_line_check.py` (7). **Prod needs `EMERGENT_LLM_KEY` in deployment secrets** (present in preview .env).

## Added (Sep 27, 2026 — Member onboarding: set-password links, welcome emails, Google button)
- Diagnosis: Resend logs show reset emails to ddramaq23@gmail.com were **delivered** 3× → Gmail Promotions/Updates tab, not a sending failure.
- `backend/password_links.py`: `make_link()` = `supabase_auth.ensure_identity()` (Admin create-if-missing) + `generate_set_password_link()` (Admin `generate_link type=recovery`, redirect `{base}/auth/reset`). `send_link_email(kind welcome|reset|no_account)` via Resend with a plain personal template (from "Pronounce This" per user choice), logged in `auth_emails`; `delivery_status()` refreshes from Resend (`Emails.get` → last_event). `welcome_if_new()` fires on Kajabi activation + admin grant for users with `last_login_at None` (base = APP_PUBLIC_URL for webhooks → **prod secret must be https://pronouncethis.us**).
- Public: `POST /api/auth/password-link {email}` (4/h/email, 20/h/IP; unknown emails get a friendly "no account" note), `GET /api/auth/password-link/status?email=`. Admin: `POST /admin/password-link` (copy link), `POST /admin/password-link/send` (welcome email). Legacy `/admin/magic-link` still exists but the Admin button now uses the Supabase link.
- Frontend: `ResetSentStatus.jsx` (live Sent→Delivered/Bounced status, Gmail tab tip, "Send it again"), `GoogleButton.jsx` (shown only when `/auth/v1/settings.external.google` is true; `signInWithOAuth` → `/app`), AuthForm forgot mode now uses our API; Admin → Users: "Password link" + "Email link" buttons.
- Tested in preview: forgot flow with `delivered@resend.dev` → Sent → Delivered ✓, resend works; Google button hidden while provider off. **NOT tested in preview: link generation** (no SUPABASE_SERVICE_ROLE_KEY in preview .env — user hasn't supplied it); returns 503 `email_unavailable` / admin 503 until the key is present. Works in prod where the key is set (same code path as startup `link_existing_users`).
- **Sep 27 (later)**: user supplied the service role key → preview `.env` now has `SUPABASE_SERVICE_ROLE_KEY`. Verified end-to-end in preview: admin `POST /admin/password-link` → real recovery link → `/auth/reset` → set password → lands in `/app`; create-if-missing identity for a brand-new email works; public forgot → email sent (bounced for the fake QA gmail → UI shows "Bounced"). Note: Supabase replaces `redirect_to` with the Site URL when the origin isn't allow-listed; the global `PASSWORD_RECOVERY → /auth/reset` redirect in `AuthProvider` makes the flow work regardless. Recommend allow-listing `https://pronouncethis.us/**` (with `**`). QA password is now `Passw0rd!lc10`.

## Added (Sep 27, 2026 — First-name greeting · Login health column · Onboarding nudge)
- `users.first_name`: set from Kajabi customer `first_name`/`name` (webhook) or the new "First name" field on Admin → Grant access (`GrantBody.first_name`). Welcome/reset/nudge emails greet "Hi Antonia," (fallback "Hi there,").
- Login health: `/admin/users` returns `last_auth_email {kind,status,sent_at}`; `LoginHealth.jsx` cell shows Password set · date / Signed in (legacy link) / Never signed in + last link email status (welcome/reminder/reset delivered|sent|bounced + date).
- Onboarding nudge: `password_links.run_onboarding_nudges()` — users with `welcome_sent_at` ≥3 days ago, `last_login_at None`, no `nudge_sent_at`, not trial_blocked → one "Your Pronounce This access is waiting" email with a fresh link (max 50/run). Cron endpoint `POST /api/cron/onboarding-nudge` (Bearer `WEBHOOK_CRON_SECRET` in backend/.env, constant-time compare, idempotent via `cron_runs.run_id`, BackgroundTasks). `.emergent/crons.yml`: daily 09:00 Australia/Sydney. **Prod needs `WEBHOOK_CRON_SECRET` in deployment secrets.**
- Verified: grant with name → welcome "Hi Antonia," with link; backdated → nudge sent, `nudge_sent_at` stamped; cron auth 401/duplicate handling; admin column renders.

## Added (Sep 27, 2026 — Kajabi connection panel + reconcile fix)
- **Bug fixed**: daily Kajabi reconciliation cancelled *any* active membership not present in Kajabi's purchases list — including Admin manual grants. Now skips `offer_id == manual_grant` / `last_event == admin_grant`.
- `GET /admin/kajabi/status` + `KajabiStatus.jsx` (bottom of Admin): last webhook event + time, total events, API creds present, offers seen with member/active counts. Webhook URL hint shown. Lets the user verify her free coaching offer is wired.
- Supabase link expiry is a dashboard setting: Authentication → Sign In / Providers → Email → "Email OTP Expiration" (default 3600; user wants 14400). Note one live link per user (a new link invalidates the previous).
- Sep 27: user prefers Admin-grant onboarding over Kajabi. Welcome/nudge emails rewritten as step-by-step instructions (button, sign-in URL from request origin/APP_PUBLIC_URL, Google hint, expired-link fallback). Admin Grant accepts multiple emails (comma/space/newline) → one grant call each → welcome emails. Verified email content via Resend.
- Sep 27: welcome email opening line per user: "Welcome to Pronounce This. You just need to choose a password once, and you're in." + steps. New `POST /admin/password-link/send-all-new` (+ Admin button under Grant): welcome email to every active member with `last_login_at None` and no `welcome_sent_at` (max 200) — for onboarding existing coaching students without deleting/re-granting.
- Deliverability audit (Sep 27): Resend domain katherinebeck.com verified (DKIM ✓, SPF on `send.` ✓, click/open tracking off ✓). **Missing DMARC** record at `_dmarc.katherinebeck.com` — user advised to add `v=DMARC1; p=none; rua=mailto:...`. Welcome subject changed to drop the word "free" ("Your Pronounce This access — set your password").
- Stripe webhook 404 (Sep 28): Stripe dashboard points at `/api/payments/webhook`, app route was `/api/stripe/webhook`. Added alias route `/payments/webhook`; user also advised to correct the URL in Stripe. Founding-member pricing switch (20 × $9/$90 → $19/$190) discussed; awaiting user's choice on auto-cap implementation.
- Founding pricing decision (Sep 28): NO automation — user will tell agent when to switch $9/$90 → $19/$190 (Stripe: create new prices or transfer lookup keys; app: update amounts in auth.py `stripe_prices` + PaywallModal fallback). Added `GET /admin/paid-count` (active `stripe:*` memberships) and a private "Founding members · paid N / 20" tally in the Admin header.

## 2026-06 — Landing page redesign v3 (Claude design handoff)
- `landing.css` rewritten to the coach's new `index.html`: fonts Fraunces (headlines) / Inter (body) / Courier Prime (labels) — landing only, app keeps Syne/Courier Prime; amber #e0a53f→#c98a26 gradient CTA with shadow, radius 4px; closing section + footer now light (paper-2 / paper) instead of dark ink panel; struggle section uses border-top layout, italic Fraunces `.callout-line` with amber bar; crossed-out items in Fraunces red strikethrough.
- Copy: breakdown list reordered (self-tape first, "needs to run lines or needs 'a reader'"), 3 struggle statements, "This is the first web app specifically designed for non-U.S. actors…", last scene bullet. Removed labels "Casting Breakdown — Seeking" and "Int. Your Next U.S. Audition".
- Kept per user: "Already a member? Sign in" top-right of hero, amber period on hero + closing headline, all 3 existing images, CTAs → trial popup. index.html Google Fonts: Fraunces weights 400–700 + italic, Inter 400–700 added.
- Verified via screenshots (desktop, mobile 390px, CTA popup). Production: Republish needed.
- Follow-up (same day): popups (Login, Paywall, Welcome, Support, Real Speakers) get `.popup-fonts` (index.css) → Fraunces headings / Inter body+inputs / Courier Prime labels & buttons. Readability bump: inputs 14→16px (also stops iOS auto-zoom), submit `.btn-primary.btn-lg` 13px, Google button 13px, mono labels 10→12px, blurbs 14→16px, footer links 12→14px. `body:has(.landing)::before{display:none}` removes the app's amber spotlight/grain bleeding onto the white landing. Verified desktop + 390px mobile (bottom-sheet modals, no horizontal overflow).

## 2026-06 — Admin sidebar layout
- `AdminNav.jsx` (ADMIN_TABS grouped: Members → All users / Grant access / Stripe sync / Kajabi / Trial abuse; Real Speakers → Clip reports / Blocked words / Hidden clips / Channel index; Pronunciation → My Dictionary / Pronunciations; System → Audio budget / Kit (email) / Export data). Dark ink sidebar (md:w-64, sticky) with amber active bar; on <900px it becomes a horizontal scrollable tab strip. Styles `.admin-nav*` in index.css.
- AdminPage renders only the selected section in `<main data-testid="admin-content">`; tab persisted in URL hash (`/admin#grant`), default `users`; header title shows the tab label (`admin-title`). Payment-health banner always shows above content + red dot on "All users" nav item. Delete dialog stays global. testids `admin-nav-{key}`.

## TO-DO (user reminder) — Google sign-in branding ("continue to alsbjfsoqtyiglqtlhdg.supabase.co")
- User asked to be reminded later. Steps (user-side): (1) Google Cloud → OAuth consent screen → Branding: app name "Pronounce This", logo, support email, home page https://pronouncethis.us, privacy + terms links → Publish → Submit for verification. (2) Supabase → Project Settings → Custom Domains (paid add-on, Pro plan): auth.pronouncethis.us, add CNAME/TXT, activate; Google Cloud: add pronouncethis.us to Authorized domains, redirect URI https://auth.pronouncethis.us/auth/v1/callback.
- Agent-side once domain is ACTIVE (not before — breaks login): set REACT_APP_SUPABASE_URL (frontend) + SUPABASE_URL (backend) to https://auth.pronouncethis.us in Secrets, Republish. No code changes needed.
- AccountChip: "Coaching library" (KAJABI_MEMBER_PORTAL_URL) now shows only for active members WITHOUT a Stripe customer (admin/Kajabi group-coaching grants). Free trial + Stripe monthly/annual never see it (Stripe members see "Manage subscription"). Verified with QA trial account.
- AccountChip: free-trial users get a highlighted "Join Pronounce This →" row (testid account-join) under Status → opens the Join popup (monthly/annual). Copy: SupportModal "Email us directly and we'll get back to you."; AuthForm 503 error "…or contact support." Verified via screenshots.

## 2026-06 — Wayward "couple of years" recurrence (prod) + Kit visibility
- Reproduced the glitch deliberately in preview: Whisper hears "couple-you've years" → mismatch detected, so the listen-back check CAN catch it. Gap fixed: `render_verified` previously treated any identical mismatch twice as "STT bias" and served the take; now `looks_like_stt_bias()` only short-circuits when every disputed script word is a proper noun (names). MAX_RENDERS → 2 (user: "drop to 2" to save credits). Report gains `stt_unavailable`.
- Admin → Audio budget now has `LineCheckHealth.jsx` (GET /admin/line-checks: 7-day totals verified/retried/gave_up/unchecked + stt_key_present + last 10 gave-up lines) so user can see if the check runs in PRODUCTION (needs EMERGENT_LLM_KEY in Secrets + Republish since Sep 25 code).
- Kit: `kit.list_tags()` + `kit.account_info()`; GET /admin/kit/tags → KitStatus "Check tags in Kit" button lists which of PT Trial/Monthly/Annual/Cancelled exist + account name/email. User may pre-create tags manually (name match is case-insensitive; POST /tags is idempotent).
- Emails (password_links.py) still signed "Katherine" (welcome/nudge/reset/no_account) — user to decide whether to change to team voice.
- Emails (password_links.py welcome/nudge/reset/no_account) now signed "The Pronounce This Team"; "one of Katherine's coaching members" → "joined through group coaching". No user-facing "Katherine" left in frontend or backend templates (sender stays login@katherinebeck.com / support info@katherinebeck.com).

## 2026-06 — Standard pricing $19/$190 + trial 2 words
- `price_cache.py`: /me `stripe_prices` now pulled LIVE from Stripe by lookup_key (10-min cache; defaults 19/190; savings_note computed) so the paywall always shows what checkout charges. setup_stripe.py amounts → 1900/19000 and was run in preview (TEST mode: archived old $9/$90, created new under same lookup_keys).
- PRODUCTION (live Stripe) still has $9/$90 under the lookup keys until the user updates them in the Stripe Dashboard (create $19/mo + $190/yr prices on the product, move lookup_keys `accent_coach_monthly` / `accent_coach_yearly`, archive old). Existing $9 subscribers keep their archived price. Founding-member $9 is now sold via Kajabi sales page (webhook grants access).
- TRIAL_WORD_LIMIT 5 → 2; all copy updated (landing FAQ, TrialSignupForm, LoginModal, WelcomeModal, PaywallModal, owner notify emails). Existing trial users who already used ≥2 words are now at the paywall.
- Founding-member prices kept ACTIVE but hidden: lookup_keys `founding_monthly` ($9) / `founding_yearly` ($90). Hidden checkout links for the Kajabi sales page: `https://pronouncethis.us/api/payments/checkout?plan=founding-monthly` and `?plan=founding-annual` (PLAN_KEYS in stripe_payments.py; titles "Founding Member (Monthly/Annual)"; Kit tags PT Monthly/PT Annual; same success page → create password). setup_stripe.py creates all 4 prices (run in TEST mode in preview). LIVE Stripe: user must rename lookup keys on existing $9/$90 prices to founding_* and create $19/$190 with accent_coach_* keys.
- Stripe Payment Link / Buy Button support: `_grant_from_session` now reads the plan from the subscription's price when session metadata lacks lookup_key (tested in Stripe test mode → "Founding Member (Monthly)"). User's existing Stripe button on Kajabi works if its after-payment redirect is set to `https://pronouncethis.us/payment/success?session_id={CHECKOUT_SESSION_ID}` and its price carries lookup_key founding_monthly/founding_yearly.

## 2026-06 — Landing redesign v4 (Kajabi match) + coral accent app-wide
- Reference: https://www.katherinebeck.com/pronounce-this-founding-member. Landing rebuilt centered: topbar sign-in link, logo image (/landing/logo.png — user's logo recolored amber→#ef5973 via PIL), italic PT Sans tagline, hero devices image, pill coral CTAs; cream band "For the non-U.S. actor who…" with 1px ink box + bold phrases; struggle (2-line h2, 4 paragraphs, hr, "What are you going to do…" h3, 4 coral strikethrough tried rows); "Ways to use" white text-card + screenshot (alternating); Sneak preview Wistia iframe (d0vcs02fod); testimonial; FAQ 2-col "+" cards (5 incl. free-trial Q); closing; footer ©. Pricing section/columns intentionally omitted (user). Fonts PT Sans (heads) / Open Sans (body) loaded in index.html.
- Accent color: amber → coral #ef5973 everywhere: index.css light theme --amber/--amber-hi (#d94a63), --primary/--ring HSL, btn-primary text now white, rgba(229,169,60)→rgba(239,89,115) in all src; tailwind rust #EF5973 / rustDeep #F2778C. Popups `.popup-fonts` → PT Sans/Open Sans.
- NOTE: the 3 landing screenshots (hero-devices.png, word-tool.jpg, scene-tool.jpg) still show the OLD amber UI inside the images — user chose to keep them; offer re-shoot.

## 2026-06 — Logo + fonts pass (user request)
- Logo: stress mark moved closer to P (gap 45px→15px at 2000px source), coral recolor; files /landing/logo.png, logo@1200.png, logo@600.png. `components/Logo.jsx` (<Logo className="h-5" />) used in app header (links to /), LoginModal, SupportModal, ResetPassword/PaymentSuccess/PaymentCancel/Verify pages (replacing the "PRONOUNCE THIS" mono eyebrow).
- Landing: new images from user zip (hero-devices.png transparent-trimmed; word-tool.jpg / scene-tool.jpg auto-cropped to the content column); tagline smaller/regular-weight/one line, tighter under logo; inline logo in "Ways to use [logo]" h2 and closing sentence "It's time to prepare for your next American accent audition with [logo]"; h3 breaks before "self-tape" on ≥900px.
- App fonts: tailwind display → PT Sans, serif/mono → Open Sans, new `font-typewriter` (Courier Prime) used ONLY for the searched headword + its IPA on the Word page; index.css --font-type/--font-mono/--font-display updated; toast font Open Sans. Copy: reverted to "Pronounce This Word." / "Pronounce This Scene." (app + landing feature titles) (PronouncePage + UploadDropzone); removed "An American Accent Pronunciation Tool" eyebrow above the Word heading.
- Landing sneak-preview video: Wistia iframe replaced with user's walkthrough (self-hosted): /landing/walkthrough.mp4 (H.264 720p CRF27, 6.6MB, faststart) + /landing/walkthrough.webm (VP9 fallback, 8MB) + poster walkthrough-poster.jpg; native <video controls playsInline preload=metadata>. Verified playback (webm in headless Chromium; mp4 for real browsers). Source 43MB mp4 kept out of repo.
- Payment Link status fix: GET /payments/status/{sid} now looks up unknown `cs_*` sessions directly in Stripe (creates payment_transactions record source=payment_link, grants if paid) so Buy-Button purchases land on "create your password" instead of "still waiting on Stripe". USER VERIFIED end-to-end on live (Kajabi Buy Button → password → app). Admin → Stripe sync now shows `StripePrices.jsx` (all prices + lookup keys + 4-plan health dots; GET /admin/stripe/prices). Live Stripe: product rename "Pronounce This" + lookup keys confirmed; Monthly was broken because key was typed into Description — fixed by user.
- Friendly paywall error for unknown_price. ElevenLabs Starter at 100% (resets Oct 22) — user advised to upgrade to Creator or enable usage-based billing.

## 2026-06 — "of course" glitch root cause (The Studio scene)
- Reproduced: plain multilingual_v2 render is clean; the glitch ("UV course"/"You've course") happens ONLY when "of" is a coach pronunciation preference → `<phoneme ph="AH1 V">` on turbo_v2. Deterministic, so retries couldn't help. Live DB has "of"=ʌv as a pref (Word tool wants citation form).
- Fix in server.py: `_FUNCTION_WORDS` never phoneme-tagged in sentences; `_synth_line/_synthesize(allow_tags=)`; both scene-line render paths (download-lines + single turn) pass a render() that uses tags on take 1 only, plain on retries. Startup purges turn_audio_cache entries with check.gave_up/stt_bias so flagged takes re-render. Verified: with PREFERRED_ARPA["of"]="AH1 V", "No, of course not." → 1 take, verified.
- Needs Republish; the user's existing scene lines flagged bad will re-render on next play; unflagged old takes need re-upload.
- Removed 'Specifically Designed For Actors' eyebrow under Pronounce This Scene on the Word page.
- Scene intro copy (Word page promo + Scene upload page): 'Hear each word, see it written phonetically (IPA) and practice with sound lists pulled from your scene. Download an audio of your character's dialogue or download your reader's lines.'

## 2026-06 — Scene-page allowance (fair use)
- `page_allowance.py`: MEMBER_PAGE_CAP=8 pages/upload (was 10), MONTHLY_PAGE_ALLOWANCE=25 pages per billing month, cycle anchored to the member's active-membership created_at day-of-month (clamped for short months); per-user override `users.page_allowance`. Usage stored in `page_usage` {email,pages,scene_id,at}. Upload returns 429 with a friendly message (resets date + support email) when a PDF exceeds remaining pages; trial unchanged (2 pages / 1 scene).
- /me adds pages_used / pages_allowance / pages_reset_at (members only) → AccountChip shows "X of 25 scene pages used · resets <date>". Admin → All users: "Pages / mo" column (used/allowance, amber ≥80%, red at limit; click → prompt to set per-member allowance via PATCH /admin/users/{email}/page-allowance). Uploaders show 429 toast for 15s.
- Verified: cycle math (anchor 31st), usage/record/limit message, /me fields, admin column, account menu line. Decision: single tier for now; add Premium when members hit the cap.
