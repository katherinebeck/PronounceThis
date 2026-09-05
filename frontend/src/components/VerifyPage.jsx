import React, { useEffect, useState } from "react";
import { Loader2, Check, XCircle } from "lucide-react";
import { verifyMagicLink } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// Handles /auth/verify?token=xxx. Consumes the magic link, refreshes
// /auth/me so the app-wide auth state flips to authenticated, then
// bounces the user back to the app root.
export default function VerifyPage() {
  const { refresh } = useAuth();
  const [state, setState] = useState("verifying"); // verifying | ok | error
  const [message, setMessage] = useState("");

  useEffect(() => {
    (async () => {
      const params = new URLSearchParams(window.location.search);
      const token = params.get("token");
      if (!token) {
        setState("error");
        setMessage("Missing sign-in token.");
        return;
      }
      try {
        await verifyMagicLink(token);
        await refresh();
        setState("ok");
        // Small pause so the user sees the checkmark before we redirect.
        setTimeout(() => {
          window.history.replaceState({}, "", "/");
          // Full reload so all components pick up the new auth cookie state.
          window.location.assign("/");
        }, 900);
      } catch (err) {
        const msg = err?.response?.data?.detail || err?.message || "Sign-in failed.";
        setState("error");
        setMessage(String(msg));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-paper px-4">
      <div className="w-full max-w-md bg-surface border thin-rule px-8 py-12 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          Accent Coach
        </div>
        {state === "verifying" && (
          <>
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
              <Loader2 size={22} className="animate-spin text-ink" />
            </div>
            <p
              className="font-display text-xl text-ink"
              data-testid="verify-status"
            >
              Signing you in…
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
              data-testid="verify-status"
            >
              You're in — one sec.
            </p>
          </>
        )}
        {state === "error" && (
          <>
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
              <XCircle size={22} className="text-rust" />
            </div>
            <p
              className="font-display text-xl text-ink mb-2"
              data-testid="verify-status"
            >
              Link didn't work
            </p>
            <p className="font-serif text-sm text-muted2 italic leading-relaxed">
              {message}. Sign-in links expire after 15 minutes and can only
              be used once.
            </p>
            <a
              href="/"
              className="btn-primary mt-6 inline-flex"
              data-testid="verify-back"
            >
              Back to Accent Coach
            </a>
          </>
        )}
      </div>
    </div>
  );
}
