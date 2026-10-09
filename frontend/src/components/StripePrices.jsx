import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

const NEEDED = [
  ["accent_coach_monthly", "Monthly $19 (shown on site)"],
  ["accent_coach_yearly", "Annual $190 (shown on site)"],
  ["founding_monthly", "Founding $9 (Kajabi link)"],
  ["founding_yearly", "Founding $90 (Kajabi link)"],
];

// Shows every Stripe price + lookup key so plan wiring problems are visible at a glance.
export default function StripePrices() {
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get("/admin/stripe/prices").then((r) => setD(r.data)).catch((e) => setD({ error: e?.response?.data?.detail || e.message }));
  }, []);

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-stripe-prices">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Stripe · plan wiring</div>
      <h2 className="font-display text-2xl text-ink mb-3">Prices &amp; lookup keys {d?.mode ? <span className="font-mono text-xs text-muted2">({d.mode} mode)</span> : null}</h2>
      {!d ? <p className="font-serif text-sm text-muted2 italic">Loading…</p> : d.error ? (
        <p className="font-serif text-sm text-crimson">Stripe error: {d.error}</p>
      ) : (
        <>
          <ul className="grid gap-1.5 sm:grid-cols-2 mb-5" data-testid="admin-stripe-lookup-status">
            {NEEDED.map(([k, label]) => (
              <li key={k} className="flex items-center gap-2 font-serif text-sm text-ink">
                <span className={"inline-block w-2 h-2 rounded-full " + (d.lookup_ok[k] ? "bg-sage" : "bg-crimson")} />
                <span className="font-mono text-xs">{k}</span>
                <span className="text-muted2">— {label}</span>
                {!d.lookup_ok[k] ? <span className="text-crimson text-xs">missing / inactive</span> : null}
              </li>
            ))}
          </ul>
          <div className="overflow-x-auto">
            <table className="w-full text-left font-serif text-sm">
              <thead className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
                <tr><th className="py-2 pr-3">Product</th><th className="py-2 pr-3">Price</th><th className="py-2 pr-3">Lookup key</th><th className="py-2 pr-3">Price active</th><th className="py-2">Product active</th></tr>
              </thead>
              <tbody>
                {d.prices.map((p) => (
                  <tr key={p.price_id} className={"border-t thin-rule " + (!p.active || !p.product_active ? "text-muted2" : "text-ink")}>
                    <td className="py-2 pr-3">{p.product_name}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">${p.amount} / {p.interval}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{p.lookup_key || <span className="text-muted2">—</span>}</td>
                    <td className="py-2 pr-3">{p.active ? "yes" : "archived"}</td>
                    <td className="py-2">{p.product_active ? "yes" : "archived"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="font-serif text-xs text-muted2 italic mt-4">
            A plan only works when its lookup key sits on a price that is active <em>and</em> whose product is active. Keys are case-sensitive and must have no spaces.
          </p>
        </>
      )}
    </section>
  );
}
