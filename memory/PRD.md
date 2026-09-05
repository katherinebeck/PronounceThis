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

## Next tasks
1. **[Waiting on user]** Create Monthly + Annual (+ optional Group Coaching) offers in Kajabi, then paste the 3 checkout URLs so we can drop them into `KAJABI_MONTHLY_OFFER_URL` / `KAJABI_ANNUAL_OFFER_URL` / `KAJABI_MEMBER_PORTAL_URL`.
2. **[Waiting on user]** Configure the Purchase Created + Payment Succeeded webhooks + cancellation Automation in Kajabi per the setup guide.
3. **Domain verification for Resend** — verify `katherinebeck.com` in Resend so login emails ship from `login@katherinebeck.com` (currently in Resend test mode which only delivers to the account owner).
4. **Nightly Kajabi reconciliation job** using the Public API — catches missed cancellations/refunds. `KAJABI_API_CLIENT_ID` + `KAJABI_API_CLIENT_SECRET` already saved.
5. **Merriam-Webster audio integration (P0)** — still waiting on MW API key.
6. Playback speed toggles (0.5× / 0.75× / 1×).
7. Refactor `server.py` (now ~1130 lines) into `routes/` + `services/`.
