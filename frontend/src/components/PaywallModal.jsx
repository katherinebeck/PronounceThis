import React, { useState, useEffect } from "react";
import { X, ArrowRight, Loader2, Sparkles, Check } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { createStripeCheckout } from "@/lib/api";
import TrialSignupForm from "./TrialSignupForm";
import { toast } from "sonner";

const UNLOCKS = [
  "Upload your own scripts — audition sides, self-tapes, acting-class scenes",
  "Unlimited words — American IPA, audio and Real Speaker clips",
  "Hear every line of your scene in a General American accent",
  "Download your Reader's Lines audio to run lines before a self-tape",
];

// What a trial user has just tasted, shown the moment the free trial runs out.
function TrialOverPitch({ reason }) {
  return (
    <div className="mb-6" data-testid="paywall-trial-over">
      <p className="font-serif text-base text-ink leading-relaxed">
        {reason === "unlock"
          ? "You've checked a word and worked a scene. Members do exactly this with their own audition sides, self-tape scripts and acting-class scenes — for every audition:"
          : reason === "scene"
          ? "You've seen how your own scene sounds in a General American accent. Members get this for every audition:"
          : "You've heard how it sounds when it's right. Members get this for every word and every audition:"}
      </p>
      <ul className="mt-4 space-y-2.5">
        {UNLOCKS.map((line) => (
          <li key={line} className="flex items-start gap-3 font-serif text-sm text-ink leading-snug">
            <Check size={14} className="text-rust shrink-0 mt-0.5" />
            <span>{line}</span>
          </li>
        ))}
      </ul>
      <figure className="mt-5 border-l-2 border-rust pl-4" data-testid="paywall-testimonial">
        <blockquote className="font-serif text-sm text-ink italic leading-relaxed">
          "This is amazing!! It's unlike anything else I've come across before and I think will be extremely useful for future US auditions."
        </blockquote>
        <figcaption className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-1.5">— Greg</figcaption>
      </figure>
    </div>
  );
}

// Shown when a trial-gated (or subscriber-only) request comes back 402.
// The subscribe buttons open Stripe Checkout for the selected plan.
const FALLBACK_PRICES = [
  { lookup_key: "accent_coach_monthly", label: "Monthly", amount: 19, currency: "usd", interval: "month" },
  { lookup_key: "accent_coach_yearly", label: "Annual", amount: 190, currency: "usd", interval: "year", savings_note: "Save $38 vs monthly" },
];

