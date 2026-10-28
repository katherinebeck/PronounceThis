import React from "react";
import { Check, ArrowRight } from "lucide-react";
import { useAuth } from "@/lib/auth";

const STEPS = [
  { n: "01", label: "Check one word", hint: "Hear it the American way" },
  { n: "02", label: "Try a scene", hint: "Pick a character, hear the lines" },
  { n: "03", label: "Unlock Pronounce This", hint: "Bring your own scripts" },
];

// Three-step guided trial strip for new free-trial accounts.
export default function GuidedTrialBar({ tab, onGoToWord, onGoToScenes }) {
  const { isGuidedTrial, guidedStep, guidedDone, openPaywall } = useAuth();
  if (!isGuidedTrial) return null;

  const go = (i) => {
    if (i === 0) onGoToWord?.();
    else if (i === 1) onGoToScenes?.();
    else openPaywall("unlock");
  };

  return (
    <div className="border-b thin-rule bg-stage" data-testid="guided-trial-bar">
      <ol className="max-w-6xl mx-auto px-4 sm:px-8 grid grid-cols-3">
        {STEPS.map((s, i) => {
          const stepNo = i + 1;
          const done = stepNo === 1 ? guidedDone.word : stepNo === 2 ? guidedDone.scene : false;
          const current = guidedStep === stepNo;
          const onTab = (stepNo === 1 && tab === "pronounce") || (stepNo === 2 && tab === "scenes");
          return (
            <li key={s.n} className={"relative " + (i < 2 ? "border-r thin-rule" : "")}>
              <button
                type="button"
                onClick={() => go(i)}
                className={
                  "w-full text-left px-3 sm:px-5 py-3 sm:py-3.5 flex items-center gap-3 transition-colors hover:bg-surface/60 " +
                  (current || onTab ? "bg-surface/40" : "")
                }
                data-testid={`guided-step-${stepNo}`}
                aria-current={current ? "step" : undefined}
              >
                <span
                  className={
                    "shrink-0 w-7 h-7 border flex items-center justify-center font-mono text-[10px] tracking-[0.2em] " +
                    (done
                      ? "bg-rust border-rust text-stage"
                      : current
                      ? "border-rust text-rust"
                      : "border-ink/30 text-muted2")
                  }
                >
                  {done ? <Check size={12} strokeWidth={3} /> : s.n}
                </span>
                <span className="min-w-0">
                  <span className={"block font-display text-sm sm:text-base leading-tight truncate " + (done || current ? "text-ink" : "text-muted2")}>
                    {s.label}
                  </span>
                  <span className="hidden sm:block font-mono text-[10px] uppercase tracking-[0.18em] text-muted2 truncate">
                    {done ? "Done" : s.hint}
                  </span>
                </span>
                {current && stepNo < 3 ? <ArrowRight size={12} className="ml-auto text-rust hidden sm:block" /> : null}
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
