import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";

// App-wide ElevenLabs model switch (Admin → Audio budget).
export default function TtsModelSwitch() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/admin/tts-model").then((r) => setD(r.data)).catch(() => setD({ error: true })); }, []);

  const choose = async (model) => {
    setBusy(true);
    try {
      await api.put("/admin/tts-model", { model });
      setD((p) => ({ ...p, model }));
      toast.success(`Voice model: ${d.options[model]}. Lines re-render on this model the next time they're played.`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not switch model");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-tts-model">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">ElevenLabs · voice model</div>
      <h2 className="font-display text-2xl text-ink mb-3">Which model speaks the lines</h2>
      {!d ? <p className="font-serif text-sm text-muted2 italic">Loading…</p> : d.error ? <p className="font-serif text-sm text-crimson">Could not load.</p> : (
        <>
          <div className="flex flex-wrap gap-2 mb-3">
            {Object.entries(d.options).map(([k, label]) => (
              <button key={k} type="button" disabled={busy} onClick={() => choose(k)}
                className={(d.model === k ? "btn-primary" : "btn-secondary") + " disabled:opacity-50"}
                aria-pressed={d.model === k} data-testid={`admin-tts-model-${k}`}>{label}</button>
            ))}
          </div>
          <p className="font-serif text-sm text-muted2 leading-relaxed">
            <b className="text-ink">Eleven v4</b> keeps one natural voice for the whole line and takes pronunciation corrections as inline IPA — no flatter “turbo” fallback.
            <b className="text-ink"> Multilingual v2</b> is the previous model. Switching re-renders lines on first play (uses characters); switch back any time.
          </p>
        </>
      )}
    </section>
  );
}
