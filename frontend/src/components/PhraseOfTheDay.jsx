import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Sparkles, ChevronRight } from "lucide-react";

/**
 * Phrase of the Day widget — appears on the home page above the search bar.
 * Rotates daily; deterministic per UTC day so all users see the same phrase.
 * Real-speaker examples fill in once the caption index is populated.
 */
export default function PhraseOfTheDay({ onPickPhrase }) {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let alive = true;
    api.get("/phrase-of-the-day")
      .then((res) => { if (alive) setData(res.data); })
      .catch(() => { /* silent — widget just doesn't render */ });
    return () => { alive = false; };
  }, []);

  if (!data || !data.phrase) return null;

  return (
    <section
      className="border thin-rule bg-surface p-5 sm:p-6 mb-6"
      data-testid="phrase-of-the-day"
    >
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={12} className="text-rust" />
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          Phrase of the day · {data.date}
        </div>
      </div>
      <h3 className="font-display text-2xl sm:text-3xl text-ink italic mb-2">
        "{data.phrase}"
      </h3>
      <p className="font-serif text-sm text-muted2 leading-relaxed mb-3">
        {data.meaning}
      </p>
      {data.ipa ? (
        <p
          className="font-mono text-sm text-ink mb-3 break-all"
          data-testid="phrase-of-the-day-ipa"
        >
          /{data.ipa}/
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onPickPhrase && onPickPhrase(data.phrase)}
          className="font-mono text-[10px] uppercase tracking-[0.22em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5"
          data-testid="phrase-of-the-day-lookup"
        >
          Look it up
          <ChevronRight size={12} />
        </button>
        {data.real_speakers && data.real_speakers.length > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 hover:text-ink transition-colors"
            data-testid="phrase-of-the-day-speakers-toggle"
          >
            {expanded ? "Hide" : "Show"} {data.real_speakers.length} real
            speaker{data.real_speakers.length === 1 ? "" : "s"}
          </button>
        ) : null}
      </div>
      {expanded && data.real_speakers?.length > 0 ? (
        <div className="mt-4 pt-4 border-t thin-rule space-y-3">
          {data.real_speakers.map((sp) => (
            <a
              key={sp.video_id}
              href={sp.youtube_url}
              target="_blank"
              rel="noreferrer"
              className="block hover:opacity-80 transition-opacity"
              data-testid={`phrase-of-the-day-speaker-${sp.video_id}`}
            >
              <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                {sp.channel_title || "YouTube"}
              </div>
              {sp.snippet ? (
                <div className="font-serif text-sm text-ink italic mt-1">
                  "{sp.snippet}"
                </div>
              ) : (
                <div className="font-serif text-sm text-ink italic mt-1">
                  {sp.title}
                </div>
              )}
            </a>
          ))}
        </div>
      ) : null}
    </section>
  );
}
