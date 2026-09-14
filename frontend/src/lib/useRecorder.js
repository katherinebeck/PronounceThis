import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { trimRecording } from "./audioTrim";

// Mic capture → auto-trimmed WAV blob + preview URL.
export function useRecorder() {
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
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
        try { out = await trimRecording(raw); } catch { /* keep raw take */ }
        reset();
        setBlob(out);
        setBlobUrl(URL.createObjectURL(out));
        setProcessing(false);
      };
      recRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      toast.error("Microphone access was blocked. Allow the mic in your browser and try again.");
    }
  }, [reset]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    setRecording(false);
  }, []);

  const toggle = useCallback(() => { if (recording) stop(); else start(); }, [recording, start, stop]);

  return { recording, processing, blob, blobUrl, start, stop, toggle, reset };
}
