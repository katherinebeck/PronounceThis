import React, { useEffect, useState } from "react";
import { Loader2, KeyRound, Clock, Link2, Mail, Check, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const RANGES = [{ days: 1, label: "Today" }, { days: 7, label: "7 days" }, { days: 30, label: "30 days" }];
const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");
const btn = "font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5 disabled:opacity-60";

// Admin → New buyers: who paid recently and whether they've made it inside yet.
export default function NewBuyers() {
  const [days, setDays] = useState(1);
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const [copied, setCopied] = useState(null);

  const load = (n = days) => api.get(`/admin/buyers?days=${n}`).then((r) => setD(r.data)).catch(() => setD({ error: true }));
  useEffect(() => { setD(null); load(days); }, [days]); // eslint-disable-line react-hooks/exhaustive-deps

  const copyLink = async (email) => {
    try {
      const res = await api.post("/admin/password-link", { email });
      await navigator.clipboard.writeText(res.data.link);
      setCopied(email);
      toast.success("Set-password link copied");
      setTimeout(() => setCopied((c) => (c === email ? null : c)), 1800);
    } catch (e) { toast.error(e?.response?.data?.detail || "Couldn't create link"); }
  };
  const resend = async (email) => {
    setBusy(email);
    try {
      await api.post("/admin/password-link/send", { email });
      toast.success(`Set-password email sent to ${email}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Couldn't send email"); }
    finally { setBusy(null); }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-new-buyers">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-4">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Members · new buyers</div>
          <h2 className="font-display text-2xl text-ink">Who paid, and who's made it inside</h2>
          {d && !d.error ? (
            <p className="font-serif text-sm text-muted2 italic mt-1" data-testid="admin-buyers-summary">
              {d.count} buyer{d.count === 1 ? "" : "s"} · {d.signed_in} signed in · {d.count - d.signed_in} still at the door
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {RANGES.map((r) => (
            <button key={r.days} type="button" onClick={() => setDays(r.days)} aria-pressed={days === r.days}
              className={(days === r.days ? "btn-primary" : "btn-secondary") + " !py-1.5 !px-3 text-xs"}
              data-testid={`admin-buyers-range-${r.days}`}>{r.label}</button>
          ))}
          <button type="button" onClick={() => load()} className={btn} title="Refresh" data-testid="admin-buyers-refresh"><RefreshCw size={11} /></button>
        </div>
      </div>
      {!d ? <p className="font-serif text-sm text-muted2 italic inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        : d.error ? <p className="font-serif text-sm text-crimson">Could not load.</p>
        : d.count === 0 ? <p className="font-serif text-sm text-muted2 italic" data-testid="admin-buyers-empty">No Stripe purchases in this window.</p>
        : (
          <div className="overflow-x-auto -mx-6 px-6">
            <table className="w-full text-sm">
              <thead>
                <tr className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 text-left border-b thin-rule">
                  <th className="py-2 pr-4">Buyer</th><th className="py-2 pr-4">Plan</th><th className="py-2 pr-4">Paid</th><th className="py-2 pr-4">Signed in</th><th className="py-2 text-right">Follow up</th>
                </tr>
              </thead>
              <tbody>
                {d.buyers.map((b) => (
                  <tr key={b.email} className="border-b thin-rule align-top" data-testid={`admin-buyer-${b.email}`}>
                    <td className="py-3 pr-4 font-serif text-ink">{b.email}</td>
                    <td className="py-3 pr-4 text-xs text-muted2">{b.plan || "—"}</td>
                    <td className="py-3 pr-4 text-xs text-muted2 whitespace-nowrap">{when(b.bought_at)}</td>
                    <td className="py-3 pr-4 text-xs whitespace-nowrap">
                      {b.signed_in ? (
                        <span className="inline-flex items-center gap-1.5 text-ink" data-testid={`admin-buyer-status-${b.email}`}><KeyRound size={11} className="text-rust" />Yes · {when(b.last_login_at)}</span>
                      ) : (
                        <span className="inline-flex flex-col gap-0.5 text-crimson" data-testid={`admin-buyer-status-${b.email}`}>
                          <span className="inline-flex items-center gap-1.5"><Clock size={11} />Not yet</span>
                          {b.last_auth_email ? <span className="text-muted2">{b.last_auth_email.kind} email {b.last_auth_email.status} · {when(b.last_auth_email.sent_at)}</span> : <span className="text-muted2">no email sent yet</span>}
                        </span>
                      )}
                    </td>
                    <td className="py-3 text-right whitespace-nowrap">
                      {!b.signed_in ? (
                        <div className="inline-flex gap-2">
                          <button type="button" onClick={() => copyLink(b.email)} className={btn} data-testid={`admin-buyer-copy-${b.email}`}>
                            {copied === b.email ? <><Check size={11} />Copied</> : <><Link2 size={11} />Password link</>}
                          </button>
                          <button type="button" onClick={() => resend(b.email)} disabled={busy === b.email} className={btn} data-testid={`admin-buyer-resend-${b.email}`}>
                            {busy === b.email ? <Loader2 size={11} className="animate-spin" /> : <Mail size={11} />}Resend email
                          </button>
                        </div>
                      ) : <span className="text-xs text-muted2">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </section>
  );
}
