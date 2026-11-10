# RCA — accent-coach-pro / pronouncethis.us (run 940caaec-f097-4faf-a806-63cfad79c9d8)

## Summary
The latest republish (redeploy run `940caaec…`, completed 2026-11-10 03:02:57Z) is **green and healthy**. The build succeeded with no dependency errors. The "errors in the logs" the user saw are a mix of (a) benign nginx→backend readiness-probe noise during the normal pod-startup window, and (b) two gracefully-handled transient WARNINGs. **No application ERROR, no Traceback, no import error, no MongoDB/env-var failure exists in the logs.** The new EAR service integration is working: the prod pod reaches the Fly URL and `EAR_SECRET` authenticates (health returns 200, never 401/403).

## Build logs (build_image) — CLEAN
- `build_state: SUCCESS`. No pip errors; no torch / transformers / soundfile resolution errors (confirming requirements.txt intentionally omits them).
- Only non-standard line, benign:
  `#51 ... Browserslist: browsers data (caniuse-lite) is 11 months old. Please run: ...`

## Secret presence (active run) — all CONFIRMED present
- `EAR_URL` — present, `matches_expected: true` (= https://pronouncethis-ear.fly.dev)
- `EAR_SECRET` — present (is_empty: false)
- `PRACTICE_MODE` — present
- `AZURE_SPEECH_KEY` — present
- `AZURE_SPEECH_REGION` — present
(values never read — presence/metadata only)

## EAR service reachability + auth — WORKING
Recurring success, every ~60s, and on startup of each pod:
- `2026-11-10 03:02:32,807 - ear - INFO - phoneme ear ready via https://pronouncethis-ear.fly.dev (vitouphy/wav2vec2-xls-r-300m-timit-phoneme)`
- `2026-11-10 03:06:21,936 - ear - INFO - phoneme ear ready via https://pronouncethis-ear.fly.dev (...)`
- `2026-11-10 03:02:32,806 / 03:03:33,113 / 03:04:33,618 / 03:05:33,942 / 03:06:21,935 / 03:06:34,262 / 03:07:22,422 / 03:07:34,582 / 03:08:22,836 / 03:08:34,891 - httpx - INFO - HTTP Request: GET https://pronouncethis-ear.fly.dev/health "HTTP/1.1 200 OK"`
Conclusion: the pod CAN reach the Fly URL, and `EAR_SECRET` is correct — every health call returns **200 OK**; there is **no 401/403 anywhere**.

## Errors/warnings found — verbatim, with timestamp + recurrence

### WARNING (2) — both transient, gracefully handled
1. `2026-11-10 03:05:02,648 - ear - WARNING - phoneme ear service failed, Azure-only for this take: The read operation timed out`
   - **Single occurrence.** A one-off httpx READ timeout on one assess call (not an auth failure — surrounding `/health` calls at 03:04:33 and 03:05:33 both returned 200). The app fell back to Azure-only for that request; `POST /api/practice/assess` still returned 200 OK. Likely a Fly cold-start / network blip.
2. `2026-11-10 03:03:04,241 - price_cache - WARNING - stripe price fetch failed, using defaults: get`
   - **Single occurrence** at startup. Stripe price lookup fell back to defaults; note the immediately-following `stripe - INFO ... response_code=200` shows Stripe is otherwise reachable. Benign fallback.

### ERROR-level lines (13) — ALL nginx readiness-probe noise during pod startup, NOT app errors
These are the sidecar nginx failing to reach uvicorn (port 8001) during the brief window before the backend bound the port on each rolling pod. They self-clear the moment `Application startup complete` / `Uvicorn running on 0.0.0.0:8001` appears.
- `2026/11/10 03:02:31 [error] 27#27: *1 connect() failed (111: Connection refused) while connecting to upstream ... "GET /health HTTP/1.1" ... upstream: "http://127.0.0.1:8001/health", host: "10.60.55.241:8080"` — 1×, cleared when uvicorn bound at 03:02:32.
- `2026/11/10 03:04:47 [error] ... upstream timed out (110: Connection timed out) while reading response header from upstream ... "GET /health" ...` — 2× at 03:04:47.
- `2026/11/10 03:05:36 → 03:05:41 → 03:05:46 → 03:05:51 → 03:05:56 → 03:06:01 → 03:06:06 → 03:06:11 → 03:06:16 → 03:06:21 [error] 26#26 connect() failed (111: Connection refused) ... "GET /health" ... host: "10.60.12.242:8080"` — 10× every 5s during the second pod's startup window; cleared at 03:06:21 when that pod's uvicorn bound (`phoneme ear ready ... 03:06:21,936`).
- Recurrence: bounded strictly to each pod's startup window; none after the app is up.

### 404 noise (97×) — benign
- `INFO:     127.0.0.1:<port> - "GET /health HTTP/1.0" 404 Not Found` (×97)
- The platform/nginx liveness probe hits `/health` on the FastAPI backend, which has no `/health` route, so FastAPI returns 404. A 404 counts as "server up" for the probe, so this never blocks readiness — it is pure log noise. Recurring continuously but harmless.

## Confirmed state
- App is live and serving: `GET /` 200, `/api/practice/status` 200, `/api/auth/me` 200, `/api/practice/assess` 200, Azure STT `POST .../cognitiveservices/v1 "HTTP/1.1 200 OK"` ×2, ElevenLabs 200s, Supabase JWKS refreshed, Mongo-backed routes all 200. No 5xx. No Traceback. No OOM/crash events relevant to this run.

## Suggested (optional) cleanups — none are required; app is healthy
1. (Code) Add a lightweight `GET /health` route to the FastAPI app returning 200 — removes the 97× 404 probe noise AND the nginx "connect/timeout to /health" lines will stop being alarming. Purely cosmetic for log hygiene.
2. (Code) If the single `ear ... read operation timed out` recurs under load, consider a slightly higher httpx read timeout and/or a retry on the assess path to the Fly ear service — the Azure-only fallback already covers it, so this is a resilience nicety, not a fix.
3. (User/Code) `stripe price fetch failed, using defaults` — monitor; if pricing ever shows defaults incorrectly, verify the `accent_coach_monthly` lookup key exists in the active Stripe mode. One-off here, Stripe otherwise returned 200.
