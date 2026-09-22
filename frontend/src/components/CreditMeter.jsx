import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

// ElevenLabs credit meter for the Admin page (weekly email + 80% alert come
// from backend/watchdog.py; this is the live view).
export default function CreditMeter() {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    api.get("/admin/credits").then((r) => setStatus(r.data)).catch(() => setStatus({ ok: false, error: "Could not load." }));
  }, []);

  const pct = status?.ok ? Math.min(100, status.pct) : 0;
  const tone = pct >= 80 ? "bg-crimson" : pct >= 60 ? "bg-rust" : "bg-sage";

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-credits">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Audio budget</div>
      <h2 className="font-display text-2xl text-ink mb-4">ElevenLabs credits this cycle</h2>
      {!status ? (
        <p className="font-serif text-sm text-muted2 italic">Checking…</p>
      ) : !status.ok ? (
        <p className="font-serif text-sm text-crimson leading-relaxed" data-testid="admin-credits-error">{status.error}</p>
      ) : (
        <>
          <div className="h-2 w-full bg-elevated border thin-rule overflow-hidden mb-3">
            <div className={`h-full ${tone} transition-[width]`} style={{ width: `${pct}%` }} />
          </div>
          <div className="font-mono text-xs text-ink flex flex-wrap gap-x-6 gap-y-1" data-testid="admin-credits-summary">
            <span>{status.used.toLocaleString()} / {status.limit.toLocaleString()} used ({status.pct}%)</span>
            <span>{status.remaining.toLocaleString()} left ≈ {Math.floor(status.remaining / 2500).toLocaleString()} reader scenes</span>
            <span>Plan: {status.tier}</span>
            {status.resets_at ? <span>Resets {status.resets_at.slice(0, 10)}</span> : null}
          </div>
          <p className="font-serif text-xs text-muted2 italic mt-3">
            You'll get an email at 80% and a summary every Monday. Upgrade before the bar fills or members hear "audio server is busy".
          </p>
        </>
      )}
    </section>
  );
}
