import React from "react";
import { Check, Target, Ear } from "lucide-react";

const BAND_COLOR = { Excellent: "text-sage", Good: "text-sage", "Okay — still needs practice": "text-rust", "Needs work": "text-crimson", "Keep working": "text-crimson" };
const VERDICT = { confirmed: ["✓", "text-sage"], missing: ["✗", "text-crimson"], unsure: ["?", "text-muted2"] };

// Admin-only: raw readout from the phoneme recogniser so the coach can tune it on real voices.
function EarReadout({ ear }) {
  if (!ear) return null;
  return (
    <div className="mx-4 sm:mx-6 mb-4 border border-dashed thin-rule bg-surface px-4 py-3" data-testid="practise-ear">
      <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 inline-flex items-center gap-2"><Ear size={12} /> Sounds heard (admin only) · {ear.status}{ear.error ? ` · ${ear.error}` : ""}</div>
      {ear.heard != null ? <div className="font-mono text-lg text-ink mt-1">{ear.heard || "—"}</div> : null}
      {ear.checks?.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {ear.checks.map((c, i) => {
            const [mark, color] = VERDICT[c.verdict] || VERDICT.unsure;
            return (
              <span key={i} className="font-mono text-xs border thin-rule px-2 py-1 bg-paper inline-flex items-center gap-1.5" title={`expected ${c.p_expected ?? "–"} · other ${c.p_heard ?? "–"}`}>
                /{c.expected}/ <span className={color}>{mark}</span>
                {c.verdict !== "confirmed" && c.heard ? <span className="text-muted2">→ {c.heard}</span> : null}
                <span className="text-muted2/70">{c.p_expected != null ? Math.round(c.p_expected * 100) + "%" : ""}</span>
              </span>
            );
          })}
        </div>
      ) : null}
      {ear.timing?.length ? (
        <div className="mt-2 font-mono text-[11px] text-muted2 flex flex-wrap gap-x-3 gap-y-1" data-testid="practise-ear-timing">
          <span className="uppercase tracking-[0.2em] text-[10px]">Length (yours · Hannah)</span>
          {ear.timing.map((t, i) => (
            <span key={i}>/{t.expected}/ {t.dur.toFixed(2)}s{t.ref != null ? ` · ${t.ref.toFixed(2)}s` : ""}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// Renders the assessment returned by POST /api/practice/assess. Every number
// and phoneme shown here comes straight from the assessment services.
export default function PractiseFeedback({ result }) {
  if (!result) return null;
  if (!result.assessable) {
    return (
      <div className="mt-5 border thin-rule bg-paper px-4 py-4 font-serif text-sm text-ink" data-testid="practise-unassessable">
        {result.reason}
      </div>
    );
  }
  const score10 = result.score10 ?? Math.round((result.score || 0) / 10 * 10) / 10;
  return (
    <div className="mt-5 border thin-rule bg-paper animate-fade-in" data-testid="practise-feedback">
      <div className="px-4 sm:px-6 py-5 border-b thin-rule flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">Pronunciation score</div>
          <div className="font-display font-bold text-5xl sm:text-6xl text-ink leading-none mt-2" data-testid="practise-score">
            {score10}<span className="text-2xl text-muted2">/10</span>
          </div>
        </div>
        <div className="text-right">
          <div className={`font-display font-bold text-xl ${BAND_COLOR[result.band] || "text-ink"}`} data-testid="practise-band">{result.band}</div>
          <div className="font-serif text-sm text-muted2 max-w-xs">{result.summary}</div>
        </div>
      </div>

      <div className="px-4 sm:px-6 py-5 grid gap-5 sm:grid-cols-2">
        <div data-testid="practise-accurate">
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2 inline-flex items-center gap-2"><Check size={12} className="text-sage" /> Sounds you nailed</div>
          {result.accurate?.length ? (
            <div className="flex flex-wrap gap-2">
              {result.accurate.map((p) => (
                <span key={p} className="font-mono text-base text-sage border border-sage/40 px-2.5 py-1 bg-surface">/{p}/</span>
              ))}
            </div>
          ) : <div className="font-serif text-sm text-muted2 italic">None scored as fully accurate yet — keep going.</div>}
        </div>

        <div data-testid="practise-needs-work">
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2 inline-flex items-center gap-2"><Target size={12} className="text-rust" /> Sounds to work on</div>
          {result.needs_work?.length ? (
            <ul className="space-y-3">
              {result.needs_work.map((n) => (
                <li key={n.phoneme} className={`border-l-2 pl-3 ${n.confirmed || n.intrusion ? "border-crimson" : "border-rust"}`}>
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <span className="font-mono text-base text-ink">{n.phoneme.includes(" ") ? n.phoneme : `/${n.phoneme}/`}</span>
                    {n.confirmed ? <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-crimson" data-testid="practise-confirmed">not heard</span>
                      : n.intrusion ? <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-crimson" data-testid="practise-intrusion">extra sound</span>
                      : n.overdone ? <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-rust" data-testid="practise-overdone">held too long</span>
                      : <span className="font-mono text-xs text-muted2">{n.score != null ? `${Math.round(n.score)}/100` : ""}</span>}
                    {n.heard && !n.note ? <span className="font-serif text-xs text-crimson">sounded closer to /{n.heard}/</span> : null}
                  </div>
                  {n.note ? <div className="font-serif text-sm text-crimson mt-1">{n.note}</div> : null}
                  {n.tip ? <div className="font-serif text-sm text-ink/90 mt-1 leading-relaxed">{n.tip}</div> : null}
                </li>
              ))}
            </ul>
          ) : <div className="font-serif text-sm text-muted2 italic">Every sound scored well. Try it again for consistency.</div>}
        </div>
      </div>

      {result.stress && result.stress.verdict !== "unsure" ? (
        <div className={`mx-4 sm:mx-6 mb-4 border-l-2 pl-3 ${result.stress.verdict === "ok" ? "border-sage" : "border-crimson"}`} data-testid="practise-stress">
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">Word stress</div>
          {result.stress.verdict === "ok" ? (
            <div className="font-serif text-sm text-ink mt-1">Stress in the right place: <span className="font-mono text-sage">{result.stress.pattern_expected}</span></div>
          ) : (
            <div className="font-serif text-sm text-crimson mt-1">{result.stress.note}</div>
          )}
        </div>
      ) : null}

      <EarReadout ear={result.ear} />

      <div className="px-4 sm:px-6 pb-4 font-mono text-[10px] text-muted2">
        Heard as “{result.recognized || "—"}” · Automated assessment of American English (en-US). Your recording was not saved.
      </div>
    </div>
  );
}
