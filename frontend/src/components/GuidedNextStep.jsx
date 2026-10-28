import React from "react";
import { ArrowRight, Lock } from "lucide-react";
import { useAuth } from "@/lib/auth";

// Step-to-step prompts for the guided trial.
// mode "scene": shown under a word result → send them to the sample scene.
// mode "unlock": shown in the sample scene once they've listened → invite to join.
export default function GuidedNextStep({ mode, onGoToScenes, blocked = false }) {
  const { openPaywall } = useAuth();

  if (mode === "scene") {
    return (
      <div className="mt-6 border border-rust/60 bg-surface p-5 sm:p-7 animate-fade-in" data-testid="guided-next-scene">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust">Step 02 of 03</div>
        <h3 className="font-display text-2xl sm:text-3xl text-ink mt-2 leading-tight">
          {blocked ? "That was your free word. Now let's pronounce a scene." : "Nice. Now let's pronounce a scene."}
        </h3>
        <p className="font-serif text-base text-muted2 mt-3 leading-relaxed max-w-2xl">
          Open our sample audition scene, choose your character, tap any word for its pronunciation and listen to the dialogue in a General American accent.
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" onClick={onGoToScenes} data-testid="guided-open-sample-scene">
            Open the sample scene <ArrowRight size={13} />
          </button>
          {blocked ? (
            <button type="button" className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted2 hover:text-ink underline underline-offset-4" onClick={() => openPaywall("unlock")} data-testid="guided-unlock-link">
              or unlock everything now
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-8 border border-rust/60 bg-surface p-5 sm:p-7 animate-fade-in max-w-[78ch]" data-testid="guided-next-unlock">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust">Step 03 of 03</div>
      <h3 className="font-display text-2xl sm:text-3xl text-ink mt-2 leading-tight">Now picture this with your own scene.</h3>
      <p className="font-serif text-base text-muted2 mt-3 leading-relaxed">
        Members upload their audition sides and acting-class scenes with every line transcribed, every word pronounced. Reader's Lines ready to download to use for practice before you film.
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button type="button" className="btn-primary" onClick={() => openPaywall("unlock")} data-testid="guided-unlock-button">
          Unlock Pronounce This <ArrowRight size={13} />
        </button>
        <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
          <Lock size={11} /> Uploads & downloads are member features
        </span>
      </div>
    </div>
  );
}
