import React, { useEffect, useState } from "react";
import Logo from "./Logo";
import { Loader2, Check, XCircle, Mail } from "lucide-react";
import { getPaymentStatus } from "@/lib/api";
import AuthForm from "./AuthForm";
import { useAuth } from "@/lib/auth";

// Landing spot after a Stripe Checkout completes. Polls until we see
// payment_status=paid, then bounces the user home with a refreshed
// auth state so their account chip flips to "Member".
export default function PaymentSuccessPage() {
  const { refresh } = useAuth();
  const [state, setState] = useState("checking"); // checking | ok | link | failed | timeout
  const [tries, setTries] = useState(0);
  const [email, setEmail] = useState("");

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
            setTimeout(() => window.location.assign("/app"), 1500);
          } else {
            setEmail(s.email || "");
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
        <div className="flex justify-center"><Logo className="h-5" /></div>
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
              Payment received. Create your password.
            </p>
            <p className="font-serif text-sm text-muted2 italic mt-3 mb-5 leading-relaxed">
              Use the same email you paid with —{" "}
              <span className="not-italic text-ink" data-testid="payment-success-email">{email || "your checkout email"}</span>{" "}
              — so your membership is attached to your account.
            </p>
            <div className="text-left">
              <AuthForm mode="signup" setMode={() => {}} compact onDone={() => window.location.assign("/app")} />
            </div>
            <p className="font-serif text-xs text-muted2 mt-4">Already have an account? <a href="/app" className="text-ink underline">Sign in</a>.</p>
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
