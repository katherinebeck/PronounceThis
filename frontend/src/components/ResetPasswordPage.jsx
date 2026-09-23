import React, { useEffect, useState } from "react";
import { Loader2, Check, Lock } from "lucide-react";
import { supabase, passwordProblem } from "@/lib/supabase";

// /auth/reset — reached from the Supabase reset email (recovery session) or
// from the account menu ("Change password") while signed in.
export default function ResetPasswordPage() {
  const [ready, setReady] = useState(null); // null checking | true | false
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let settled = false;
    const finish = (ok) => { if (!settled) { settled = true; setReady(ok); } };
    const { data } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY" || session) finish(true);
    });
    supabase.auth.getSession().then(({ data: d }) => { if (d?.session) finish(true); });
    const t = setTimeout(() => finish(false), 6000);
    return () => { clearTimeout(t); data.subscription.unsubscribe(); };
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    const p = passwordProblem(pw);
    if (p) return setError(p);
    if (pw !== confirm) return setError("Passwords don't match.");
    setError("");
    setBusy(true);
    const { error: err } = await supabase.auth.updateUser({ password: pw });
    setBusy(false);
    if (err) return setError(err.message);
    setDone(true);
    setTimeout(() => window.location.assign("/app"), 1200);
  };

  const inputCls = "w-full bg-paper border thin-rule pl-9 pr-3 py-3 font-serif text-sm text-ink placeholder:text-muted2 focus:outline-none focus:border-rust";
  return (
    <div className="min-h-screen flex items-center justify-center bg-paper px-4">
      <div className="w-full max-w-md bg-surface border thin-rule px-8 py-10">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 text-center">Pronounce This</div>
        <h1 className="font-display text-2xl text-ink text-center mt-2 mb-6" data-testid="reset-title">Choose a new password</h1>
        {ready === null ? (
          <p className="font-serif text-sm text-muted2 italic text-center"><Loader2 size={14} className="inline animate-spin mr-2" />Checking your link…</p>
        ) : ready === false ? (
          <div className="text-center" data-testid="reset-invalid">
            <p className="font-serif text-sm text-muted2 leading-relaxed">This reset link has expired or already been used. Request a new one from “Forgot password?” on the sign-in screen.</p>
            <a href="/app" className="btn-primary mt-6 inline-flex">Back to Pronounce This</a>
          </div>
        ) : done ? (
          <p className="font-serif text-sm text-ink text-center" data-testid="reset-done"><Check size={16} className="inline text-sage mr-2" />Password updated — taking you in.</p>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3" data-testid="reset-form">
            <div className="relative"><Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
              <input type="password" autoComplete="new-password" className={inputCls} placeholder="New password (8+ characters, a letter and a number)" value={pw} onChange={(e) => setPw(e.target.value)} data-testid="reset-password" /></div>
            <div className="relative"><Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
              <input type="password" autoComplete="new-password" className={inputCls} placeholder="Confirm new password" value={confirm} onChange={(e) => setConfirm(e.target.value)} data-testid="reset-confirm" /></div>
            {error ? <p className="font-serif text-xs text-crimson" data-testid="reset-error">{error}</p> : null}
            <button type="submit" className="btn-primary w-full justify-center disabled:opacity-60" disabled={busy} data-testid="reset-submit">
              {busy ? <Loader2 size={16} className="animate-spin" /> : "Save new password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
