import React, { useState } from "react";
import { Volume2, Loader2 } from "lucide-react";
import { playWord } from "@/lib/audio";
import { toast } from "sonner";

// Words like "produce" / "record" that change stress (and sometimes vowels)
// by part of speech: one row per variant, each with its own audio.
export default function HeteronymVariants({ word, variants, catLookup }) {
  const [playing, setPlaying] = useState(null);

  const play = async (v, i) => {
    setPlaying(i);
    try {
      await playWord(word, { arpabet: v.arpabet.join(" ") });
    } catch (err) {
      toast.error(err.friendly || "Audio playback failed.");
    } finally {
      setPlaying(null);
    }
  };

  return (
    <div className="px-5 sm:px-8 py-5 sm:py-6 border-b thin-rule" data-testid="pronounce-variants">
      <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-rust mb-3">
        Two pronunciations — it depends on how the word is used
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {variants.map((v, i) => (
          <div
            key={v.label + i}
            className="border thin-rule bg-paper p-4 flex flex-col gap-3"
            data-testid={`pronounce-variant-${i}`}
          >
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                {v.label}
              </div>
              {v.gloss ? (
                <div className="font-serif text-sm text-muted2 italic mt-0.5">{v.gloss}</div>
              ) : null}
              <div className="font-mono text-2xl sm:text-3xl text-rust mt-2 tracking-tight break-words" data-testid={`pronounce-variant-ipa-${i}`}>
                {v.ipa}
              </div>
            </div>
            <button
              type="button"
              className="btn-primary self-start"
              onClick={() => play(v, i)}
              disabled={playing !== null}
              data-testid={`pronounce-variant-play-${i}`}
            >
              {playing === i ? (
                <><Loader2 size={12} className="animate-spin" /> Playing</>
              ) : (
                <><Volume2 size={13} /> Hear {v.label.split(" ")[0]}</>
              )}
            </button>
            {v.categories?.length ? (
              <div className="flex flex-wrap gap-1.5">
                {v.categories.map((cid) => (
                  <span key={cid} className="font-mono text-[10px] text-muted2 border thin-rule px-2 py-1">
                    {catLookup?.get(cid)?.label || cid}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
