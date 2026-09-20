import React, { useState } from "react";
import { Mail, Loader2, Check } from "lucide-react";
import { requestMagicLink } from "@/lib/api";
import { toast } from "sonner";

// Compact "try it free" email capture used at the top of the Get Started
// modal. Sends the same magic link as the Sign in modal.
export default function TrialSignupForm() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle");

  const onSubmit = async (e) => {
    e.preventDefault();
    const clean = email.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(clean)) {
      toast.error("Please enter a valid email address.");
      return;
    }
    setStatus("sending");
    try {
      await requestMagicLink(clean);
      setStatus("sent");
    } catch (err) {
      setStatus("idle");
      const detail = err?.response?.data?.detail;
      const msg =
        detail === "disposable_email"
          ? "Temporary or disposable email addresses can't be used. Please use your regular email."
          : detail === "invalid_email"
            ? "That doesn't look like a valid email address."
            : String(detail || err?.message || "Could not send link.");
      toast.error(msg);
    }
  };

  if (status === "sent") {
    return (
      <div className="border thin-rule bg-paper px-4 py-4 flex items-start gap-3" data-testid="trial-signup-sent">
        <Check size={16} className="text-rust mt-0.5 shrink-0" />
        <p className="font-serif text-sm text-ink leading-relaxed">
          We just emailed a sign-in link to <span className="font-mono text-rust break-all">{email}</span>.
          Tap it to start your free trial.
        </p>
      </div>
    );
  }

  return (
    <div data-testid="trial-signup">
      <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-muted2 mb-3">
        New here? Try Pronounce This for free
      </div>
      <form onSubmit={onSubmit} className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2 pointer-events-none" />
          <input
            type="email"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full pl-9 pr-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
            data-testid="trial-email-input"
          />
        </div>
        <button
          type="submit"
          disabled={status === "sending"}
          className="btn-primary justify-center shrink-0"
          data-testid="trial-submit"
        >
          {status === "sending" ? <Loader2 size={14} className="animate-spin" /> : <>Try it free</>}
        </button>
      </form>
      <p className="font-serif text-xs text-muted2 mt-2 leading-snug">
        Get 5 free words + 1 free scene. Just enter your email above.
      </p>
    </div>
  );
}
