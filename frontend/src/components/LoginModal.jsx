import React, { useState } from "react";
import { X, Mail, Loader2, Check } from "lucide-react";
import { requestMagicLink } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";

// Passwordless email login. User types email → we email a one-tap link →
// they click it → they're in. Zero passwords.
export default function LoginModal() {
  const { loginOpen, closeLogin } = useAuth();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | sending | sent | error
  const [error, setError] = useState("");

  if (!loginOpen) return null;

  const onSubmit = async (e) => {
    e.preventDefault();
    const clean = email.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(clean)) {
      setError("Please enter a valid email address.");
      return;
    }
    setError("");
    setStatus("sending");
    try {
      await requestMagicLink(clean);
      setStatus("sent");
    } catch (err) {
      setStatus("error");
      const detail = err?.response?.data?.detail;
      let msg;
      if (detail === "email_delivery_pending_domain_verification") {
        msg =
          "We're still verifying our email domain — right now sign-in links only work for the app owner. Please email support to get a comp account while we finish setup.";
      } else if (detail === "email_send_failed") {
        msg =
          "Couldn't send the sign-in email right now. Please try again in a minute, or contact support if it persists.";
      } else if (detail === "invalid_email") {
        msg = "That doesn't look like a valid email address.";
      } else {
        msg = detail || err?.message || "Could not send link.";
      }
      setError(String(msg));
      toast.error(String(msg));
    }
  };

  const reset = () => {
    setStatus("idle");
    setEmail("");
    setError("");
    closeLogin();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4"
      data-testid="login-modal"
      onClick={reset}
    >
      <div
        className="relative w-full max-w-md bg-surface border thin-rule shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b thin-rule">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
              Accent Prep
            </div>
            <div className="font-display text-2xl text-ink mt-0.5">
              {status === "sent" ? "Check your email" : "Sign in"}
            </div>
          </div>
          <button
            type="button"
            className="text-muted2 hover:text-ink p-1"
            onClick={reset}
            data-testid="login-close"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        {status === "sent" ? (
          <div className="px-6 py-8 text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule mb-4 bg-paper">
              <Check size={22} className="text-rust" />
            </div>
            <p className="font-serif text-base text-ink leading-relaxed">
              We just emailed a sign-in link to
            </p>
            <p className="font-mono text-sm text-rust mt-1 break-all">{email}</p>
            <p className="font-serif text-sm text-muted2 italic mt-4 leading-relaxed">
              Tap the button in that email to sign in. The link is good for
              15 minutes.
            </p>
            <button
              type="button"
              className="btn-secondary mt-6 !px-4 !py-2"
              onClick={reset}
              data-testid="login-done"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="px-6 py-6">
            <p className="font-serif text-sm text-muted2 leading-relaxed mb-5">
              Enter your email and we'll send a one-tap sign-in link. No
              passwords to remember.
            </p>

            <label
              htmlFor="login-email"
              className="font-mono text-[10px] uppercase tracking-[0.24em] text-muted2 block mb-2"
            >
              Email address
            </label>
            <div className="relative">
              <Mail
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2 pointer-events-none"
              />
              <input
                id="login-email"
                type="email"
                inputMode="email"
                autoComplete="email"
                autoFocus
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full pl-9 pr-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
                data-testid="login-email-input"
              />
            </div>

            {error ? (
              <p className="font-mono text-[11px] text-rust mt-2">{error}</p>
            ) : null}

            <button
              type="submit"
              disabled={status === "sending"}
              className="btn-primary w-full mt-5 justify-center"
              data-testid="login-submit"
            >
              {status === "sending" ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Sending link…
                </>
              ) : (
                <>Send me a sign-in link</>
              )}
            </button>

            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-5 text-center">
              New here? Get 1 free word + 1 free scene on us.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
