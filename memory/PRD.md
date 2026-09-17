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

## 2026-06 — Anthropic key rotation
- ANTHROPIC_API_KEY replaced in backend/.env (old key expires 2026-09-15). Only that line changed. Verified by testing agent (iteration_20: 6/6 pass) — api.anthropic.com 200, no Emergent fallback. User must re-publish for production.
