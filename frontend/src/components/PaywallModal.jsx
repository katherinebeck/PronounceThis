import React from "react";
import { X, ArrowRight, Lock } from "lucide-react";
import { useAuth } from "@/lib/auth";

// Shown when a trial-gated (or subscriber-only) request comes back 402.
// The subscribe buttons point to the coach's Kajabi checkout URLs (set
// via env). Falls back to a friendly "coming soon" state if URLs aren't
// configured yet.
export default function PaywallModal() {
  const { paywallOpen, closePaywall, paywallReason, me } = useAuth();
  if (!paywallOpen) return null;

  const monthly = me?.monthly_offer_url || "";
  const annual = me?.annual_offer_url || "";
  const portal = me?.member_portal_url || "";
  const configured = !!(monthly || annual);

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

          {configured ? (
            <div className="space-y-3">
              {monthly ? (
                <a
                  href={monthly}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group block border thin-rule bg-paper hover:bg-ink hover:text-surface transition-colors px-5 py-4"
                  data-testid="paywall-monthly"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-muted2 group-hover:text-surface/70">
                        Monthly
                      </div>
                      <div className="font-display text-xl mt-0.5">
                        Start monthly membership
                      </div>
                    </div>
                    <ArrowRight
                      size={18}
                      className="shrink-0 transition-transform group-hover:translate-x-1"
                    />
                  </div>
                </a>
              ) : null}
              {annual ? (
                <a
                  href={annual}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group block border thin-rule bg-ink text-surface hover:bg-rust hover:border-rust transition-colors px-5 py-4"
                  data-testid="paywall-annual"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-surface/70">
                        Annual · Best value
                      </div>
                      <div className="font-display text-xl mt-0.5">
                        Save with annual membership
                      </div>
                    </div>
                    <ArrowRight
                      size={18}
                      className="shrink-0 transition-transform group-hover:translate-x-1"
                    />
                  </div>
                </a>
              ) : null}
            </div>
          ) : (
            <div className="border thin-rule bg-paper px-5 py-6 text-center">
              <Lock size={18} className="text-muted2 mx-auto mb-3" />
              <p className="font-serif text-sm text-ink leading-relaxed">
                Memberships are launching soon. Reach out to your coach to
                request access.
              </p>
            </div>
          )}

          {portal ? (
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 text-center mt-5">
              Already a member?{" "}
              <a
                href={portal}
                target="_blank"
                rel="noopener noreferrer"
                className="text-ink hover:text-rust underline"
                data-testid="paywall-portal-link"
              >
                Open the member portal →
              </a>
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
