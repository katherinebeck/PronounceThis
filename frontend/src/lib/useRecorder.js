import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { trimRecording } from "./audioTrim";

// Mic capture → auto-trimmed WAV blob + preview URL.
export function useRecorder({ onError, trim = true, raw = false } = {}) {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [blob, setBlob] = useState(null);
  const [blobUrl, setBlobUrl] = useState(null);
  const recRef = useRef(null);
  const chunksRef = useRef([]);

  const reset = useCallback(() => {
    setBlob(null);
    setBlobUrl((u) => { if (u) URL.revokeObjectURL(u); return null; });
  }, []);

  useEffect(() => () => { if (blobUrl) URL.revokeObjectURL(blobUrl); }, [blobUrl]);

  const start = useCallback(async () => {
    try {
      // raw: no browser noise suppression / auto-gain — they strip the quiet voiced closure of b d g (beer → "peer").
      const constraints = raw ? { echoCancellation: false, noiseSuppression: false, autoGainControl: false } : true;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: constraints });
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const raw = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        setProcessing(true);
        let out = raw;
        if (trim) { try { out = await trimRecording(raw); } catch { /* keep raw take */ } }
        reset();
        setBlob(out);
        setBlobUrl(URL.createObjectURL(out));
        setProcessing(false);
      };
      recRef.current = rec;
      rec.start();
      setRecording(true);
    } catch (err) {
      if (onError) onError(err);
      else toast.error("Microphone access was blocked. Allow the mic in your browser and try again.");
    }
  }, [reset, onError, trim, raw]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    setRecording(false);
  }, []);

  const toggle = useCallback(() => { if (recording) stop(); else start(); }, [recording, start, stop]);

  return { recording, processing, blob, blobUrl, start, stop, toggle, reset };
}
