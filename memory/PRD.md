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

## Known limitation
- The provided **ElevenLabs key is on the Free tier**, which the provider blocks from cloud datacenter IPs ("detected_unusual_activity"). Upgrading the ElevenLabs plan unlocks real audio playback. All other features are unaffected.

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

## Next tasks
1. Inform user about the ElevenLabs free-tier limitation and the upgrade path.
2. (After user upgrade) Re-run TTS test to confirm audio caching works.
3. Tackle P1 items based on user priority.
