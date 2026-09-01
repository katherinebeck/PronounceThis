import React, { useEffect, useRef, useState } from "react";
import { Plus, Trash2, Upload, Loader2 } from "lucide-react";
import { uploadScene, deleteScene } from "@/lib/api";
import { toast } from "sonner";

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function ScenesSidebar({
  scenes,
  activeId,
  onSelect,
  onNewScene,
  onDeleted,
}) {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);

  const handleFile = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const scene = await uploadScene(file);
      toast.success(`"${scene.title}" transcribed.`);
      onNewScene?.(scene);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed.");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleDelete = async (id, title, e) => {
    e.stopPropagation();
    if (!window.confirm(`Delete "${title}"?`)) return;
    try {
      await deleteScene(id);
      toast.success("Scene deleted.");
      onDeleted?.(id);
    } catch {
      toast.error("Delete failed.");
    }
  };

  return (
    <aside
      className="w-64 shrink-0 border-r thin-rule bg-surface flex flex-col min-w-0"
      data-testid="scenes-sidebar"
    >
      <div className="px-6 py-7 border-b thin-rule">
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2">
          The Workbench
        </div>
        <div className="font-display text-3xl leading-none text-ink">
          Scene Library
        </div>
      </div>
      <div className="px-4 py-4 border-b thin-rule">
        <button
          type="button"
          className="btn-secondary w-full justify-center"
          data-testid="new-scene-button"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          {busy ? (
            <>
              <Loader2 size={13} className="animate-spin" /> Working
            </>
          ) : (
            <>
              <Plus size={13} /> New Scene
            </>
          )}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          data-testid="sidebar-upload-input"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
      <div className="flex-1 overflow-auto scrollbar-thin">
        {scenes.length === 0 ? (
          <div className="px-6 py-10 text-sm text-muted2 font-serif italic">
            No scenes yet. Upload a PDF to start your first transcription.
          </div>
        ) : (
          <ul>
            {scenes.map((s) => {
              const active = s.id === activeId;
              return (
                <li
                  key={s.id}
                  className={
                    "px-6 py-4 border-b thin-rule cursor-pointer group transition-colors " +
                    (active ? "bg-paper" : "hover:bg-paper/60")
                  }
                  data-testid={`scene-list-item-${s.id}`}
                  onClick={() => onSelect?.(s.id)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div
                        className={
                          "font-display text-xl leading-tight truncate " +
                          (active ? "text-rust" : "text-ink")
                        }
                      >
                        {s.title}
                      </div>
                      <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
                        {s.word_count} words · {formatDate(s.created_at)}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-muted2 hover:text-rust"
                      data-testid={`delete-scene-${s.id}`}
                      onClick={(e) => handleDelete(s.id, s.title, e)}
                      aria-label="Delete scene"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <div className="px-6 py-4 border-t thin-rule font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 flex items-center gap-2">
        <Upload size={12} /> Saved locally in your session
      </div>
    </aside>
  );
}
