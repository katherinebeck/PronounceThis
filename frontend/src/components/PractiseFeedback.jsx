import React from "react";
import { Check, Target } from "lucide-react";

const BAND_COLOR = { Excellent: "text-sage", Good: "text-sage", "Getting there": "text-rust", "Keep working": "text-crimson" };

// Renders the assessment returned by POST /api/practice/assess. Every number
// and phoneme shown here comes straight from the assessment service.
export default function PractiseFeedback({ result }) {
  if (!result) return null;
  if (!result.assessable) {
    return (
      <div className="mt-5 border thin-rule bg-paper px-4 py-4 font-serif text-sm text-ink" data-testid="practise-unassessable">
        {result.reason}
      </div>
    );
  }
  return (
    <div className="mt-5 border thin-rule bg-paper animate-fade-in" data-testid="practise-feedback">
      <div className="px-4 sm:px-6 py-5 border-b thin-rule flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">Pronunciation score</div>
          <div className="font-display font-bold text-5xl sm:text-6xl text-ink leading-none mt-2" data-testid="practise-score">
            {result.score}<span className="text-2xl text-muted2">/100</span>
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
                <li key={n.phoneme} className="border-l-2 border-rust pl-3">
                  <div className="flex items-baseline gap-3 flex-wrap">
                    <span className="font-mono text-base text-ink">/{n.phoneme}/</span>
                    <span className="font-mono text-xs text-muted2">{n.score != null ? `${Math.round(n.score)}/100` : ""}</span>
                    {n.heard ? <span className="font-serif text-xs text-crimson">sounded closer to /{n.heard}/</span> : null}
                  </div>
                  {n.tip ? <div className="font-serif text-sm text-ink/90 mt-1 leading-relaxed">{n.tip}</div> : null}
                </li>
              ))}
            </ul>
          ) : <div className="font-serif text-sm text-muted2 italic">Every sound scored well. Try it again for consistency.</div>}
        </div>
      </div>

      <div className="px-4 sm:px-6 pb-4 font-mono text-[10px] text-muted2">
        Heard as “{result.recognized || "—"}” · Automated assessment of American English (en-US). Your recording was not saved.
      </div>
    </div>
  );
}
