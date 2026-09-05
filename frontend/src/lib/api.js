import axios from "axios";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

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

export async function fetchTTS(word) {
  const { data } = await api.post("/tts", { word });
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

export async function downloadMyLines(sceneId, { character, voice = null } = {}) {
  const params = { character };
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
