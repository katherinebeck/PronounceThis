import React, { useRef, useState } from "react";
import { Upload, Loader2 } from "lucide-react";
import { uploadScene } from "@/lib/api";
import { toast } from "sonner";

export default function UploadDropzone({ onUploaded }) {
  const fileRef = useRef(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleFile = async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Only text-based PDF files are supported.");
      return;
    }
    setBusy(true);
    try {
      const scene = await uploadScene(file);
      toast.success(`"${scene.title}" transcribed.`);
      onUploaded?.(scene);
    } catch (e) {
      const msg = e?.response?.data?.detail || "Upload failed.";
      toast.error(msg);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div
      data-testid="upload-dropzone"
      className={
        "relative border thin-rule p-12 lg:p-16 bg-surface " +
        (drag ? "ring-2 ring-rust" : "")
      }
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files?.[0];
        handleFile(f);
      }}
    >
      <div className="flex flex-col items-start gap-6 max-w-xl">
        <h2 className="font-display text-3xl sm:text-4xl lg:text-5xl leading-[1.1] text-ink">
          Pronounce This Scene<span className="text-rust">.</span>
          <br />
          <em className="not-italic text-rust text-xl sm:text-2xl lg:text-3xl">Hear how to pronounce every word.</em>
        </h2>
        <p className="text-lg text-muted2 leading-relaxed font-serif">
          Upload a scene. Each word will be transcribed in
          American IPA, click any word to hear it spoken aloud, pull sound
          lists to practice tricky sounds and download an audio
          sample of your character's dialogue for practice.
        </p>
        <div className="flex gap-3 items-center">
          <button
            type="button"
            className="btn-primary"
            data-testid="upload-pdf-button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            {busy ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Transcribing
              </>
            ) : (
              <>
                <Upload size={14} />
                Upload PDF
              </>
            )}
          </button>
          <span className="font-mono text-xs text-muted2">
            or drag a file anywhere in this panel
          </span>
        </div>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        data-testid="upload-pdf-input"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
    </div>
  );
}
