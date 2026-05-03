import React, { useMemo, useState } from "react";
import WordBlock from "./WordBlock";

export default function SceneReader({ scene, highlightSet }) {
  const [activeIdx, setActiveIdx] = useState(null);

  const stats = useMemo(() => {
    const words = (scene?.tokens || []).filter((t) => t.is_word);
    const transcribed = words.filter((w) => w.ipa).length;
    return { total: words.length, transcribed };
  }, [scene]);

  if (!scene) return null;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-paper">
      <div className="px-10 lg:px-16 pt-10 pb-6 border-b thin-rule">
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2">
          The Scene
        </div>
        <h1
          className="font-display text-4xl lg:text-5xl text-ink leading-tight"
          data-testid="scene-title"
        >
          {scene.title}
        </h1>
        <div className="mt-3 font-mono text-xs text-muted2 flex flex-wrap gap-x-6 gap-y-1">
          <span data-testid="scene-stat-words">{stats.total} words</span>
          <span data-testid="scene-stat-ipa">
            {stats.transcribed} transcribed in IPA
          </span>
          <span>Click any word to hear it spoken</span>
        </div>
      </div>
      <div
        className="flex-1 overflow-auto scrollbar-thin px-10 lg:px-16 py-10 animate-fade-in"
        data-testid="scene-reader"
      >
        <div className="scene-flow max-w-[78ch]">
          {scene.tokens.map((tok, i) => (
            <WordBlock
              key={i}
              token={tok}
              active={activeIdx === i}
              highlighted={
                tok.is_word && highlightSet?.has(normalize(tok.text))
              }
              onSetActive={() => setActiveIdx(i)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function normalize(w) {
  return (w || "").toLowerCase().replace(/[^a-z']/g, "");
}
