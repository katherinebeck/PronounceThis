import React, { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Kit (ConvertKit) connection check + one-click test tag.
export default function KitStatus() {
  const [status, setStatus] = useState(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  useEffect(() => {
    api.get("/admin/kit/status").then((r) => setStatus(r.data)).catch(() => setStatus({ enabled: false }));
  }, []);

  const test = async () => {
    setBusy(true);
    setResult("");
    try {
      const { data } = await api.post("/admin/kit/test", { email: email.trim() || undefined });
      setResult(`Kit accepted it — ${data.email} now has the tag “${data.tag}”. Check Kit → Subscribers.`);
      toast.success("Kit test tag sent");
    } catch (e) {
      setResult(`Kit refused: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-kit">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Marketing</div>
      <h2 className="font-display text-2xl text-ink mb-3">Kit (ConvertKit) connection</h2>
      {!status ? (
        <p className="font-serif text-sm text-muted2 italic">Checking…</p>
      ) : (
        <>
          <p className="font-serif text-sm text-ink leading-relaxed" data-testid="admin-kit-status">
            {status.enabled
              ? `Key present (starts “${status.key_prefix}…”) — ${status.looks_v4 ? "V4 key ✓" : "⚠ not a V4 key: Kit → Settings → Developer → V4 Keys"}. Tags: ${status.tags.join(", ")}.`
              : "No KIT_API_KEY set in this environment — tagging is off."}
          </p>
          <div className="flex gap-2 mt-4 flex-wrap">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email to tag (defaults to you)"
                   className="flex-1 min-w-[220px] px-3 py-2.5 bg-paper border thin-rule font-serif text-sm text-ink focus:outline-none" data-testid="admin-kit-email" />
            <button type="button" onClick={test} disabled={busy || !status.enabled} className="btn-primary disabled:opacity-50" data-testid="admin-kit-test">
              {busy ? <Loader2 size={14} className="animate-spin" /> : "Send test tag"}
            </button>
          </div>
          {result ? <p className="font-serif text-xs text-ink mt-3" data-testid="admin-kit-result">{result}</p> : null}
        </>
      )}
    </section>
  );
}
