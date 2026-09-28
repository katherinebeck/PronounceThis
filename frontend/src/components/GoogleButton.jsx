import React, { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

let providersPromise = null;
// Supabase's public settings endpoint tells us which social providers are on,
// so the button only appears once Google is configured in the dashboard.
function loadProviders() {
  if (!providersPromise) {
    providersPromise = fetch(`${process.env.REACT_APP_SUPABASE_URL}/auth/v1/settings`, {
      headers: { apikey: process.env.REACT_APP_SUPABASE_ANON_KEY },
    })
      .then((r) => (r.ok ? r.json() : {}))
      .then((j) => j?.external || {})
      .catch(() => ({}));
  }
  return providersPromise;
}

export default function GoogleButton({ onError }) {
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { loadProviders().then((ext) => setEnabled(Boolean(ext.google))); }, []);
  if (!enabled) return null;

  const go = async () => {
    setBusy(true);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/app` },
    });
    if (error) { setBusy(false); onError?.(error.message); }
  };

  return (
    <>
      <button type="button" onClick={go} disabled={busy}
        className="w-full justify-center inline-flex items-center gap-3 border thin-rule bg-surface px-4 py-3 font-mono text-[13px] uppercase tracking-[0.16em] text-ink hover:bg-paper transition-colors disabled:opacity-60"
        data-testid="auth-google">
        <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden="true">
          <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.8 6C12.3 13.2 17.7 9.5 24 9.5z" />
          <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-2.8-.4-4H24v8.1h12.7c-.3 2.2-1.7 5.4-4.8 7.6l7.4 5.7c4.4-4.1 7.2-10.1 7.2-17.4z" />
          <path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.8-6A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.8-6z" />
          <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.4-5.7c-2 1.4-4.7 2.4-8.5 2.4-6.3 0-11.7-3.7-13.6-9.2l-7.8 6C6.5 42.6 14.6 48 24 48z" />
        </svg>
        Continue with Google
      </button>
      <div className="flex items-center gap-3 font-mono text-xs uppercase tracking-[0.16em] text-muted2">
        <span className="flex-1 border-t thin-rule" /> or with email <span className="flex-1 border-t thin-rule" />
      </div>
    </>
  );
}
