import React, { useState } from "react";
import { X, ArrowRight, Loader2, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { createStripeCheckout } from "@/lib/api";
import { toast } from "sonner";

// Shown when a trial-gated (or subscriber-only) request comes back 402.
// The subscribe buttons open Stripe Checkout for the selected plan.
export default function PaywallModal() {
  const { paywallOpen, closePaywall, paywallReason, me } = useAuth();
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

  const headline =
    paywallReason === "scene"
      ? "You've used your free scene"
      : paywallReason === "word"
      ? "You've used your free word"
      : "Members only";

  const subhead =
    paywallReason === "scene"
      ? "Upload another audition scene, generate line-by-line audio, and download an actor's lines as one MP3 — all with a membership."
      : paywallReason === "word"
      ? "Hear as many words as you like, drill sound categories, and unlock Real-Speaker video clips with a membership."
      : "This is a members-only feature. Join to unlock everything.";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4"
      data-testid="paywall-modal"
      onClick={closePaywall}
    >
      <div
        className="relative w-full max-w-lg bg-surface border thin-rule shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b thin-rule">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
              Membership
            </div>
            <div className="font-display text-2xl text-ink mt-0.5">
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
          <p className="font-serif text-base text-ink leading-relaxed mb-6">
            {subhead}
          </p>

          <div className="space-y-3">
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

          <div className="mt-5 flex items-center justify-center gap-1.5 text-muted2">
            <Sparkles size={11} />
            <p className="font-mono text-[10px] uppercase tracking-[0.22em]">
              Cancel anytime. Secure checkout by Stripe.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
