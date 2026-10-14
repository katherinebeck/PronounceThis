import React, { useEffect, useState } from "react";
import { Loader2, BellRing, CheckCircle2, XCircle, Clock } from "lucide-react";
import { api } from "@/lib/api";

const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");

// Admin → Notifications: every owner alert the app tried to send you.
export default function OwnerNotifications() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/admin/notifications").then((r) => setD(r.data)).catch(() => setErr("Could not load."));
  }, []);
  const strip = (s) => (s || "").replace(/<[^>]+>/g, "");

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-notifications">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">System · alerts to you</div>
      <h2 className="font-display text-2xl text-ink mb-1">Owner notifications</h2>
      <p className="font-serif text-sm text-muted2 italic mb-5">
        Every alert the app tried to email you — new trials, new members, cancellations, audio-budget warnings — with whether it was delivered to Resend.
        {d?.to ? <> Sending to <span className="not-italic text-ink" data-testid="admin-notifications-to">{d.to}</span>.</> : null}
      </p>
      {err ? <p className="font-serif text-sm text-crimson">{err}</p>
        : !d ? <p className="font-serif text-sm text-muted2 italic inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        : d.count === 0 ? <p className="font-serif text-sm text-muted2 italic" data-testid="admin-notifications-empty">No notifications logged yet — the next trial sign-up or purchase will appear here.</p>
        : (
          <ul className="divide-y thin-rule border thin-rule bg-paper" data-testid="admin-notifications-list">
            {d.notifications.map((n, i) => (
              <li key={(n.key || "") + (n.sent_at || n.claimed_at) + i} className="px-4 py-2.5 flex items-start gap-3">
                {n.status === "sent" ? <CheckCircle2 size={15} className="text-ink mt-0.5 shrink-0" />
                  : n.status === "failed" ? <XCircle size={15} className="text-crimson mt-0.5 shrink-0" />
                  : <Clock size={15} className="text-muted2 mt-0.5 shrink-0" />}
                <div className="min-w-0 flex-1">
                  <div className="font-serif text-sm text-ink">{n.subject || <span className="text-muted2 italic">pending — {n.key}</span>}</div>
                  {n.lines?.length ? <div className="font-serif text-xs text-muted2 truncate">{strip(n.lines[0])}</div> : null}
                  {n.error ? <div className="font-serif text-xs text-crimson truncate">{n.error}</div> : null}
                </div>
                <span className="font-mono text-[10px] text-muted2 whitespace-nowrap">{when(n.sent_at || n.claimed_at)}</span>
              </li>
            ))}
          </ul>
        )}
      <p className="font-serif text-xs text-muted2 mt-4 inline-flex items-center gap-1.5"><BellRing size={11} /> "New member" fires once per subscription, whichever Stripe event arrives first.</p>
    </section>
  );
}
