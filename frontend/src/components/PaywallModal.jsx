import React, { useState, useEffect } from "react";
import { X, ArrowRight, Loader2, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { createStripeCheckout } from "@/lib/api";
import TrialSignupForm from "./TrialSignupForm";
import { toast } from "sonner";

// Shown when a trial-gated (or subscriber-only) request comes back 402.
// The subscribe buttons open Stripe Checkout for the selected plan.
export default function PaywallModal() {
  const { paywallOpen, closePaywall, paywallReason, me } = useAuth();

  useEffect(() => {
    if (!paywallOpen) return undefined;
    const onKey = (e) => { if (e.key === "Escape") closePaywall(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paywallOpen, closePaywall]);
  const [loading, setLoading] = useState(null); // lookup_key currently checking-out
  if (!paywallOpen) return null;

  const prices = Array.isArray(me?.stripe_prices) ? me.stripe_prices : [];

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
      toast.error(
        detail === "not_authenticated"
          ? "Please sign in first."
          : String(detail || err?.message || "Could not start checkout")
      );
    }
  };

  const trialOnly = paywallReason === "trial" && !me?.email;
  const showTrial = (paywallReason === "join" || trialOnly) && !me?.email;
  const headline =
    showTrial
      ? "Try it free"
      : paywallReason === "join"
      ? "Join Pronounce This"
      : paywallReason === "scene"
      ? "You've used your free scene"
      : paywallReason === "word"
      ? "You've used your 5 free words"
      : "Members only";

  const subhead =
    paywallReason === "join"
      ? "Choose monthly or join annual (get 2 months free). A one-tap sign-in link lands in your inbox right after — no password, ever."
      : paywallReason === "scene"
      ? "Upload another audition scene, generate line-by-line audio, and download an actor's lines as one MP3 — all with a membership."
      : paywallReason === "word"
      ? "Hear as many words as you like, drill sound categories, and unlock Real-Speaker video clips with a membership."
      : "This is a members-only feature. Join to unlock everything.";

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-stage/90 sm:bg-stage/75 sm:backdrop-blur-md p-0 sm:p-4 overflow-y-auto"
      data-testid="paywall-modal"
      onClick={closePaywall}
    >
      <div
        className="relative w-full max-w-lg bg-surface border thin-rule shadow-2xl max-h-[92dvh] overflow-y-auto"
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
            <div className={trialOnly ? "" : "mb-6 pb-6 border-b thin-rule"}>
              <TrialSignupForm />
            </div>
          ) : null}
          {trialOnly ? (
            <p className="font-serif text-xs text-muted2 italic mt-4" data-testid="paywall-trial-footer">
              Already a member? Use <span className="text-ink not-italic">Sign in</span> at the top.
              Want unlimited access? Tap <span className="text-ink not-italic">Get Started</span>.
            </p>
          ) : null}
          {showTrial && !trialOnly ? (
            <div className="font-display text-2xl text-ink mb-3" data-testid="paywall-join-heading">
              Join Pronounce This
            </div>
          ) : null}
          {!trialOnly ? (
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
                        "font-mono text-[10px] uppercase tracking-[0.24em] " +
                        (isAnnual
                          ? "text-surface/70"
                          : "text-muted2 group-hover:text-surface/70")
                      }>
                        {p.label}
                        {p.savings_note ? ` · ${p.savings_note}` : ""}
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
            <p className="font-mono text-[10px] uppercase tracking-[0.22em]">
              Cancel anytime. Secure checkout by Stripe.
            </p>
          </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
