import { fetchTTS, fetchTurnTTS } from "./api";

const cache = new Map(); // word(lower) -> ObjectURL
const turnCache = new Map(); // `${sceneId}:${turnIndex}` -> ObjectURL

function b64ToBlobUrl(audio_b64, mime) {
  const bin = atob(audio_b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: mime || "audio/mpeg" });
  return URL.createObjectURL(blob);
}

function friendlyError(e, fallback = "Audio playback failed.") {
  const msg = e?.response?.data?.detail;
  if (typeof msg === "string" && msg.includes("detected_unusual_activity"))
    return "ElevenLabs free tier is blocked from cloud servers — please upgrade your plan to enable audio.";
  if (typeof msg === "string") return msg.slice(0, 220);
  return fallback;
}

export async function playWord(word) {
  if (!word) return;
  const key = word.toLowerCase();
  let url = cache.get(key);
  if (!url) {
    let resp;
    try {
      resp = await fetchTTS(word);
    } catch (e) {
      const err = new Error(friendlyError(e, "Unable to generate audio."));
      err.friendly = err.message;
      throw err;
    }
    url = b64ToBlobUrl(resp.audio_b64, resp.mime);
    cache.set(key, url);
  }
  const audio = new Audio(url);
  audio.preload = "auto";
  await audio.play().catch(() => {});
  return audio;
}

export async function loadTurnAudio(sceneId, turnIndex, { voice = null } = {}) {
  const key = `${sceneId}:${turnIndex}` + (voice ? `:${voice}` : "");
  let url = turnCache.get(key);
  if (url) return url;
  let resp;
  try {
    resp = await fetchTurnTTS(sceneId, turnIndex, { voice });
  } catch (e) {
    const err = new Error(friendlyError(e, "Unable to generate line audio."));
    err.friendly = err.message;
    throw err;
  }
  url = b64ToBlobUrl(resp.audio_b64, resp.mime);
  turnCache.set(key, url);
  return url;
}

/** Play one speaker turn. Returns the HTMLAudioElement so caller can wire
 * 'ended' or 'pause' events for sequencing. */
export async function playTurn(sceneId, turnIndex, opts = {}) {
  const url = await loadTurnAudio(sceneId, turnIndex, opts);
  const audio = new Audio(url);
  audio.preload = "auto";
  await audio.play().catch(() => {});
  return audio;
}
