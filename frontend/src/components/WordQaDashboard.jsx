import React, { useEffect, useState } from "react";
import { Loader2, ShieldCheck, ShieldAlert, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import WordAudioInspector from "./WordAudioInspector";

const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");
const pct = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : "—");

// Admin → Word audio QA: how the AI listener is doing, week by week.
export default function WordQaDashboard() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/admin/word-qa?weeks=8").then((r) => setD(r.data)).catch(() => setErr("Could not load."));
  }, []);

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-word-qa">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Pronunciation · audio check</div>
      <h2 className="font-display text-2xl text-ink mb-1">Word audio QA</h2>
      <p className="font-serif text-sm text-muted2 italic mb-2">Every first-time word render is heard by the AI listener. Flagged words go to the top of your Recording queue.</p>
      {d?.judge ? (
        <p className={"font-mono text-[10px] uppercase tracking-[0.2em] mb-5 " + (d.judge.configured && d.judge.ok !== false ? "text-muted2" : "text-crimson")} data-testid="admin-word-qa-judge">
          Listener: {!d.judge.configured ? "not configured (EMERGENT_LLM_KEY missing) — words play unchecked"
            : d.judge.ok === null ? "ready, no checks yet since restart"
            : d.judge.ok ? `ok · last check ${new Date(d.judge.at).toLocaleTimeString()}`
            : `unavailable — ${d.judge.error}`}
        </p>
      ) : null}
      {err ? <p className="font-serif text-sm text-crimson">{err}</p>
        : !d ? <p className="font-serif text-sm text-muted2 italic inline-flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6" data-testid="admin-word-qa-totals">
              {[
                ["Checked", d.total.checked, null],
                ["Passed", d.total.passed, pct(d.total.passed, d.total.checked)],
                ["Flagged", d.total.flagged, pct(d.total.flagged, d.total.checked)],
                ["Retakes", d.total.retakes, pct(d.total.retakes, d.total.checked)],
              ].map(([label, n, sub]) => (
                <div key={label} className="border thin-rule bg-paper px-4 py-3">
                  <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">{label}</div>
                  <div className="font-display text-3xl text-ink leading-none mt-1">{n}</div>
                  {sub ? <div className="font-serif text-xs text-muted2 mt-1">{sub}</div> : null}
                </div>
              ))}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mb-2">Last {d.weeks} weeks</div>
            {d.weekly.length === 0 ? <p className="font-serif text-sm text-muted2 italic mb-6" data-testid="admin-word-qa-empty">No checked words yet — the first new word a student clicks will show up here.</p> : (
              <div className="overflow-x-auto mb-6">
                <table className="w-full text-sm" data-testid="admin-word-qa-weekly">
                  <thead><tr className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 text-left border-b thin-rule">
                    <th className="py-2 pr-4">Week</th><th className="py-2 pr-4">Checked</th><th className="py-2 pr-4">Passed</th><th className="py-2 pr-4">Flagged</th><th className="py-2 pr-4">Retakes</th><th className="py-2">Avg naturalness</th>
                  </tr></thead>
                  <tbody>{d.weekly.map((w) => (
                    <tr key={w.week} className="border-b thin-rule font-serif">
                      <td className="py-2 pr-4 font-mono text-xs text-ink">{w.week}</td>
                      <td className="py-2 pr-4">{w.checked}</td>
                      <td className="py-2 pr-4 text-ink">{w.passed} <span className="text-muted2 text-xs">({pct(w.passed, w.checked)})</span></td>
                      <td className={"py-2 pr-4 " + (w.flagged ? "text-crimson" : "text-muted2")}>{w.flagged}</td>
                      <td className="py-2 pr-4">{w.retakes}</td>
                      <td className="py-2">{w.avg_natural ?? "—"} / 10</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mb-2">Recent verdicts</div>
            <ul className="divide-y thin-rule border thin-rule bg-paper" data-testid="admin-word-qa-recent">
              {d.recent.length === 0 ? <li className="px-4 py-3 font-serif text-sm text-muted2 italic">Nothing yet.</li> : d.recent.map((r) => (
                <li key={r.word + r.at} className="px-4 py-2.5 flex items-start gap-3" data-testid={`admin-word-qa-row-${r.word}`}>
                  {r.ok ? <ShieldCheck size={15} className="text-ink mt-0.5 shrink-0" /> : <ShieldAlert size={15} className="text-crimson mt-0.5 shrink-0" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="font-display text-lg text-ink">{r.word}</span>
                      <span className="font-serif text-xs text-muted2">heard “{r.heard || "—"}” · {r.natural ?? "—"}/10</span>
                      {r.takes > 1 ? <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted2"><RotateCcw size={10} /> retake</span> : null}
                    </div>
                    {r.note ? <div className="font-serif text-xs text-muted2 truncate">{r.note}</div> : null}
                  </div>
                  <span className="font-mono text-[10px] text-muted2 whitespace-nowrap">{when(r.at)}</span>
                </li>
              ))}
            </ul>
            <WordAudioInspector />
          </>
        )}
    </section>
  );
}
