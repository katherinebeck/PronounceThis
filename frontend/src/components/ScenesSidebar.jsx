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
  const [mobileOpen, setMobileOpen] = useState(false);

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

  const activeScene = scenes.find((s) => s.id === activeId);

  return (
    <aside
      className="w-full md:w-64 md:shrink-0 border-b md:border-b-0 md:border-r thin-rule bg-surface flex flex-col min-w-0"
      data-testid="scenes-sidebar"
    >
      {/* Mobile-only compact header */}
      <div className="md:hidden px-4 py-3 border-b thin-rule flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
            Scene Library
          </div>
          <div className="font-display text-lg text-ink truncate">
            {activeScene?.title || `${scenes.length} scene${scenes.length === 1 ? "" : "s"}`}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            className="btn-secondary !px-3 !py-2"
            data-testid="mobile-new-scene-button"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          </button>
          <button
            type="button"
            className="btn-secondary !px-3 !py-2"
            data-testid="mobile-scenes-toggle"
            onClick={() => setMobileOpen((v) => !v)}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? "Hide" : "Library"}
          </button>
        </div>
      </div>

      {/* Desktop header */}
      <div className="hidden md:block px-6 py-7 border-b thin-rule">
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2">
          The Workbench
        </div>
        <div className="font-display text-3xl leading-none text-ink">
          Scene Library
        </div>
      </div>

      {/* Desktop upload button */}
      <div className="hidden md:block px-4 py-4 border-b thin-rule">
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
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        data-testid="sidebar-upload-input"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      <div
        className={
          "overflow-auto scrollbar-thin " +
          (mobileOpen ? "block" : "hidden md:block") +
          " md:flex-1 max-h-[45vh] md:max-h-none"
        }
      >
        {scenes.length === 0 ? (
          <div className="px-6 py-6 md:py-10 text-sm text-muted2 font-serif italic">
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
                  onClick={() => {
                    onSelect?.(s.id);
                    setMobileOpen(false);
                  }}
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
                      className="md:opacity-0 md:group-hover:opacity-100 transition-opacity p-1 text-muted2 hover:text-rust"
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
      <div className="hidden md:flex px-6 py-4 border-t thin-rule font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 items-center gap-2" data-testid="scene-retention-note">
        <Upload size={12} /> Scenes are kept for 90 days
      </div>
    </aside>
  );
}
