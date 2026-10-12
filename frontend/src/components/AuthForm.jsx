import React, { useState } from "react";
import { Loader2, Mail, Lock } from "lucide-react";
import { supabase, passwordProblem } from "@/lib/supabase";
import { useAuth, AUTH_ERROR_TEXT } from "@/lib/auth";
import { api } from "@/lib/api";
import { toast } from "sonner";
import ResetSentStatus from "./ResetSentStatus";
import GoogleButton from "./GoogleButton";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const inputCls =
  "w-full bg-paper border thin-rule pl-9 pr-3 py-3 font-serif text-base text-ink placeholder:text-muted2 focus:outline-none focus:border-rust";

function Field({ icon: Icon, testId, ...props }) {
  return (
    <div className="relative">
      <Icon size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
      <input className={inputCls} data-testid={testId} {...props} />
    </div>
  );
}

// mode: "signin" | "signup" | "forgot". onDone(mode) fires after success.
export default function AuthForm({ mode, setMode, onDone, compact = false, ctaLabel }) {
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(null);

  const friendly = (msg = "") => {
    const m = msg.toLowerCase();
    if (m.includes("invalid login")) return "That email and password don't match. Try again or use “Forgot password?”.";
    if (m.includes("already registered") || m.includes("already been registered")) return "You already have an account with this email — use Sign in, or tap “Forgot password?” and we'll email you a link to set one.";
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
        const { data } = await api.post("/auth/password-link", { email: clean });
        setSent(data);
      } else {
        const { error: err } = mode === "signup"
          ? await supabase.auth.signUp({ email: clean, password })
          : await supabase.auth.signInWithPassword({ email: clean, password });
        if (err) throw err;
        // Confirm the backend actually recognises this login before closing.
        const me = await refresh();
        if (me?.auth_error) {
          setError(AUTH_ERROR_TEXT[me.auth_error] || "We couldn't link your account. Please contact support.");
          return;
        }
        if (mode === "signup") toast.success("Welcome to Pronounce This!");
        onDone?.(mode);
      }
    } catch (err) {
      if (err?.response?.status === 429) setError("Too many attempts — please wait a minute and try again.");
      else if (err?.response?.status === 503) setError("We couldn't send the email right now. Please try again in a moment or contact support.");
      else setError(friendly(err?.message));
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return <ResetSentStatus email={sent.to || email.trim().toLowerCase()} initial={sent} />;
  }

  const cta = ctaLabel || (mode === "forgot" ? "Send reset link" : mode === "signup" ? "Create my account" : "Sign in");
  return (
    <form onSubmit={submit} className="flex flex-col gap-3" data-testid={`auth-form-${mode}`}>
      {mode !== "forgot" ? <GoogleButton onError={(m) => setError(m)} /> : null}
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
      {error ? <p className="font-serif text-sm text-crimson" data-testid="auth-error">{error}</p> : null}
      <button type="submit" className="btn-primary btn-lg w-full justify-center disabled:opacity-60" disabled={busy} data-testid="auth-submit">
        {busy ? <Loader2 size={16} className="animate-spin" /> : cta}
      </button>
      {!compact ? (
        <div className="flex flex-wrap justify-between gap-2 font-mono text-xs uppercase tracking-[0.16em] text-muted2">
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
