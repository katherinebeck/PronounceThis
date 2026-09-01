import React, { useEffect, useMemo, useRef, useState } from "react";
import { X, ExternalLink, Loader2, Play, RefreshCw } from "lucide-react";
import { captionSearch } from "@/lib/api";
import { toast } from "sonner";

// Formats seconds as m:ss for the "Play at" chip.
function formatTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

// Custom YouGlish replacement: searches our curated allowlist of American
// English YouTube channels for videos where the word is actually spoken,
// and embeds the player at the exact caption timestamp. No third-party
// widget, no Fluently promo, no cross-user history.
export default function CaptionSearchModal({ open, query, onClose }) {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const abortRef = useRef(null);

  const load = async (refresh = false) => {
    if (!query) return;
    // Kill any in-flight request
    if (abortRef.current) abortRef.current.abort?.();
    setLoading(true);
    setError("");
    try {
      const data = await captionSearch(query, { refresh });
      setResults(data.results || []);
      setSelected((data.results || [])[0] || null);
      if (!data.results?.length) {
        setError(
          "No matches from the curated American-speaker channels for that word. Try a variant spelling."
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
    setSelected(null);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, query]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const embedSrc = useMemo(() => {
    if (!selected) return null;
    const start = Math.max(0, Math.floor(selected.offset_seconds || 0));
    // youtube-nocookie.com is more permissive with embeds and doesn't set
    // tracking cookies. `rel=0` avoids unrelated recommendations,
    // `modestbranding` trims logos. Autoplay is off so the iframe doesn't
    // hijack focus in a coaching session.
    const params = new URLSearchParams({
      start: String(start),
      rel: "0",
      modestbranding: "1",
    });
    return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(
      selected.video_id
    )}?${params.toString()}`;
  }, [selected]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4 animate-fade-in"
      data-testid="caption-search-modal"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-5xl bg-surface border thin-rule shadow-2xl max-h-[92vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 py-5 border-b thin-rule">
          <div className="min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
              Real Speakers · American English · Caption Search
            </div>
            <div
              className="font-display text-2xl text-ink mt-1 truncate"
              data-testid="caption-search-query"
            >
              {query}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="btn-secondary !px-3 !py-2"
              onClick={() => load(true)}
              disabled={loading}
              data-testid="caption-search-refresh"
              title="Refresh from YouTube"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              Refresh
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

        <div className="flex-1 min-h-0 grid md:grid-cols-[280px_1fr] gap-px bg-rule">
          {/* Results column */}
          <aside
            className="bg-surface overflow-auto scrollbar-thin min-h-[420px] max-h-[70vh]"
            data-testid="caption-search-results"
          >
            {loading ? (
              <div className="p-8 flex items-center gap-2 font-mono text-xs text-muted2">
                <Loader2 size={14} className="animate-spin" /> Searching real
                speakers…
              </div>
            ) : results.length ? (
              <ul>
                {results.map((r) => {
                  const active = selected?.video_id === r.video_id &&
                    selected?.offset_seconds === r.offset_seconds;
                  const precise = r.has_timestamp;
                  return (
                    <li
                      key={`${r.video_id}-${r.offset_seconds}`}
                      className={
                        "px-5 py-4 border-b thin-rule cursor-pointer transition-colors " +
                        (active ? "bg-paper" : "hover:bg-paper/60")
                      }
                      data-testid={`caption-result-${r.video_id}`}
                      onClick={() => setSelected(r)}
                    >
                      <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 truncate">
                        {r.channel_title}
                      </div>
                      <div
                        className={
                          "font-serif text-sm leading-snug mt-1 line-clamp-2 " +
                          (active ? "text-rust" : "text-ink")
                        }
                        // titles come from YT and may include HTML entities
                        dangerouslySetInnerHTML={{ __html: r.title }}
                      />
                      {r.snippet ? (
                        <div className="font-serif text-xs text-muted2 mt-2 italic line-clamp-2">
                          "{r.snippet}"
                        </div>
                      ) : null}
                      <div className="mt-2 inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                        {precise ? (
                          <>
                            <Play size={10} /> {formatTime(r.offset_seconds)}
                          </>
                        ) : (
                          <span title="Full video — seek to find the word">
                            Full video
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="p-8 font-serif text-sm text-muted2 italic leading-relaxed">
                {error ||
                  "No matches yet. Try Refresh, or use a variant spelling."}
              </div>
            )}
          </aside>

          {/* Player column */}
          <section className="bg-surface p-5 flex flex-col min-h-[420px]">
            {selected ? (
              <>
                <div className="mb-3">
                  <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mb-1">
                    {selected.channel_title}
                    {selected.has_timestamp
                      ? ` · starts at ${formatTime(selected.offset_seconds)}`
                      : " · full video (captions unavailable — seek to find the word)"}
                  </div>
                  <div
                    className="font-display text-lg text-ink leading-snug"
                    dangerouslySetInnerHTML={{ __html: selected.title }}
                  />
                </div>
                <div className="aspect-video bg-ink border thin-rule overflow-hidden">
                  {embedSrc ? (
                    <iframe
                      key={embedSrc}
                      title={selected.title}
                      className="w-full h-full"
                      src={embedSrc}
                      allow="autoplay; encrypted-media; picture-in-picture"
                      allowFullScreen
                      data-testid="caption-search-iframe"
                    />
                  ) : null}
                </div>
                <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
                  <div className="font-serif text-xs text-muted2 italic">
                    {selected.snippet ? `"${selected.snippet}"` : ""}
                  </div>
                  <a
                    className="btn-secondary !px-3 !py-2"
                    href={selected.youtube_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="caption-search-open-external"
                  >
                    <ExternalLink size={12} />
                    Open on YouTube
                  </a>
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center font-mono text-xs text-muted2">
                {loading ? "Loading…" : "Select a clip to play."}
              </div>
            )}
          </section>
        </div>

        <div className="px-6 py-3 border-t thin-rule font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 flex items-center justify-between gap-4 flex-wrap">
          <span>Curated American-speaker channels · captions from YouTube</span>
          <span>{results.length} clip{results.length === 1 ? "" : "s"}</span>
        </div>
      </div>
    </div>
  );
}
