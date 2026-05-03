import { fetchTTS } from "./api";

const cache = new Map(); // word(lower) -> ObjectURL

export async function playWord(word) {
  if (!word) return;
  const key = word.toLowerCase();
  let url = cache.get(key);
  if (!url) {
    let resp;
    try {
      resp = await fetchTTS(word);
    } catch (e) {
      const msg =
        e?.response?.data?.detail || "Unable to generate audio for this word.";
      const friendly =
        typeof msg === "string" && msg.includes("detected_unusual_activity")
          ? "ElevenLabs free tier is blocked from cloud servers — please upgrade your plan to enable audio."
          : typeof msg === "string"
            ? msg.slice(0, 220)
            : "Audio generation failed.";
      const err = new Error(friendly);
      err.friendly = friendly;
      throw err;
    }
    const { audio_b64, mime } = resp;
    const bin = atob(audio_b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: mime || "audio/mpeg" });
    url = URL.createObjectURL(blob);
    cache.set(key, url);
  }
  const audio = new Audio(url);
  audio.preload = "auto";
  await audio.play().catch(() => {});
  return audio;
}
