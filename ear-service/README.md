# Pronounce This — ear service

The phoneme recogniser ("ear") behind **Practise This Word**, packaged as its own tiny web
service so the main Pronounce This backend stays light. The backend talks to it over HTTPS;
if the ear is ever unreachable the backend falls back to Azure-only scoring for that take
(students still get feedback, just without the second opinion).

Needs: **2 GB RAM, 1–2 vCPU**, no GPU. ~1–2 s per take on CPU.

## 1. Build & run anywhere (Docker)

```bash
# from the repo root
docker build -f ear-service/Dockerfile -t pt-ear .
docker run -p 8080:8080 -e EAR_SECRET='choose-a-long-random-string' pt-ear
curl -H "X-Ear-Secret: choose-a-long-random-string" http://localhost:8080/health
# → {"ready": true, "model": "...timit-phoneme", "status": "ready", "mode": "in-process"}
```

The model (~1.2 GB) is baked into the image at build time, so starts take ~20 s, not minutes.

## 2. Host it (pick one)

**Fly.io (~$8–14/month always-on; much less with idle-suspend)** — `fly.toml` is included.
```bash
fly launch --no-deploy --copy-config --name pronouncethis-ear   # from the repo root
cp ear-service/fly.toml fly.toml                                 # launch writes a 1 GB default; ours is 2 GB + idle-suspend
fly secrets set EAR_SECRET='choose-a-long-random-string'
fly deploy
fly scale count 1                                                # launch creates two machines by default
```
Cost controls: `fly.toml` suspends the machine when idle (resumes in ~1–2 s, model kept in memory; suspended
machines aren't billed for CPU/RAM) and runs one analysis at a time, refusing with 503 "ear busy" when
more than `EAR_MAX_WAITING` takes are queued (the backend then scores that take Azure-only). Check with
`fly status` (one machine) and `fly scale show`. Redeploy after any change to `backend/phoneme_ear.py`.
Public URL: `https://pronouncethis-ear.fly.dev`

**Render / Railway / DigitalOcean App Platform** — new Web Service from this repo,
Dockerfile path `ear-service/Dockerfile`, build context `.` (repo root), 2 GB instance,
env var `EAR_SECRET`. Health check path `/health` needs the secret header, so use a TCP check
or leave the platform default.

**Render (~$25/month, 2 GB "Standard")** — `render.yaml` is included: Render → New → Blueprint → this repo.
It generates `EAR_SECRET` for you (copy it from the service's Environment tab for step 3).

**Google Cloud Run (pay per use; ~$15–20/month with one warm instance)**
```bash
gcloud run deploy pronouncethis-ear --source . --region us-east1 --memory 2Gi --cpu 2 \
  --min-instances 1 --set-env-vars EAR_SECRET='choose-a-long-random-string' \
  --allow-unauthenticated --port 8080
# Cloud Run needs the Dockerfile at the context root: copy ear-service/Dockerfile to ./Dockerfile first.
```
Without `--min-instances 1` the first take after idle waits ~30 s for a cold start.

**Hugging Face Inference Endpoints / Replicate** — also possible, but they expect their own
wrappers (handler.py / Cog) rather than this Docker service; use one of the options above unless
you already have an account there.

**A plain VPS (Hetzner CX22 ~€4, DigitalOcean 2 GB $12)** — install Docker, run the
`docker run` line above behind Caddy/nginx with HTTPS.

## 3. Point the backend at it

In the Pronounce This app secrets (Emergent → Secrets), add:

| key | value |
|---|---|
| `EAR_URL` | `https://pronouncethis-ear.fly.dev` (no trailing slash) |
| `EAR_SECRET` | the same long random string |
| `PRACTICE_MODE` | `on` |

Then publish. `GET /api/practice/status` should return `{"enabled": true, ...}` and the admin
"Sounds heard" readout shows `mode: remote`. `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION`
must already be set (Azure Standard S0 tier for members; the free F0 tier is single-request).

## 4. Turning it off

Remove `PRACTICE_MODE` (or set it to `off`) and publish — the record button disappears.
Removing `EAR_URL` alone keeps the feature on but Azure-only (not recommended).

## API

- `GET /health` → `{"ready": true|false, "model", "status", "error", "mode"}`
- `POST /listen` body `{"wav_b64": "<16 kHz mono PCM wav>", "windows": [{"expected": "ɑɹ", "start_s": 0.12, "end_s": 0.31, "flap": false}]}`
  → the same object `backend/phoneme_ear.listen()` returns (`heard`, `checks`, `tokens`, `extra_nuclei`).
- Every request needs header `X-Ear-Secret`.
