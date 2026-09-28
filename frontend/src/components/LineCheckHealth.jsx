import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Is the scene-line "listen back and re-do bad takes" check actually running?
export default function LineCheckHealth() {
  const [s, setS] = useState(null);
  useEffect(() => {
    api.get("/admin/line-checks").then((r) => setS(r.data)).catch(() => setS({ error: true }));
  }, []);

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-line-checks">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Scene lines · quality check</div>
      <h2 className="font-display text-2xl text-ink mb-3">Listen-back check (last 7 days)</h2>
      {!s ? (
        <p className="font-serif text-sm text-muted2 italic">Checking…</p>
      ) : s.error ? (
        <p className="font-serif text-sm text-crimson">Could not load.</p>
      ) : (
        <>
          <p className={"font-serif text-sm leading-relaxed " + (s.stt_key_present ? "text-ink" : "text-crimson")} data-testid="admin-line-checks-key">
            {s.stt_key_present
              ? "Speech-to-text key present — every scene line is transcribed back and re-rendered if a word is wrong."
              : "⚠ No EMERGENT_LLM_KEY in this environment — lines are served unchecked. Add it to Secrets and Republish."}
          </p>
          <div className="font-mono text-xs text-ink flex flex-wrap gap-x-6 gap-y-1 mt-3" data-testid="admin-line-checks-summary">
            <span>{s.total} lines rendered</span>
            <span>{s.verified} verified clean</span>
            <span>{s.retried} needed a re-take</span>
            <span className={s.gave_up ? "text-rust" : ""}>{s.gave_up} still off after retries</span>
            <span className={s.stt_unavailable || s.unchecked ? "text-rust" : ""}>{s.stt_unavailable + s.unchecked} unchecked</span>
          </div>
          {s.recent_gave_up?.length ? (
            <ul className="mt-4 space-y-2" data-testid="admin-line-checks-recent">
              {s.recent_gave_up.map((r, i) => (
                <li key={i} className="font-serif text-xs text-muted2 leading-relaxed border-l-2 border-rust pl-3">
                  <span className="text-ink">“{r.text}”</span><br />
                  heard: “{r.heard}” · {r.renders} takes
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}
