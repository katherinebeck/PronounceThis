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

export async function fetchTurnTTS(sceneId, turnIndex) {
  const { data } = await api.post(
    `/scenes/${sceneId}/turns/${turnIndex}/tts`
  );
  return data; // { scene_id, turn_index, speaker, audio_b64, mime, cached }
}
