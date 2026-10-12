import React, { useState } from "react";
import { Loader2, Lock } from "lucide-react";
import { supabase, passwordProblem } from "@/lib/supabase";
import { useAuth, AUTH_ERROR_TEXT } from "@/lib/auth";
import { api } from "@/lib/api";

const inputCls =
  "w-full bg-paper border thin-rule pl-9 pr-3 py-3 font-serif text-base text-ink placeholder:text-muted2 focus:outline-none focus:border-rust";

// Right after Stripe Checkout: the paid session proves ownership, so the
// buyer picks a password here and is signed straight in. onExisting() fires
// when the account already has a login (show the sign-in form instead).
export default function CheckoutPasswordForm({ sessionId, email, onExisting }) {
  const { refresh } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    const problem = passwordProblem(password);
    if (problem) return setError(problem);
    if (password !== confirm) return setError("Those passwords don't match.");
    setError("");
    setBusy(true);
    try {
      const { data } = await api.post("/payments/set-password", { session_id: sessionId, password });
      const { error: err } = await supabase.auth.signInWithPassword({ email: data.email, password });
      if (err) throw err;
      const me = await refresh();
      if (me?.auth_error) {
        setError(AUTH_ERROR_TEXT[me.auth_error] || "We couldn't link your account. Please contact support.");
        return;
      }
      window.location.assign("/app");
    } catch (err) {
      const status = err?.response?.status;
      if (status === 409) onExisting?.();
      else if (status === 429) setError("Too many attempts — please wait a minute and try again.");
      else if (status === 410) setError("This checkout link has expired. Use the “set your password” email we sent you, or tap Sign in → Forgot password?");
      else setError("We couldn't save that password. Check your email for the “set your password” link, or try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="checkout-password-form">
      <div className="relative">
        <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
        <input className={inputCls} type="password" autoComplete="new-password" placeholder="Choose a password"
          value={password} onChange={(e) => setPassword(e.target.value)} required
          data-testid="checkout-password-input" />
      </div>
      <div className="relative">
        <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
        <input className={inputCls} type="password" autoComplete="new-password" placeholder="Repeat password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} required
          data-testid="checkout-password-confirm-input" />
      </div>
      <p className="font-serif text-xs text-muted2">At least 8 characters, with a letter and a number. For <span className="text-ink">{email}</span>.</p>
      {error && <p className="font-serif text-sm text-crimson" role="alert" data-testid="checkout-password-error">{error}</p>}
      <button type="submit" disabled={busy} className="btn-primary w-full justify-center disabled:opacity-50"
        data-testid="checkout-password-submit">
        {busy ? <Loader2 size={16} className="animate-spin" /> : "Save password & open the app →"}
      </button>
    </form>
  );
}
