import React, { useEffect, useMemo, useRef, useState } from "react";
import { X, ChevronLeft, ChevronRight, Loader2, RefreshCw, ExternalLink, EyeOff, Flag } from "lucide-react";
import { captionSearch, reportUnplayable, adminHideVideo, reportClip } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ClipPlayer } from "./ClipPlayer";
import { toast } from "sonner";

function decodeEntities(s) {
  const el = document.createElement("textarea");
  el.innerHTML = s || "";
  return el.value;
}

function formatTime(secs) {
  const t = Math.floor(secs || 0);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function HighlightedSnippet({ text, query }) {
  const q = (query || "").trim();
  if (!q) return <>{text}</>;
  const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig");
  return (
    <>
      {text.split(re).map((part, i) =>
        part.toLowerCase() === q.toLowerCase() ? (
          <mark key={i} className="bg-rust text-stage px-1 rounded-sm not-italic">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

// YouGlish-style single-clip player. Opens on the first result, cued to the
// word, and lets you tap ▶ / ◀ to jump to the next / previous clip. No
// sidebar, no transcript spam — just the word, spoken.
export default function CaptionSearchModal({ open, query, onClose, inline = false }) {
  const { me } = useAuth();
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const [corrected, setCorrected] = useState(null);
  const abortRef = useRef(null);

  const load = async (refresh = false) => {
    if (!query) return;
    if (abortRef.current) abortRef.current.abort?.();
    setLoading(true);
    setError("");
    try {
      let data;
      for (let attempt = 0; ; attempt++) {
        try {
          data = await captionSearch(query, { refresh });
          break;
        } catch (err) {
          const status = err?.response?.status;
          if (attempt < 2 && (!status || status >= 500)) {
            await new Promise((r) => setTimeout(r, 800 * (attempt + 1)));
            continue;
          }
          throw err;
        }
      }
      // YouGlish behavior: only keep clips cued to the exact word. Full-video
      // fallbacks (no captions) aren't useful when you just want to hear the
      // word right now.
      const cued = (data.results || []).filter((r) => r.has_timestamp);
      setResults(cued);
      setCorrected(data.corrected_query || null);
      setIndex(0);
      if (!cued.length) {
        setError(
          data.error ||
            "No timestamped clips from the curated American-speaker channels for that word. Try Refresh or a variant spelling."
        );
      }
    } catch (err) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      const msg =
        !status || status >= 500
          ? "Real Speakers is taking a moment — tap Refresh to try again."
          : typeof detail === "string" && !detail.trim().startsWith("<")
          ? detail
          : "Search failed. Tap Refresh to try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  // Reload whenever the modal opens with a new query.
  useEffect(() => {
    if (!open || !query) return;
    setResults([]);
    setIndex(0);
    setCorrected(null);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, query]);

  // Keyboard: Esc closes, ←/→ cycles clips (modal only).
  useEffect(() => {
    if (!open || inline) return;
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

  // Word-accurate cues need only a 1s lead-in; interpolated ones get 2s.
  const startSeconds = useMemo(() => {
    if (!current) return 0;
    const lead = current.precise ? 1 : 2;
    return Math.max(0, Math.floor(current.offset_seconds || 0) - lead);
  }, [current]);

  // Clip refused to play (deleted / private / embed disabled): hide it for
  // everyone and move on without the user having to do anything.
  const onUnplayable = (code) => {
    if (!current) return;
    const dead = current.video_id;
    reportUnplayable(dead, code).catch(() => {});
    setResults((rs) => {
      const rest = rs.filter((r) => r.video_id !== dead);
      setIndex((i) => (rest.length ? Math.min(i, rest.length - 1) : 0));
      if (!rest.length) setError("Those clips are no longer available. Tap Refresh to search again.");
      return rest;
    });
  };

  // Any member: flag this clip for Katherine to review (offensive, wrong
  // speaker, wrong word…). The clip is skipped locally right away.
  const [reporting, setReporting] = useState(false);
  const REPORT_REASONS = ["Offensive language", "Not an American speaker", "Wrong word or timing", "Other"];
  const sendReport = async (reason) => {
    if (!current) return;
    const dead = current.video_id;
    setReporting(false);
    try {
      await reportClip(dead, reason, query);
      toast.success("Thanks — we'll review this clip.");
      setResults((rs) => {
        const rest = rs.filter((r) => r.video_id !== dead);
        setIndex((i) => (rest.length ? Math.min(i, rest.length - 1) : 0));
        return rest;
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not send report.");
    }
  };

  // Admin: this speaker isn't General American — hide the clip for everyone.
  const hideForEveryone = async () => {
    if (!current) return;
    const dead = current.video_id;
    try {
      await adminHideVideo(dead, `Hidden from Real Speakers for "${query}"`);
      toast.success("Clip hidden for everyone.");
      setResults((rs) => {
        const rest = rs.filter((r) => r.video_id !== dead);
        setIndex((i) => (rest.length ? Math.min(i, rest.length - 1) : 0));
        return rest;
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not hide clip.");
    }
  };

  if (!open) return null;
  const body = (
      <div
        className={
          inline
            ? "relative w-full bg-surface border thin-rule flex flex-col"
            : "relative w-full max-w-3xl bg-surface border thin-rule shadow-2xl max-h-[95vh] flex flex-col"
        }
        onClick={(e) => e.stopPropagation()}
        data-testid={inline ? "real-speakers-inline" : undefined}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-3 sm:py-4 border-b thin-rule gap-3">
          <div className="min-w-0">
            <div className="font-mono text-[9px] sm:text-[10px] uppercase tracking-[0.22em] sm:tracking-[0.28em] text-muted2">
              {inline ? "Real Speaker Examples" : "Real Speakers · American"}
            </div>
            <div
              className="font-display text-xl sm:text-2xl text-ink mt-0.5 truncate"
              data-testid="caption-search-query"
            >
              {inline ? `Watch Americans say “${query}”` : query}
            </div>
            {corrected ? (
              <div className="font-serif text-xs text-muted2 italic mt-0.5" data-testid="caption-search-corrected">
                Showing results for <span className="not-italic text-ink">{corrected}</span>
              </div>
            ) : null}
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
            {!inline ? (
              <button
                type="button"
                className="text-muted2 hover:text-ink p-1"
                onClick={onClose}
                data-testid="caption-search-close"
                aria-label="Close"
              >
                <X size={20} />
              </button>
            ) : null}
          </div>
        </div>

        {/* Player */}
        <div className="p-4 sm:p-5 bg-surface">
          <div className="aspect-video bg-stage border thin-rule overflow-hidden relative">
            {loading ? (
              <div className="absolute inset-0 flex items-center gap-2 justify-center font-mono text-xs text-muted2">
                <Loader2 size={14} className="animate-spin" /> Searching real
                speakers…
              </div>
            ) : current ? (
              <ClipPlayer
                videoId={current.video_id}
                start={startSeconds}
                title={current.title || query}
                onUnplayable={onUnplayable}
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center p-6 text-center font-serif text-sm text-muted2 italic leading-relaxed">
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

          {/* Caption line where the word is spoken */}
          {current?.snippet ? (
            <p
              className="mt-3 font-serif text-sm sm:text-base text-ink leading-relaxed border-l-2 border-ink/30 pl-3"
              data-testid="caption-search-snippet"
            >
              <span className="font-mono text-[9px] uppercase tracking-[0.22em] text-muted2 block mb-1">
                Said at {formatTime(current.offset_seconds)}
              </span>
              <HighlightedSnippet text={decodeEntities(current.snippet)} query={corrected || query} />
            </p>
          ) : null}

          {/* Footer: report / admin hide + Open on YouTube */}
          {current ? (
            <div className="mt-3 flex justify-between items-center gap-3 flex-wrap">
              <div className="flex items-center gap-4">
                {reporting ? (
                  <div className="flex flex-wrap gap-1.5" data-testid="caption-report-reasons">
                    {REPORT_REASONS.map((r) => (
                      <button key={r} type="button" onClick={() => sendReport(r)}
                        className="font-mono text-[10px] uppercase tracking-[0.18em] px-2 py-1 border thin-rule text-ink hover:bg-ink hover:text-surface"
                        data-testid={`caption-report-reason-${r.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
                        {r}
                      </button>
                    ))}
                    <button type="button" onClick={() => setReporting(false)} className="font-mono text-[10px] uppercase tracking-[0.18em] px-2 py-1 text-muted2 hover:text-ink" data-testid="caption-report-cancel">Cancel</button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setReporting(true)}
                    className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 hover:text-rust inline-flex items-center gap-1.5"
                    data-testid="caption-search-report"
                    title="Flag this clip for review"
                  >
                    <Flag size={11} />
                    Report clip
                  </button>
                )}
                {me?.is_admin && !reporting ? (
                  <button
                    type="button"
                    onClick={hideForEveryone}
                    className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 hover:text-rust inline-flex items-center gap-1.5"
                    data-testid="caption-search-admin-hide"
                    title="Not an American speaker — hide this clip for everyone"
                  >
                    <EyeOff size={11} />
                    Not American · hide
                  </button>
                ) : null}
              </div>
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
  );
  if (inline) return body;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-stage/90 sm:bg-stage/75 sm:backdrop-blur-md p-0 sm:p-4 overflow-y-auto animate-fade-in"
      data-testid="caption-search-modal"
      onClick={onClose}
    >
      {body}
    </div>
  );
}
