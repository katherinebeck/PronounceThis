# Pronounce This

Accent-coaching web app: upload a script PDF, get dialogue + American IPA, hear
ElevenLabs TTS, and find native speakers saying each word via a local YouTube
caption index.

## Stack (all open / standard)

| Layer     | Technology                                   |
|-----------|----------------------------------------------|
| Frontend  | React 19 (CRA + craco), Tailwind, shadcn/ui  |
| Backend   | Python 3.11, FastAPI, Motor (async MongoDB)  |
| Database  | MongoDB (any 4.4+ instance / Atlas)          |
| Auth      | Magic links via Resend, JWT in HTTP-only cookie |
| Payments  | Stripe Checkout, Customer Portal, Webhooks   |
| TTS       | ElevenLabs REST API                          |
| Videos    | YouTube Data API v3 + `youtube-transcript-api` |
| LLM       | Anthropic Claude via official `anthropic` SDK |

Nothing in the app depends on a proprietary hosting runtime. Every external
service is reached through its vendor's public API with a key you own.

## Running it anywhere

```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001

# frontend
cd frontend && yarn install && yarn build   # serve /build with any static host
```

Route `/api/*` to the backend and everything else to the frontend build.

### Backend environment variables (`backend/.env`)

| Variable | Purpose |
|----------|---------|
| `MONGO_URL`, `DB_NAME` | MongoDB connection |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `APP_PUBLIC_URL` | Public URL used in magic-link emails / Stripe redirects |
| `JWT_SECRET` | Signs session cookies |
| `ADMIN_EMAILS` | Comma-separated admin logins for `/admin` |
| `RESEND_API_KEY`, `SENDER_EMAIL`, `SENDER_NAME` | Magic-link email delivery |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_MODE` | Subscriptions |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | TTS |
| `YOUTUBE_API_KEY` | Real Speakers search + caption index ingest |
| `ANTHROPIC_API_KEY` | LLM dialogue extraction & IPA fallback (preferred) |
| `EMERGENT_LLM_KEY` | Optional fallback for the LLM if `ANTHROPIC_API_KEY` is unset |
| `LLM_MODEL` | Optional; defaults to `claude-sonnet-4-5-20250929` |
| `KAJABI_*` | Legacy Kajabi webhook/offers (optional) |

### Frontend environment variables (`frontend/.env`)

| Variable | Purpose |
|----------|---------|
| `REACT_APP_BACKEND_URL` | Origin of the API (no trailing slash) |

## Data ownership & export

All state lives in MongoDB. Export with standard tooling:

```bash
mongodump --uri="$MONGO_URL" --db="$DB_NAME" --out=./backup
mongorestore --uri="<new-uri>" ./backup
```

Collections:

- `users` — accounts, trial usage, `stripe_customer_id`
- `memberships` — subscription status; mirrors Stripe (`stripe_customer_id`, `subscription_end_at`)
- `magic_links` — short-lived login tokens
- `pronunciation_overrides` — coach-recorded audio stored as base64 in the document (no external blob store)
- `caption_transcript_cache` — YouTube transcript index (rebuildable via Admin → Deep Index or `prewarm.py`)
- `system_state` — background job bookkeeping

Stripe customers, subscriptions, products and prices live in **your** Stripe
account; the app only stores IDs. Membership state can be re-synced from Stripe
at any time (Admin → "Sync from Stripe", or the self-heal on `/api/auth/me`).

## Dev-only tooling

`@emergentbase/visual-edits` in `frontend/package.json` is an optional
dev-time plugin; `craco.config.js` skips it when not installed. It has no
effect on the production build.
