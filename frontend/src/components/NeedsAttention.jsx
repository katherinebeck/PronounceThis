import React, { useEffect, useState } from "react";
import { Loader2, AlertTriangle, Ear, BookOpen, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const btn = "font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5 disabled:opacity-60";

// Audio check → Needs attention: listener-flagged words first, then the most
// played words that still have no coach fix. Actions jump to the tools.
export default function NeedsAttention({ onInspect, refreshKey = 0 }) {
  const [d, setD] = useState(null);
  const load = () => api.get("/admin/recording-queue?limit=30").then((r) => setD(r.data)).catch(() => setD({ words: [], error: true }));
  useEffect(() => { load(); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const dismiss = async (w) => {
    try { await api.post("/admin/recording-queue/dismiss", { word: w }); load(); }
    catch { toast.error("Couldn't dismiss"); }
  };
  const editInDictionary = (w) => {
    localStorage.setItem("dict_open_word", w);
    window.location.hash = "dictionary";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  };

  return (
    <div className="border thin-rule bg-paper p-4 mb-6" data-testid="admin-needs-attention">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Needs attention</div>
        {d && !d.error ? <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2" data-testid="admin-needs-attention-count">{d.flagged || 0} flagged · {d.words.length} listed</div> : null}
      </div>
      {!d ? <p className="font-serif text-sm text-muted2 italic inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        : d.error ? <p className="font-serif text-sm text-crimson">Could not load.</p>
        : d.words.length === 0 ? <p className="font-serif text-sm text-muted2 italic" data-testid="admin-needs-attention-empty">Nothing waiting — no flagged words, and nothing heavily played without your fix.</p>
        : (
          <ul className="divide-y thin-rule">
            {d.words.map((w) => (
              <li key={w.word} className="py-2 flex items-center gap-3 flex-wrap" data-testid={`admin-attention-${w.word}`}>
                {w.qa_flag ? <AlertTriangle size={14} className="text-crimson shrink-0" /> : <span className="w-[14px] shrink-0" />}
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="font-display text-lg text-ink">{w.word}</span>
                    <span className="font-mono text-xs text-rust">{w.ipa || ""}</span>
                    <span className="font-serif text-xs text-muted2">played {w.count}×</span>
                  </div>
                  {w.qa_flag ? <div className="font-serif text-xs text-crimson truncate">Flagged{w.qa_heard ? ` — heard “${w.qa_heard}”` : ""}{w.qa_note ? `. ${w.qa_note}` : ""}</div> : null}
                </div>
                <div className="inline-flex gap-2">
                  <button type="button" onClick={() => onInspect?.(w.word)} className={btn} data-testid={`admin-attention-inspect-${w.word}`}><Ear size={11} /> Inspect / audition</button>
                  <button type="button" onClick={() => editInDictionary(w.word)} className={btn} data-testid={`admin-attention-edit-${w.word}`}><BookOpen size={11} /> My Dictionary</button>
                  <button type="button" onClick={() => dismiss(w.word)} className="text-muted2 hover:text-ink p-1.5" title="It's fine — remove from this list" data-testid={`admin-attention-dismiss-${w.word}`}><X size={14} /></button>
                </div>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
