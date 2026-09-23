import axios from "axios";
import { supabase } from "./supabase";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// withCredentials so the httpOnly JWT session cookie flows on every request.
export const api = axios.create({ baseURL: API, withCredentials: true });

// Every request carries the Supabase access token; the backend verifies it.
api.interceptors.request.use(async (config) => {
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// --- Auth --------------------------------------------------------------
export async function fetchMe() {
  const { data } = await api.get("/auth/me");
  return data;
}
export async function requestMagicLink(email) {
  const { data } = await api.post("/auth/request-magic-link", { email });
  return data;
}
export async function verifyMagicLink(token) {
  const { data } = await api.get("/auth/verify", { params: { token } });
  return data;
}
export async function logout() {
  const { data } = await api.post("/auth/logout");
  return data;
}

// --- Stripe payments --------------------------------------------------
export async function createStripeCheckout(lookup_key) {
  const { data } = await api.post("/payments/checkout", {
    lookup_key,
    origin_url: window.location.origin,
  });
  return data; // { checkout_url, session_id }
}
export async function getPaymentStatus(session_id) {
  const { data } = await api.get(`/payments/status/${session_id}`);
  return data;
}
export async function createStripePortal() {
  const { data } = await api.post("/payments/portal", {
    origin_url: window.location.origin,
  });
  return data; // { url }
}

export async function uploadScene(file) {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await api.post("/scenes/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listScenes() {
  const { data } = await api.get("/scenes");
  return data;
}

export async function getScene(id) {
  const { data } = await api.get(`/scenes/${id}`);
  return data;
}

export async function deleteScene(id) {
  const { data } = await api.delete(`/scenes/${id}`);
  return data;
}

export async function fetchLaundryList(sceneId, sound) {
  const { data } = await api.get(`/scenes/${sceneId}/laundry-list`, {
    params: { sound },
  });
  return data;
}

export async function fetchSoundCategories() {
  const { data } = await api.get("/sound-categories");
  return data.categories;
}

export async function fetchTTS(word, phonetic = false, arpabet = null) {
  const body = { word, phonetic };
  if (arpabet) body.arpabet = arpabet;
  const { data } = await api.post("/tts", body);
  return data; // { word, audio_b64, mime, cached }
}

export async function pronounceWord(word) {
  const { data } = await api.get("/pronounce", { params: { word } });
  return data; // { word, normalized, ipa, arpabet, categories, source }
}

export async function captionSearch(query, { limit = 6, refresh = false } = {}) {
  const { data } = await api.get("/caption-search", {
    params: { q: query, limit, refresh: refresh ? "true" : "false" },
  });
  return data; // { query, results: [{ video_id, title, channel_title, offset_seconds, snippet, youtube_url, thumbnail }], cached }
}

export async function fetchTurnTTS(sceneId, turnIndex, { voice = null } = {}) {
  const params = voice ? { voice } : {};
  const { data } = await api.post(
    `/scenes/${sceneId}/turns/${turnIndex}/tts`,
    null,
    { params }
  );
  return data; // { scene_id, turn_index, speaker, audio_b64, mime, cached }
}

export async function fetchReaderVoices() {
  const { data } = await api.get("/reader-voices");
  return data.voices; // [{ key, label, gender, description }]
}

export async function downloadMyLines(sceneId, { character, voice = null, mode = "mine" } = {}) {
  const params = { character, mode };
  if (voice) params.voice = voice;
  const response = await api.get(`/scenes/${sceneId}/download-lines`, {
    params,
    responseType: "blob",
  });
  // Filename comes from the Content-Disposition header the backend sets.
  const disp = response.headers?.["content-disposition"] || "";
  const match = /filename="?([^"]+)"?/i.exec(disp);
  const filename = match?.[1] || `${character || "lines"}.mp3`;
  return { blob: response.data, filename };
}

export async function reportUnplayable(video_id, code) {
  const { data } = await api.post("/caption-search/unplayable", { video_id, code });
  return data;
}

export async function reportClip(video_id, reason, query) {
  const { data } = await api.post("/caption-search/report", { video_id, reason, query });
  return data;
}

export async function adminHideVideo(video_id, reason) {
  const { data } = await api.post("/admin/hidden-videos", { url_or_id: video_id, reason });
  return data;
}
