import React, { useEffect, useState } from "react";
import { ArrowRight, Lock, X } from "lucide-react";
import { useAuth } from "@/lib/auth";

const COPY = {
  scene: {
    step: "Step 02 of 03",
    title: "Nice. Now let's pronounce a scene.",
    titleBlocked: "That was your free word. Now let's pronounce a scene.",
    body: "Open our sample audition scene, choose your character, tap any word for its pronunciation and listen to the dialogue in a General American accent.",
    cta: "Open the sample scene",
  },
  unlock: {
    step: "Step 03 of 03",
    title: "Now picture this with your own scene.",
    body: "Members upload their audition sides and acting-class scenes with every line transcribed, every word pronounced. Reader's Lines ready to download to use for practice before you film.",
    cta: "Unlock Pronounce This",
  },
};

// Step-to-step prompts for the guided trial.
// mode "scene": under a word result → send them to the sample scene.
// mode "unlock": in the scene library once they've listened → invite to join.
export default function GuidedNextStep({ mode, onGoToScenes, blocked = false, compact = false }) {
  const { openPaywall } = useAuth();
  const c = COPY[mode];
  const act = () => (mode === "scene" ? onGoToScenes?.() : openPaywall("unlock"));

  return (
    <div
      className={"border border-rust/60 bg-surface animate-fade-in " + (compact ? "p-4" : "mt-6 p-5 sm:p-7")}
      data-testid={mode === "scene" ? "guided-next-scene" : "guided-next-unlock"}
    >
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust">{c.step}</div>
      <h3 className={"font-display text-ink mt-2 leading-tight " + (compact ? "text-xl" : "text-2xl sm:text-3xl")}>
        {blocked && c.titleBlocked ? c.titleBlocked : c.title}
      </h3>
      <p className={"font-serif text-muted2 mt-3 leading-relaxed " + (compact ? "text-sm" : "text-base max-w-2xl")}>{c.body}</p>
      <div className={"mt-5 flex flex-wrap items-center gap-3 " + (compact ? "flex-col items-stretch" : "")}>
        <button
          type="button"
          className={"btn-primary " + (compact ? "justify-center" : "")}
          onClick={act}
          data-testid={mode === "scene" ? "guided-open-sample-scene" : "guided-unlock-button"}
        >
          {c.cta} <ArrowRight size={13} />
        </button>
        {mode === "scene" && blocked ? (
          <button type="button" className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted2 hover:text-ink underline underline-offset-4" onClick={() => openPaywall("unlock")} data-testid="guided-unlock-link">
            or unlock everything now
          </button>
        ) : null}
        {mode === "unlock" ? (
          <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
            <Lock size={11} /> Uploads & downloads are member features
          </span>
        ) : null}
      </div>
    </div>
  );
}

// Timed nudge: slides in from the corner after `delayMs` while `active`, once per mode per session.
export function GuidedPopup({ mode, active, delayMs, onGoToScenes }) {
  const { openPaywall } = useAuth();
  const [open, setOpen] = useState(false);
  const key = `guided_popup_${mode}`;

  useEffect(() => {
    if (!active) return undefined;
    if (window.sessionStorage.getItem(key)) return undefined;
    const t = setTimeout(() => {
      setOpen(true);
      window.sessionStorage.setItem(key, "1");
    }, delayMs);
    return () => clearTimeout(t);
  }, [active, delayMs, key]);

  if (!open || !active) return null;
  const c = COPY[mode];
  const act = () => {
    setOpen(false);
    if (mode === "scene") onGoToScenes?.();
    else openPaywall("unlock");
  };

  return (
    <div
      className="fixed z-40 inset-x-3 bottom-3 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-[380px] bg-ink text-stage p-5 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.8)] animate-fade-in"
      role="dialog"
      aria-live="polite"
      data-testid={`guided-popup-${mode}`}
    >
      <button type="button" className="absolute top-3 right-3 text-stage/60 hover:text-stage p-1" onClick={() => setOpen(false)} aria-label="Dismiss" data-testid="guided-popup-close">
        <X size={16} />
      </button>
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust">{c.step}</div>
      <h3 className="font-display text-xl mt-1.5 leading-tight pr-6">{c.title}</h3>
      <p className="font-serif text-sm text-stage/80 mt-2 leading-relaxed">{c.body}</p>
      <button type="button" className="btn-primary mt-4 w-full justify-center" onClick={act} data-testid={`guided-popup-${mode}-cta`}>
        {c.cta} <ArrowRight size={13} />
      </button>
    </div>
  );
}
