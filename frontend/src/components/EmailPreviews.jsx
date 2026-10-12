import React, { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";

const KINDS = [
  { key: "welcome", label: "Welcome (set password)", when: "Sent after a Stripe purchase or admin grant, before first login." },
  { key: "member", label: "Member welcome", when: "Sent to a buyer who already had an account." },
  { key: "nudge", label: "24h nudge", when: "Sent once, 24h+ after the welcome email if they still haven't logged in." },
  { key: "reset", label: "Password reset", when: "Sent from Forgot password?" },
  { key: "no_account", label: "No account", when: "Sent when someone asks for a link under an unknown email." },
];

// Admin → Email previews: the transactional emails rendered exactly as sent.
export default function EmailPreviews() {
  const [kind, setKind] = useState("welcome");
  const [firstName, setFirstName] = useState("Kate");
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setD(null); setErr("");
    api.get(`/admin/email-preview?kind=${kind}&first_name=${encodeURIComponent(firstName)}`)
      .then((r) => setD(r.data)).catch(() => setErr("Could not load preview."));
  }, [kind, firstName]);

  const meta = KINDS.find((k) => k.key === kind);
  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-email-previews">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">System · emails</div>
      <h2 className="font-display text-2xl text-ink mb-1">Email previews</h2>
      <p className="font-serif text-sm text-muted2 italic mb-5">Proofread the copy here — nothing is sent. Buttons in the preview are inert.</p>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {KINDS.map((k) => (
          <button key={k.key} type="button" onClick={() => setKind(k.key)} aria-pressed={kind === k.key}
            className={(kind === k.key ? "btn-primary" : "btn-secondary") + " !py-1.5 !px-3 text-xs"}
            data-testid={`admin-email-kind-${k.key}`}>{k.label}</button>
        ))}
        <label className="ml-auto flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
          First name
          <input value={firstName} onChange={(e) => setFirstName(e.target.value)}
            className="bg-paper border thin-rule px-2 py-1 font-serif text-sm text-ink normal-case tracking-normal w-28"
            data-testid="admin-email-first-name" />
        </label>
      </div>
      <p className="font-serif text-xs text-muted2 mb-3" data-testid="admin-email-when">{meta?.when}</p>
      {err ? <p className="font-serif text-sm text-crimson">{err}</p>
        : !d ? <p className="font-serif text-sm text-muted2 italic inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Rendering…</p>
        : (
          <div className="border thin-rule bg-paper">
            <div className="px-4 py-3 border-b thin-rule font-serif text-sm">
              <div><span className="text-muted2">From:</span> <span className="text-ink">{d.from}</span></div>
              <div><span className="text-muted2">Subject:</span> <span className="text-ink" data-testid="admin-email-subject">{d.subject}</span></div>
            </div>
            <iframe title="Email preview" sandbox="" srcDoc={`<!doctype html><html><body style="margin:0;background:#fff">${d.html}</body></html>`}
              className="w-full bg-white" style={{ height: 620 }} data-testid="admin-email-frame" />
          </div>
        )}
    </section>
  );
}
