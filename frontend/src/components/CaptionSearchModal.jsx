import React, { useEffect, useMemo, useRef, useState } from "react";
import { X, ChevronLeft, ChevronRight, Loader2, RefreshCw, ExternalLink } from "lucide-react";
import { captionSearch } from "@/lib/api";
import { toast } from "sonner";

// YouGlish-style single-clip player. Opens on the first result, cued to the
// word, and lets you tap ▶ / ◀ to jump to the next / previous clip. No
// sidebar, no transcript spam — just the word, spoken.
export default function CaptionSearchModal({ open, query, onClose }) {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const abortRef = useRef(null);

  const load = async (refresh = false) => {
    if (!query) return;
    if (abortRef.current) abortRef.current.abort?.();
    setLoading(true);
    setError("");
    try {
      const data = await captionSearch(query, { refresh });
      // YouGlish behavior: only keep clips cued to the exact word. Full-video
      // fallbacks (no captions) aren't useful when you just want to hear the
      // word right now.
      const cued = (data.results || []).filter((r) => r.has_timestamp);
      setResults(cued);
      setIndex(0);
      if (!cued.length) {
        setError(
          data.error ||
            "No timestamped clips from the curated American-speaker channels for that word. Try Refresh or a variant spelling."
        );
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || "Search failed.";
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  // Reload whenever the modal opens with a new query.
  useEffect(() => {
    if (!open || !query) return;
    setResults([]);
    setIndex(0);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, query]);

  // Keyboard: Esc closes, ←/→ cycles clips.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose?.();
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, onClose, results.length]);

  const current = results[index] || null;

  const next = () => {
    if (!results.length) return;
    setIndex((i) => (i + 1) % results.length);
  };
  const prev = () => {
    if (!results.length) return;
    setIndex((i) => (i - 1 + results.length) % results.length);
  };

  const embedSrc = useMemo(() => {
    if (!current) return null;
    const start = Math.max(0, Math.floor(current.offset_seconds || 0));
    // Autoplay is fine here: the modal only opens on a direct user click,
    // which satisfies the browser autoplay policy.
    const params = new URLSearchParams({
      start: String(start),
      autoplay: "1",
      rel: "0",
      modestbranding: "1",
    });
    return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(
      current.video_id
    )}?${params.toString()}`;
  }, [current]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4 animate-fade-in"
      data-testid="caption-search-modal"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl bg-surface border thin-rule shadow-2xl max-h-[95vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 border-b thin-rule gap-3">
          <div className="min-w-0">
            <div className="font-mono text-[9px] sm:text-[10px] uppercase tracking-[0.22em] sm:tracking-[0.28em] text-muted2">
              Real Speakers · American
            </div>
            <div
              className="font-display text-xl sm:text-2xl text-ink mt-0.5 truncate"
              data-testid="caption-search-query"
            >
              {query}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              className="btn-secondary !px-2.5 sm:!px-3 !py-2"
              onClick={() => load(true)}
              disabled={loading}
              data-testid="caption-search-refresh"
              title="Refresh from YouTube"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
            <button
              type="button"
              className="text-muted2 hover:text-ink p-1"
              onClick={onClose}
              data-testid="caption-search-close"
              aria-label="Close"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Player */}
        <div className="p-4 sm:p-5 bg-surface">
          <div className="aspect-video bg-ink border thin-rule overflow-hidden relative">
            {loading ? (
              <div className="absolute inset-0 flex items-center gap-2 justify-center font-mono text-xs text-paper/80">
                <Loader2 size={14} className="animate-spin" /> Searching real
                speakers…
              </div>
            ) : embedSrc ? (
              <iframe
                key={embedSrc}
                title={current?.title || query}
                className="w-full h-full"
                src={embedSrc}
                allow="autoplay; encrypted-media; picture-in-picture"
                allowFullScreen
                data-testid="caption-search-iframe"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center p-6 text-center font-serif text-sm text-paper/80 italic leading-relaxed">
                {error ||
                  "No matches yet. Tap Refresh, or try a variant spelling."}
              </div>
            )}
          </div>

          {/* Nav row */}
          <div className="mt-3 sm:mt-4 flex items-center justify-between gap-3">
            <button
              type="button"
              className="btn-secondary !px-3 !py-2 disabled:opacity-40"
              onClick={prev}
              disabled={!results.length || results.length < 2}
              data-testid="caption-search-prev"
              aria-label="Previous clip"
              title="Previous clip (←)"
            >
              <ChevronLeft size={16} />
              <span className="hidden sm:inline">Prev</span>
            </button>

            <div className="flex-1 text-center min-w-0 px-2">
              <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 truncate">
                {current
                  ? `${current.channel_title} · clip ${index + 1} of ${results.length}`
                  : loading
                  ? "Loading…"
                  : results.length
                  ? `Clip ${index + 1} of ${results.length}`
                  : "No clips"}
              </div>
            </div>

            <button
              type="button"
              className="btn-primary !px-3 !py-2 disabled:opacity-40"
              onClick={next}
              disabled={!results.length || results.length < 2}
              data-testid="caption-search-next"
              aria-label="Next clip"
              title="Next clip (→)"
            >
              <span className="hidden sm:inline">Next</span>
              <ChevronRight size={16} />
            </button>
          </div>

          {/* Optional "Open on YouTube" — minimal footer */}
          {current ? (
            <div className="mt-3 flex justify-end">
              <a
                className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 hover:text-ink inline-flex items-center gap-1.5"
                href={current.youtube_url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="caption-search-open-external"
              >
                <ExternalLink size={11} />
                Open on YouTube
              </a>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