export default function PaywallModal() {
  const { paywallOpen, closePaywall, openPaywall, openLogin, paywallReason, me } = useAuth();

  useEffect(() => {
    if (!paywallOpen) return undefined;
    const onKey = (e) => { if (e.key === "Escape") closePaywall(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paywallOpen, closePaywall]);
  const [loading, setLoading] = useState(null); // lookup_key currently checking-out
  if (!paywallOpen) return null;

  const prices = Array.isArray(me?.stripe_prices) && me.stripe_prices.length
    ? me.stripe_prices
    : FALLBACK_PRICES;

  const startCheckout = async (lookup_key) => {
    setLoading(lookup_key);
    try {
      const { checkout_url } = await createStripeCheckout(lookup_key);
      // Redirect the whole page to Stripe. On return, /payment/success
      // handles the state flip.
      window.location.href = checkout_url;
    } catch (err) {
      setLoading(null);
      const detail = err?.response?.data?.detail;
      const friendly = String(detail || "").startsWith("unknown_price")
        ? "That plan is temporarily unavailable. Please try the other plan or contact support."
        : null;
      toast.error(
        detail === "not_authenticated"
          ? "Please sign in first."
          : friendly || String(detail || err?.message || "Could not start checkout")
      );
    }
  };

  const trialOnly = paywallReason === "trial" && !me?.email;
  const showTrial = trialOnly;
  const trialOver = paywallReason === "word" || paywallReason === "scene" || paywallReason === "unlock";
  const oneWord = (me?.trial_word_limit ?? 2) === 1;
  const headline = trialOnly
    ? "New here? Try it for free"
    : paywallReason === "unlock"
    ? "Bring your own scripts."
    : trialOver
    ? (paywallReason === "scene" ? "That was your free scene." : oneWord ? "That was your free word." : "That was your 2 free words.")
    : "Join Pronounce This";

  const usedNote =
    paywallReason === "scene"
      ? "You've used your free scene upload. "
      : paywallReason === "word"
      ? "You've used your 2 free words. "
      : paywallReason === "practice"
      ? "You've used your free pronunciation check for this word. Members get unlimited practice. "
      : paywallReason === "subscription"
      ? "This is a members-only feature. "
      : "";
  const subhead =
    usedNote +
    "Choose monthly or join annual (get 2 months free). Pay securely with Stripe, then sign in with your email and password.";

  return (
    <div
      className="popup-fonts fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-stage/90 sm:bg-stage/75 sm:backdrop-blur-md p-0 sm:p-4 overflow-y-auto"
      data-testid="paywall-modal"
      onClick={closePaywall}
    >
      <div
        className="theme-light relative w-full max-w-lg bg-surface border thin-rule shadow-2xl max-h-[92dvh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b thin-rule">
          <div>
            <div className="font-display text-2xl text-ink">
              {headline}
            </div>
          </div>
          <button
            type="button"
            className="text-muted2 hover:text-ink p-1"
            onClick={closePaywall}
            data-testid="paywall-close"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-6">
          {showTrial ? (
            <div>
              <TrialSignupForm />
            </div>
          ) : null}
          {trialOnly ? (
            <p className="font-serif text-sm text-muted2 italic mt-4 leading-relaxed" data-testid="paywall-trial-footer">
              Already a member?{" "}
              <button type="button" className="text-ink not-italic underline underline-offset-2 hover:text-rust" onClick={() => { closePaywall(); openLogin(); }} data-testid="paywall-trial-signin">Sign in</button>.
              {" "}Want unlimited access?{" "}
              <button type="button" className="text-ink not-italic underline underline-offset-2 hover:text-rust" onClick={() => openPaywall("join")} data-testid="paywall-trial-join">Join Pronounce This</button>.
            </p>
          ) : null}
          {trialOver ? (
            <TrialOverPitch reason={paywallReason} />
          ) : !trialOnly ? (
          <p className="font-serif text-base text-ink leading-relaxed mb-6">
            {subhead}
          </p>
          ) : null}

          <div className={trialOnly ? "hidden" : "space-y-3"}>
            {prices.map((p) => {
              const isAnnual = p.interval === "year";
              return (
                <button
                  key={p.lookup_key}
                  type="button"
                  onClick={() => startCheckout(p.lookup_key)}
                  disabled={loading !== null}
                  className={
                    "group block w-full text-left border thin-rule px-5 py-4 transition-colors disabled:opacity-60 " +
                    (isAnnual
                      ? "bg-ink text-surface hover:bg-rust hover:border-rust"
                      : "bg-paper hover:bg-ink hover:text-surface")
                  }
                  data-testid={`paywall-${p.lookup_key}`}
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className={
                        "font-mono text-xs uppercase tracking-[0.18em] " +
                        (isAnnual
                          ? "text-surface/70"
                          : "text-muted2 group-hover:text-surface/70")
                      }>
                        {isAnnual && trialOver ? "Most popular · 2 months free" : p.label}
                        {p.savings_note && !(isAnnual && trialOver) ? ` · ${p.savings_note}` : ""}
                      </div>
                      <div className="font-display text-xl mt-0.5">
                        {isAnnual ? "Save with annual · " : "Start monthly · "}
                        <span className="font-mono not-italic tabular-nums">
                          ${p.amount}
                        </span>
                        <span className={
                          "font-mono text-sm ml-0.5 " +
                          (isAnnual
                            ? "text-surface/70"
                            : "text-muted2 group-hover:text-surface/70")
                        }>
                          /{p.interval === "year" ? "yr" : "mo"}
                        </span>
                      </div>
                    </div>
                    {loading === p.lookup_key ? (
                      <Loader2 size={18} className="animate-spin shrink-0" />
                    ) : (
                      <ArrowRight
                        size={18}
                        className="shrink-0 transition-transform group-hover:translate-x-1"
                      />
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {!trialOnly ? (
          <div className="mt-5 flex items-center justify-center gap-1.5 text-muted2">
            <Sparkles size={11} />
            <p className="font-mono text-xs uppercase tracking-[0.16em]">
              Cancel anytime. Secure checkout by Stripe.
            </p>
          </div>
          ) : null}
          {!trialOnly && !trialOver ? (
            <p className="font-serif text-sm text-muted2 mt-4 text-center leading-relaxed" data-testid="paywall-spam-note">
              Don't see our email? Check your spam or junk folder.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
