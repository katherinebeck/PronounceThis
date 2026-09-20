import React, { useCallback, useEffect, useState } from "react";
import { Loader2, EyeOff, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

const inputCls =
  "w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink";

// Admin: hide a specific Real Speakers clip (e.g. a non-GA speaker) for everyone.
export function HiddenVideos() {
  const [videos, setVideos] = useState([]);
  const [url, setUrl] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/hidden-videos");
      setVideos(data.videos || []);
    } catch {
      setVideos([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const hide = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    try {
      const { data } = await api.post("/admin/hidden-videos", { url_or_id: url.trim(), reason });
      toast.success(`Hidden ${data.video_id}`);
      setUrl("");
      setReason("");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail === "could_not_parse_video_id"
        ? "Paste a YouTube link or 11-character video ID" : "Could not hide video");
    } finally {
      setBusy(false);
    }
  };

  const unhide = async (video_id) => {
    try {
      await api.post("/admin/hidden-videos/delete", { video_id });
      load();
    } catch {
      toast.error("Could not unhide");
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-hidden-videos">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Real Speakers · hidden clips
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Hidden clips
        <span className="font-mono text-sm text-muted2 ml-2" data-testid="hidden-video-count">{videos.length}</span>
      </h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Heard a speaker who isn’t American? Use the “Not American · hide” link under any
        clip, or paste the YouTube link here. Hidden clips disappear from Real Speakers for
        everyone — the channel stays. Clips reported as unplayable by two members land here too.
      </p>
      <form onSubmit={hide} className="grid gap-3 sm:grid-cols-[2fr_1fr_auto]">
        <input type="url" required placeholder="https://www.youtube.com/watch?v=…" value={url}
          onChange={(e) => setUrl(e.target.value)} className={inputCls} data-testid="hidden-video-url" />
        <input type="text" placeholder="Reason (optional)" value={reason}
          onChange={(e) => setReason(e.target.value)} className={inputCls} data-testid="hidden-video-reason" />
        <button type="submit" disabled={busy} className="btn-primary justify-center" data-testid="hidden-video-submit">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <EyeOff size={14} />} Hide
        </button>
      </form>
      {videos.length ? (
        <ul className="mt-5 divide-y thin-rule border thin-rule" data-testid="hidden-video-list">
          {videos.map((v) => (
            <li key={v.video_id} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <div className="min-w-0">
                <a href={`https://www.youtube.com/watch?v=${v.video_id}`} target="_blank" rel="noreferrer"
                  className="font-mono text-sm text-ink underline underline-offset-4 decoration-ink/30">
                  {v.video_id}
                </a>
                <span className="ml-3 font-serif text-sm text-muted2 italic truncate">
                  {v.channel_title ? `${v.channel_title} · ` : ""}{v.reason || v.title || ""}
                </span>
              </div>
              <button type="button" onClick={() => unhide(v.video_id)} className="text-muted2 hover:text-rust p-1" title="Unhide"
                data-testid={`hidden-video-remove-${v.video_id}`}>
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
