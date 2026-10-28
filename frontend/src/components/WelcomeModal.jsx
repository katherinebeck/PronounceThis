import React, { useEffect, useState } from "react";
import { X, ChevronRight, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth";

const STORAGE_KEY = "welcome_seen_v1";

// First-run walkthrough for brand-new signed-in users on the free trial.
// Shows exactly once per browser per user; the "Got it" button dismisses
// permanently. Skipped for members and returning trial users so the modal
// never blocks a paying student.
export default function WelcomeModal() {
  const { me, isAuthenticated, isSubscriber } = useAuth();
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!isAuthenticated || !me?.email) return;
    if (isSubscriber) return;                    // paying members already know the app
    // A truly "fresh" account: hasn't used any trial yet AND hasn't dismissed.
    const notYetUsed =
      (me.trial_word_used || 0) === 0 && (me.trial_scene_used || 0) === 0;
    if (!notYetUsed) return;
    try {
      const seenFor = window.localStorage.getItem(STORAGE_KEY);
      if (seenFor === me.email) return;
    } catch {
      // If localStorage is blocked, still show the modal — worst case is the
      // user sees the walkthrough twice, which is fine.
    }
    setVisible(true);
    setStep(0);
  }, [isAuthenticated, isSubscriber, me?.email, me?.trial_word_used, me?.trial_scene_used]);

  const dismiss = () => {
    try {
      if (me?.email) window.localStorage.setItem(STORAGE_KEY, me.email);
    } catch (e) {
      console.warn("Could not persist welcome-seen flag", e);
    }
    setVisible(false);
  };

  if (!visible) return null;

  const slides = [
    {
      icon: <Sparkles size={20} className="text-rust" />,
      eyebrow: "Welcome",
      title: "You're in!",
      body: (
        <>
          Let's start by looking up a word. Type a word to hear it pronounced for
          you or open <em className="not-italic font-mono text-ink">Real Speakers</em> to
          hear it spoken by an American speaker on YouTube.
        </>
      ),
    },
  ];

  const s = slides[step];
  const isLast = step === slides.length - 1;

  return (
    <div
      className="popup-fonts fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-stage/90 sm:bg-stage/75 sm:backdrop-blur-md p-0 sm:p-4 overflow-y-auto"
      data-testid="welcome-modal"
    >
      <div
        className="relative w-full max-w-md bg-surface border thin-rule shadow-2xl max-h-[92dvh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="absolute top-3 right-3 text-muted2 hover:text-ink p-1 z-10"
          onClick={dismiss}
          data-testid="welcome-close"
          aria-label="Close"
        >
          <X size={18} />
        </button>

        <div className="px-6 py-8 sm:px-8 sm:py-10">
          <div className="inline-flex items-center justify-center w-12 h-12 border thin-rule bg-paper mb-4">
            {s.icon}
          </div>
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
            {s.eyebrow}
          </div>
          <h2 className="font-display text-2xl sm:text-3xl text-ink mt-1 leading-tight">
            {s.title}
          </h2>
          <p className="font-serif text-base text-ink leading-relaxed mt-4">
            {s.body}
          </p>
        </div>

        <div className="flex items-center justify-between px-6 sm:px-8 pb-6">
          {/* progress dots */}
          <div className="flex items-center gap-1.5">
            {slides.map((_, i) => (
              <span
                key={i}
                className={
                  "h-1.5 w-6 border thin-rule " +
                  (i === step ? "bg-ink border-ink" : "bg-transparent")
                }
              />
            ))}
          </div>
          {isLast ? (
            <button
              type="button"
              className="btn-primary !py-2 !px-5"
              onClick={dismiss}
              data-testid="welcome-done"
            >
              Got it
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary !py-2 !px-4 inline-flex items-center gap-1.5"
              onClick={() => setStep((n) => n + 1)}
              data-testid="welcome-next"
            >
              Next
              <ChevronRight size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
