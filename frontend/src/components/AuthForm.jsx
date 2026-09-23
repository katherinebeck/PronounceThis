import React, { useState } from "react";
import { Loader2, Mail, Lock } from "lucide-react";
import { supabase, passwordProblem } from "@/lib/supabase";
import { toast } from "sonner";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const inputCls =
  "w-full bg-paper border thin-rule pl-9 pr-3 py-3 font-serif text-sm text-ink placeholder:text-muted2 focus:outline-none focus:border-rust";

function Field({ icon: Icon, testId, ...props }) {
  return (
    <div className="relative">
      <Icon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
      <input className={inputCls} data-testid={testId} {...props} />
    </div>
  );
}

// mode: "signin" | "signup" | "forgot". onDone(mode) fires after success.
export default function AuthForm({ mode, setMode, onDone, compact = false }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const friendly = (msg = "") => {
    const m = msg.toLowerCase();
    if (m.includes("invalid login")) return "That email and password don't match. Try again or use “Forgot password?”.";
    if (m.includes("already registered") || m.includes("already been registered")) return "An account with this email already exists — sign in instead.";
    if (m.includes("rate limit") || m.includes("too many")) return "Too many attempts — please wait a minute and try again.";
    if (m.includes("password")) return msg;
    return msg || "Something went wrong. Please try again.";
  };

  const submit = async (e) => {
    e.preventDefault();
    const clean = email.trim().toLowerCase();
    if (!EMAIL_RE.test(clean)) return setError("Please enter a valid email address.");
    if (mode !== "forgot") {
      const p = passwordProblem(password);
      if (p) return setError(p);
      if (mode === "signup" && password !== confirm) return setError("Passwords don't match.");
    }
    setError("");
    setBusy(true);
    try {
      if (mode === "forgot") {
        const { error: err } = await supabase.auth.resetPasswordForEmail(clean, { redirectTo: `${window.location.origin}/auth/reset` });
        if (err) throw err;
        setSent(true);
      } else if (mode === "signup") {
        const { error: err } = await supabase.auth.signUp({ email: clean, password });
        if (err) throw err;
        toast.success("Welcome to Pronounce This!");
        onDone?.("signup");
      } else {
        const { error: err } = await supabase.auth.signInWithPassword({ email: clean, password });
        if (err) throw err;
        onDone?.("signin");
      }
    } catch (err) {
      setError(friendly(err?.message));
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <p className="font-serif text-sm text-ink leading-relaxed" data-testid="auth-reset-sent">
        If an account exists for <span className="font-mono text-rust break-all">{email}</span>, a password reset link is on its way.
        Open it on this device to choose a new password.
      </p>
    );
  }

  const cta = mode === "forgot" ? "Send reset link" : mode === "signup" ? "Create my account" : "Sign in";
  return (
    <form onSubmit={submit} className="flex flex-col gap-3" data-testid={`auth-form-${mode}`}>
      <Field icon={Mail} type="email" autoComplete="email" placeholder="you@example.com" value={email}
             onChange={(e) => setEmail(e.target.value)} testId="auth-email" />
      {mode !== "forgot" ? (
        <Field icon={Lock} type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"}
               placeholder={mode === "signup" ? "Choose a password (8+ characters, a letter and a number)" : "Password"}
               value={password} onChange={(e) => setPassword(e.target.value)} testId="auth-password" />
      ) : null}
      {mode === "signup" ? (
        <Field icon={Lock} type="password" autoComplete="new-password" placeholder="Confirm password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} testId="auth-confirm" />
      ) : null}
      {error ? <p className="font-serif text-xs text-crimson" data-testid="auth-error">{error}</p> : null}
      <button type="submit" className="btn-primary w-full justify-center disabled:opacity-60" disabled={busy} data-testid="auth-submit">
        {busy ? <Loader2 size={16} className="animate-spin" /> : cta}
      </button>
      {!compact ? (
        <div className="flex flex-wrap justify-between gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
          {mode === "signin" ? (
            <>
              <button type="button" className="hover:text-ink" onClick={() => setMode("forgot")} data-testid="auth-forgot">Forgot password?</button>
            </>
          ) : (
            <button type="button" className="hover:text-ink" onClick={() => setMode("signin")} data-testid="auth-to-signin">Back to sign in</button>
          )}
        </div>
      ) : null}
    </form>
  );
}
