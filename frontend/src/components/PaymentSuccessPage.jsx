import React, { useEffect, useState } from "react";
import { Loader2, Check, XCircle, Mail } from "lucide-react";
import { getPaymentStatus, requestMagicLink } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Landing spot after a Stripe Checkout completes. Polls until we see
// payment_status=paid, then bounces the user home with a refreshed
// auth state so their account chip flips to "Member".
export default function PaymentSuccessPage() {
  const { refresh } = useAuth();
  const [state, setState] = useState("checking"); // checking | ok | link | failed | timeout
  const [tries, setTries] = useState(0);
  const [email, setEmail] = useState("");
  const [resent, setResent] = useState(false);
  const [canResend, setCanResend] = useState(false);

  useEffect(() => {
    if (state !== "link") return undefined;
    const t = setTimeout(() => setCanResend(true), 60000);
    return () => clearTimeout(t);
  }, [state]);

  const sendLink = async (to) => {
    try { await requestMagicLink(to); } catch { /* silent: rate-limited or transient */ }
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("session_id");
    if (!sid) {
      setState("failed");
      return;
    }
    let cancelled = false;
    let attempt = 0;

    const tick = async () => {
      attempt += 1;
      setTries(attempt);
      try {
        const s = await getPaymentStatus(sid);
        if (cancelled) return;
        if (s.payment_status === "paid") {
          const me = await refresh();
          if (me?.authenticated) {
            setState("ok");
            setTimeout(() => window.location.assign("/"), 1500);
          } else {
            setEmail(s.email || "");
            if (s.email) await sendLink(s.email);
            setState("link");
          }
          return;
        }
        if (attempt >= 15) {
          setState("timeout");
          return;
        }
        setTimeout(tick, 2000);
      } catch {
        if (cancelled) return;
        if (attempt >= 15) {
          setState("timeout");
          return;
        }
        setTimeout(tick, 2000);
      }
    };
    tick();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-paper flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-surface border thin-rule px-8 py-12 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          Pronounce This
        </div>
        {state === "checking" && (
          <>
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
              <Loader2 size={22} className="animate-spin text-ink" />
            </div>
            <p
              className="font-display text-xl text-ink"
              data-testid="payment-success-status"
            >
              Confirming your payment…
            </p>
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-3">
              Attempt {tries} of 15
            </p>
          </>
        )}
        {state === "ok" && (
          <>
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
              <Check size={22} className="text-rust" />
            </div>
            <p
              className="font-display text-xl text-ink"
              data-testid="payment-success-status"
            >
              You're a member. Welcome in.
            </p>
            <p className="font-serif text-sm text-muted2 italic mt-2">
              Redirecting…
            </p>
          </>
        )}
        {state === "link" && (
          <>
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
              <Mail size={22} className="text-rust" />
            </div>
            <p className="font-display text-xl text-ink" data-testid="payment-success-status">
              Payment received. Check your inbox.
            </p>
            <p className="font-serif text-sm text-muted2 italic mt-3 leading-relaxed">
              We've emailed a one-tap sign-in link to{" "}
              <span className="not-italic text-ink" data-testid="payment-success-email">{email || "your email"}</span>.
              Open it on any device to start using Pronounce This — no password needed.
            </p>
            <button
              type="button"
              disabled={resent || !email || !canResend}
              onClick={async () => { await sendLink(email); setResent(true); }}
              className="btn-secondary mt-6 disabled:opacity-50"
              data-testid="payment-success-resend"
            >
              {resent ? "Link sent again" : canResend ? "Resend the link" : "Not there yet? Resend available in a minute"}
            </button>
          </>
        )}
        {(state === "failed" || state === "timeout") && (
          <>
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
              <XCircle size={22} className="text-rust" />
            </div>
            <p
              className="font-display text-xl text-ink mb-2"
              data-testid="payment-success-status"
            >
              We're still waiting on Stripe
            </p>
            <p className="font-serif text-sm text-muted2 italic leading-relaxed">
              Your card may have been charged. If your account isn't upgraded
              in a minute, refresh the app or check the account menu.
            </p>
            <a
              href="/app"
              className="btn-primary mt-6 inline-flex"
              data-testid="payment-success-home"
            >
              Back to Pronounce This
            </a>
          </>
        )}
      </div>
    </div>
  );
}
