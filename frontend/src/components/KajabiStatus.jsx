import React, { useEffect, useState } from "react";
import { Plug, PlugZap } from "lucide-react";
import { api } from "@/lib/api";

const when = (iso) => (iso ? new Date(iso).toLocaleString() : "never");

// Admin: is Kajabi actually sending us events, and which offers have we seen?
export function KajabiStatus() {
  const [s, setS] = useState(null);

  useEffect(() => {
    api.get("/admin/kajabi/status").then((r) => setS(r.data)).catch(() => setS({ error: true }));
  }, []);

  const connected = Boolean(s?.last_webhook);

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-kajabi-status">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Kajabi · connection</div>
      <h2 className="font-display text-2xl text-ink mb-4 inline-flex items-center gap-3">
        Kajabi
        {s ? (
          <span className={`inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] px-2 py-1 border thin-rule ${connected ? "text-rust" : "text-crimson"}`} data-testid="kajabi-connected">
            {connected ? <PlugZap size={11} /> : <Plug size={11} />}
            {connected ? "receiving events" : "no events yet"}
          </span>
        ) : null}
      </h2>
      {!s ? <p className="font-serif text-sm text-muted2">Checking…</p> : s.error ? (
        <p className="font-serif text-sm text-crimson">Couldn't load Kajabi status.</p>
      ) : (
        <div className="flex flex-col gap-4">
          <p className="font-serif text-sm text-ink leading-relaxed" data-testid="kajabi-last-webhook">
            Last event from Kajabi: <b>{s.last_webhook ? `${s.last_webhook.event} · ${when(s.last_webhook.received_at)}` : "none received"}</b>
            {" · "}{s.webhook_events} event{s.webhook_events === 1 ? "" : "s"} total
            {" · "}Kajabi API {s.api_credentials ? "connected" : "not configured"}.
          </p>
          {s.offers?.length ? (
            <table className="w-full text-left font-serif text-sm border thin-rule" data-testid="kajabi-offers">
              <thead className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 border-b thin-rule">
                <tr><th className="px-3 py-2">Offer</th><th className="px-3 py-2">Members</th><th className="px-3 py-2">Active</th><th className="px-3 py-2">Last event</th></tr>
              </thead>
              <tbody className="divide-y thin-rule">
                {s.offers.map((o) => (
                  <tr key={o.offer_id} data-testid={`kajabi-offer-${o.offer_id}`}>
                    <td className="px-3 py-2">{o.offer_title} <span className="font-mono text-[10px] text-muted2">#{o.offer_id}</span></td>
                    <td className="px-3 py-2">{o.members}</td>
                    <td className="px-3 py-2">{o.active}</td>
                    <td className="px-3 py-2 text-xs text-muted2">{when(o.last_event_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="font-serif text-sm text-muted2 italic" data-testid="kajabi-offers-empty">
              No offers seen yet. In Kajabi: Settings → Webhooks → add the Purchase webhook pointing at this app (see below), then make a test purchase/grant of your free offer.
            </p>
          )}
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted2">Webhook URL: {window.location.origin}{s.webhook_url_hint}</p>
        </div>
      )}
    </section>
  );
}
