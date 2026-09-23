import React, { useEffect, useRef, useState } from "react";
import { Loader2, Check, XCircle } from "lucide-react";
import { verifyMagicLink } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function VerifyPage() {
  const { refresh } = useAuth();
  const [state, setState] = useState("verifying"); // verifying | ok | error
  const [message, setMessage] = useState("");
  const [knownEmail, setKnownEmail] = useState("");
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return; // StrictMode double-invoke guard
    startedRef.current = true;
    (async () => {
      const params = new URLSearchParams(window.location.search);
      const token = params.get("token");
      if (!token) {
        setState("error");
        setMessage("Missing sign-in token.");
        return;
      }
      const isTransient = (err) => {
        const status = err?.response?.status;
        return !status || status >= 500 || status === 429;
      };
      try {
        for (let attempt = 0; ; attempt++) {
          try {
            await verifyMagicLink(token);
            break;
          } catch (err) {
            if (attempt < 3 && isTransient(err)) {
              setMessage("The server took a moment — retrying…");
              await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
              continue;
            }
            throw err;
          }
        }
        await refresh();
        setState("ok");
        // Small pause so the user sees the checkmark before we redirect.
        setTimeout(() => {
          window.history.replaceState({}, "", "/app");
          // Full reload so all components pick up the new auth cookie state.
          window.location.assign("/app");
        }, 900);
      } catch (err) {
        const raw = err?.response?.data?.detail;
        const code = typeof raw === "string" ? raw : raw?.code;
        if (raw?.email) setKnownEmail(raw.email);
        const friendly = {
          invalid_or_used_link: "This sign-in link has already been used too many times.",
          expired_link: "This sign-in link has expired (links last 15 minutes).",
          invalid_link: "This sign-in link isn't valid.",
        };
        const msg = code && friendly[code]
          ? `${friendly[code]} Sign in with your email and password instead — or use “Forgot password?”.`
          : "We couldn't reach the server just now. Please try the link again in a moment, or request a fresh one below.";
        setState("error");
        setMessage(msg);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-paper px-4">
      <div className="w-full max-w-md bg-surface border thin-rule px-8 py-12 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          Pronounce This
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
            {message ? (
              <p className="font-serif text-sm text-muted2 italic mt-2" data-testid="verify-retry-note">{message}</p>
            ) : null}
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
              {message}
            </p>
            <a href="/app" className="btn-primary mt-6 inline-flex" data-testid="verify-signin">Sign in with your password</a>
            <a
              href="/app"
              className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted2 hover:text-ink mt-6 inline-flex"
              data-testid="verify-back"
            >
              Back to Pronounce This
            </a>
          </>
        )}
      </div>
    </div>
  );
}
