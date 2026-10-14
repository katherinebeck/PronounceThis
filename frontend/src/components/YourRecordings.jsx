import React, { useEffect, useState } from "react";
import { Loader2, Play, Trash2, Ear, Check } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { playWord } from "@/lib/audio";

const btn = "font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5 disabled:opacity-60";
const when = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—");

// Audio check → Your recordings: audit every word that plays from a
// recording / chosen take instead of the generated voice.
export default function YourRecordings({ onInspect, refreshKey = 0 }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(null);
  const [checked, setChecked] = useState(() => new Set(JSON.parse(localStorage.getItem("rec_audit_ok") || "[]")));
  const load = () => api.get("/admin/word-audio/recordings").then((r) => setD(r.data)).catch(() => setD({ recordings: [], error: true }));
  useEffect(() => { load(); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const markOk = (w) => {
    const next = new Set(checked); next.has(w) ? next.delete(w) : next.add(w);
    setChecked(next); localStorage.setItem("rec_audit_ok", JSON.stringify([...next]));
  };
  const discard = async (w) => {
    if (!window.confirm(`Discard the recording for “${w}” and go back to the generated voice?`)) return;
    setBusy(w);
    try {
      await api.post("/admin/word-audio/reset", { word: w, drop_recording: true });
      toast.success(`“${w}” now uses the generated voice — re-rendering…`);
      await playWord(w, {});
      load();
    } catch { toast.error("Couldn't discard."); }
    finally { setBusy(null); }
  };

  return (
    <div className="border thin-rule bg-paper p-4 mb-6" data-testid="admin-your-recordings">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Your recordings & chosen takes</div>
        {d && !d.error ? <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2" data-testid="admin-your-recordings-count">{d.count} words · {[...checked].filter((w) => d.recordings.some((r) => r.word === w)).length} checked ok</div> : null}
      </div>
      <p className="font-serif text-xs text-muted2 italic mb-3">These play instead of the generated voice. Tap Play on each; tick the ones that sound right, discard the ones that don't.</p>
      {!d ? <p className="font-serif text-sm text-muted2 italic inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        : d.error ? <p className="font-serif text-sm text-crimson">Could not load.</p>
        : d.count === 0 ? <p className="font-serif text-sm text-muted2 italic" data-testid="admin-your-recordings-empty">No recordings — every word plays from the generated voice.</p>
        : (
          <ul className="divide-y thin-rule">
            {d.recordings.map((r) => (
              <li key={r.word} className={"py-2 flex items-center gap-3 flex-wrap " + (checked.has(r.word) ? "opacity-60" : "")} data-testid={`admin-recording-${r.word}`}>
                <button type="button" onClick={() => playWord(r.word, {})} className={btn} data-testid={`admin-recording-play-${r.word}`}><Play size={11} /> Play</button>
                <div className="min-w-0 flex-1">
                  <span className="font-display text-lg text-ink">{r.word}</span>
                  <span className="font-serif text-xs text-muted2 ml-2">{r.kind} · {when(r.created_at)} · played {r.plays}×</span>
                </div>
                <div className="inline-flex gap-2">
                  <button type="button" onClick={() => markOk(r.word)} aria-pressed={checked.has(r.word)} className={btn + (checked.has(r.word) ? " bg-ink text-surface" : "")} data-testid={`admin-recording-ok-${r.word}`}><Check size={11} /> {checked.has(r.word) ? "Sounds right" : "Mark ok"}</button>
                  <button type="button" onClick={() => onInspect?.(r.word)} className={btn} data-testid={`admin-recording-inspect-${r.word}`}><Ear size={11} /> Audition</button>
                  <button type="button" onClick={() => discard(r.word)} disabled={busy === r.word} className={btn + " text-crimson"} data-testid={`admin-recording-discard-${r.word}`}>
                    {busy === r.word ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />} Discard
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
