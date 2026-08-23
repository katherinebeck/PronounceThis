import React, { useEffect, useMemo, useRef, useState } from "react";
import { X, ExternalLink, Loader2 } from "lucide-react";

// Loads the YouGlish widget script exactly once and resolves when
// `window.YG` is available.
let ygReadyPromise = null;
function loadYouglish() {
  if (ygReadyPromise) return ygReadyPromise;
  ygReadyPromise = new Promise((resolve) => {
    if (typeof window === "undefined") return resolve(null);
    if (window.YG) return resolve(window.YG);
    const prev = window.onYouglishAPIReady;
    window.onYouglishAPIReady = () => {
      if (typeof prev === "function") prev();
      resolve(window.YG);
    };
    const s = document.createElement("script");
    s.src = "https://youglish.com/public/emb/widget.js";
    s.async = true;
    s.charset = "utf-8";
    document.head.appendChild(s);
  });
  return ygReadyPromise;
}

let widgetIdSeq = 0;

/**
 * YouGlish reference modal. Given a word or phrase, embeds YouGlish's
 * American-English pronunciation widget so the actor can hear real speakers
 * saying the name / location.
 */
export default function YouglishModal({ open, query, onClose }) {
  const widgetRef = useRef(null);
  const [loading, setLoading] = useState(true);
  // Generate a fresh mount id per open+query so the mount node exists in the
  // DOM by the time the widget script attaches to it.
  const mountId = useMemo(() => {
    if (!open) return null;
    widgetIdSeq += 1;
    return `yg-mount-${widgetIdSeq}`;
  }, [open, query]);

  useEffect(() => {
    if (!open) setLoading(true);
  }, [open, query]);

  useEffect(() => {
    if (!open || !query || !mountId) return;
    let cancelled = false;
    let observer = null;

    // Hide any Fluently.ai "Check how you say ... in English" panel the
    // YouGlish widget injects. Its wording / branding is unstable across
    // widget versions so we match against a few known strings.
    const stripFluently = (root) => {
      if (!root) return;
      const kill = new Set();
      root.querySelectorAll("*").forEach((el) => {
        const t = (el.textContent || "").toLowerCase();
        if (
          t.includes("check how you say") ||
          t.includes("tap and read the text") ||
          t.includes("fluently")
        ) {
          // Bubble up to the smallest reasonable container that only carries
          // this promo — usually a direct child of the widget mount.
          let node = el;
          for (let i = 0; i < 4 && node.parentElement && node.parentElement !== root; i++) {
            node = node.parentElement;
          }
          kill.add(node);
        }
      });
      kill.forEach((n) => {
        n.style.display = "none";
      });
    };

    (async () => {
      const YG = await loadYouglish();
      if (cancelled || !YG) return;
      const el = document.getElementById(mountId);
      if (!el) return;
      widgetRef.current = new YG.Widget(mountId, {
        width: 720,
        components: 1 + 2 + 4 + 8, // search + video + captions + play controls
        events: {
          onFetchDone: () => {
            setLoading(false);
            stripFluently(el);
          },
        },
      });
      // Watch for the promo re-appearing as the user paginates clips.
      observer = new MutationObserver(() => stripFluently(el));
      observer.observe(el, { childList: true, subtree: true });
      try {
        widgetRef.current.fetch(query, "english", "us");
      } catch {
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (observer) observer.disconnect();
    };
  }, [open, query, mountId]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4 animate-fade-in"
      data-testid="youglish-modal"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl bg-surface border thin-rule shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 py-5 border-b thin-rule">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
              Reference · Real Speakers · YouGlish
            </div>
            <div className="font-display text-2xl text-ink mt-1">{query}</div>
          </div>
          <div className="flex items-center gap-3">
            <a
              className="btn-secondary !px-3 !py-2"
              href={`https://youglish.com/pronounce/${encodeURIComponent(query)}/english/us`}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="youglish-open-external"
            >
              <ExternalLink size={12} />
              Open
            </a>
            <button
              type="button"
              className="text-muted2 hover:text-ink p-1"
              onClick={onClose}
              data-testid="youglish-close"
              aria-label="Close"
            >
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="p-6 min-h-[420px] relative">
          {loading ? (
            <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-muted2 gap-2 pointer-events-none">
              <Loader2 size={14} className="animate-spin" /> Loading real
              speakers…
            </div>
          ) : null}
          {mountId ? <div id={mountId} /> : null}
        </div>
        <div className="px-6 py-3 border-t thin-rule font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
          Clips streamed live from YouTube via YouGlish
        </div>
      </div>
    </div>
  );
}
