import React, { useState, useRef, useEffect } from "react";
import { User, LogOut, CreditCard, ExternalLink, ChevronDown, Loader2, Mail, Sparkles, ArrowRight } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { createStripePortal } from "@/lib/api";
import { toast } from "sonner";
import SupportModal from "./SupportModal";

// Header account chip: shows "Sign in" for anonymous users, or a small
// menu with email + status + logout for logged-in users.
export default function AccountChip() {
  const { me, isAuthenticated, isSubscriber, openLogin, openPaywall, logout,
          trialWordRemaining, trialSceneRemaining } = useAuth();
  const [open, setOpen] = useState(false);
  const [supportOpen, setSupportOpen] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (!ref.current?.contains(e.target)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (!isAuthenticated) {
    return (
      <div className="flex items-center gap-2" data-testid="header-auth-actions">
        <button
          type="button"
          onClick={openLogin}
          className="font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.22em] px-3 sm:px-4 py-2 sm:py-2.5 rounded-full border thin-rule text-ink hover:border-ink transition-colors"
          data-testid="header-signin"
        >
          Sign in
        </button>
        <button
          type="button"
          onClick={() => openPaywall("join")}
          className="font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.22em] px-4 sm:px-5 py-2 sm:py-2.5 rounded-full bg-rust text-stage font-semibold hover:bg-rustDeep transition-colors"
          data-testid="header-get-started"
        >
          Join Pronounce This
        </button>
      </div>
    );
  }

  // Only members granted access outside Stripe (group-coaching / admin grants)
  // see the Kajabi coaching library link; free-trial users never do.
  const portal = isSubscriber && !me?.has_stripe_customer ? me?.member_portal_url : null;
  const status = isSubscriber
    ? (me?.subscription_offer_title || "Member")
    : "Free trial";

  const openStripePortal = async () => {
    setPortalLoading(true);
    try {
      const { url } = await createStripePortal();
      window.location.href = url;
    } catch (err) {
      setPortalLoading(false);
      toast.error(err?.response?.data?.detail || "Could not open the billing portal");
    }
  };
  // Members who paid via Stripe get the Stripe Customer Portal (cancel /
  // change card / upgrade). Members granted via Kajabi / admin panel don't
  // have a Stripe customer — they see the Kajabi library link (if set)
  // or no manage-billing button at all.
  const canOpenStripePortal = !!me?.has_stripe_customer;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.22em] px-3 sm:px-4 py-2 sm:py-2.5 border thin-rule hover:bg-paper transition-colors"
        data-testid="header-account"
      >
        <User size={12} />
        <span className="hidden sm:inline max-w-[140px] truncate">
          {me?.email}
        </span>
        <ChevronDown size={12} className={open ? "rotate-180 transition-transform" : "transition-transform"} />
      </button>

      {open ? (
        <div
          className="absolute right-0 top-full mt-1 w-72 bg-surface border thin-rule shadow-xl z-40"
          data-testid="account-menu"
        >
          <div className="px-4 py-3 border-b thin-rule">
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
              Signed in as
            </div>
            <div className="font-serif text-sm text-ink truncate mt-0.5">
              {me?.email}
            </div>
          </div>
          <div className="px-4 py-3 border-b thin-rule">
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
              Status
            </div>
            <div className={"font-display text-lg mt-0.5 " + (isSubscriber ? "text-rust" : "text-ink")}>
              {status}
            </div>
            {!isSubscriber ? (
              <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-2">
                {trialWordRemaining} {trialWordRemaining === 1 ? "word" : "words"} · {trialSceneRemaining} scene left
              </div>
            ) : null}
          </div>

          {!isSubscriber ? (
            <button
              type="button"
              onClick={() => { setOpen(false); openPaywall("join"); }}
              className="flex items-center justify-between gap-2 w-full px-4 py-3 bg-rust/10 hover:bg-rust/20 transition-colors border-b thin-rule text-left"
              data-testid="account-join"
            >
              <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-ink font-semibold">
                <Sparkles size={12} className="text-rust" />
                Join Pronounce This
              </span>
              <ArrowRight size={12} className="text-rust" />
            </button>
          ) : null}

          {canOpenStripePortal ? (
            <button
              type="button"
              onClick={openStripePortal}
              disabled={portalLoading}
              className="flex items-center justify-between gap-2 w-full px-4 py-3 hover:bg-paper transition-colors border-b thin-rule text-left"
              data-testid="account-manage-stripe"
            >
              <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-ink">
                <CreditCard size={12} />
                Manage subscription
              </span>
              {portalLoading ? (
                <Loader2 size={12} className="animate-spin text-muted2" />
              ) : (
                <ExternalLink size={12} className="text-muted2" />
              )}
            </button>
          ) : portal ? (
            <a
              href={portal}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between gap-2 px-4 py-3 hover:bg-paper transition-colors border-b thin-rule"
              data-testid="account-manage"
            >
              <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em] text-ink">
                <CreditCard size={12} />
                Coaching library
              </span>
              <ExternalLink size={12} className="text-muted2" />
            </a>
          ) : null}

          <button
            type="button"
            onClick={() => { setOpen(false); setSupportOpen(true); }}
            className="flex items-center gap-2 w-full px-4 py-3 hover:bg-paper transition-colors font-mono text-[11px] uppercase tracking-[0.22em] text-ink text-left border-b thin-rule"
            data-testid="account-support"
          >
            <Mail size={12} />
            Contact support
          </button>

          <a
            href="/auth/reset"
            className="block w-full text-left px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.18em] text-ink hover:bg-elevated"
            data-testid="account-change-password"
          >
            Change password
          </a>
          <button
            type="button"
            onClick={async () => {
              setOpen(false);
              await logout();
            }}
            className="flex items-center gap-2 w-full px-4 py-3 hover:bg-paper transition-colors font-mono text-[11px] uppercase tracking-[0.22em] text-ink text-left"
            data-testid="account-logout"
          >
            <LogOut size={12} />
            Sign out
          </button>
        </div>
      ) : null}
      <SupportModal open={supportOpen} onClose={() => setSupportOpen(false)} />
    </div>
  );
}
