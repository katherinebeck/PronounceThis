import React, { useEffect, useMemo, useState } from "react";
import { Volume2, Loader2, Search, Book, FileText, ArrowRight } from "lucide-react";
import { pronounceWord, fetchSoundCategories } from "@/lib/api";
import { playWord } from "@/lib/audio";
import YouglishModal from "./CaptionSearchModal";
import { toast } from "sonner";

// A small, focused word-lookup workbench: type anything, get IPA + ARPABET +
// sound categories, tap to hear Rachel say it, or open real-speaker clips
// from curated American YouTube channels. Complements the full scene view.
export default function PronouncePage({ onGoToScenes }) {
  const [input, setInput] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [playingHint, setPlayingHint] = useState(false);
  const [categoriesMeta, setCategoriesMeta] = useState([]);
  const [ygQuery, setYgQuery] = useState(null);

  useEffect(() => {
    fetchSoundCategories().then(setCategoriesMeta).catch(() => {});
  }, []);

  const catLookup = useMemo(() => {
    const m = new Map();
    for (const c of categoriesMeta) m.set(c.id, c);
    return m;
  }, [categoriesMeta]);

  const submit = async (e) => {
    e?.preventDefault?.();
    const word = input.trim();
    if (!word) return;
    setLoading(true);
    try {
      const r = await pronounceWord(word);
      setResult(r);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Lookup failed.");
    } finally {
      setLoading(false);
    }
  };

  const play = async () => {
    if (!result?.word) return;
    setPlayingHint(true);
    try {
      await playWord(result.word);
    } catch (err) {
      toast.error(err.friendly || "Audio playback failed.");
    } finally {
      setPlayingHint(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-paper" data-testid="pronounce-page">
      <div className="max-w-3xl mx-auto px-5 sm:px-10 lg:px-14 py-8 sm:py-12 lg:py-16">
        <div className="mb-8 sm:mb-10">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-3">
            Pronounce It · General American Accent Pronunciation Tool
          </div>
          <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl text-ink leading-[0.98]">
            Pronounce it.
            <br />
            <em className="not-italic text-rust">One word at a time.</em>
          </h1>
          <p className="mt-4 sm:mt-5 text-base sm:text-lg text-muted2 font-serif leading-relaxed max-w-2xl">
            Type any word, character name or location to see it written
            phonetically (IPA) and hear it spoken in an American accent.
          </p>
          <button
            type="button"
            onClick={() => onGoToScenes?.()}
            className="mt-6 sm:mt-8 w-full text-left border thin-rule bg-surface hover:border-ink transition-colors group flex items-start gap-3 sm:gap-4 p-4 sm:p-5"
            data-testid="scenes-promo-banner"
          >
            <FileText size={18} className="mt-1 shrink-0 text-rust" />
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
                Got an audition scene?
              </div>
              <div className="font-serif text-sm sm:text-base text-ink leading-snug">
                Import your scene and get a full IPA transcription, sound
                cues for every word, plus word lists pulled from your scene
                for sound practice drills.
              </div>
            </div>
            <span className="hidden sm:inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 group-hover:text-rust shrink-0 mt-1">
              Open Scenes <ArrowRight size={12} />
            </span>
          </button>
        </div>

        <form
          onSubmit={submit}
          className="border thin-rule bg-surface p-2 sm:p-3 flex items-center gap-2 sm:gap-3"
        >
          <Search size={16} className="hidden sm:block text-muted2 ml-3" />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a word — Whitmore, February…"
            className="flex-1 min-w-0 bg-transparent outline-none font-serif text-lg sm:text-xl text-ink placeholder:text-muted2/60 pl-3 sm:pl-0"
            data-testid="pronounce-input"
            autoFocus
          />
          <button
            type="submit"
            className="btn-primary shrink-0"
            data-testid="pronounce-submit"
            disabled={loading}
          >
            {loading ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                <span className="hidden sm:inline"> Looking up</span>
              </>
            ) : (
              <>Pronounce</>
            )}
          </button>
        </form>

        {result ? (
          <div className="mt-8 sm:mt-10 border thin-rule bg-surface animate-fade-in" data-testid="pronounce-result">
            <div className="px-5 sm:px-8 py-6 sm:py-8 border-b thin-rule flex items-start justify-between gap-4 sm:gap-6 flex-wrap">
              <div className="min-w-0">
                <div className="font-serif text-4xl sm:text-5xl lg:text-6xl text-ink leading-none break-words">
                  {result.word}
                </div>
                {result.ipa ? (
                  <div className="font-mono text-xl sm:text-2xl lg:text-3xl text-rust mt-3 tracking-tight break-words" data-testid="pronounce-ipa">
                    {result.ipa}
                  </div>
                ) : (
                  <div className="mt-3 text-sm text-muted2 font-serif italic">
                    We couldn’t transcribe this one. Try a variant spelling.
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  className="btn-primary"
                  data-testid="pronounce-play"
                  onClick={play}
                  disabled={!result.ipa || playingHint}
                >
                  {playingHint ? (
                    <>
                      <Loader2 size={12} className="animate-spin" /> Playing
                    </>
                  ) : (
                    <>
                      <Volume2 size={13} /> Hear Word
                    </>
                  )}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  data-testid="pronounce-youglish"
                  onClick={() => setYgQuery(result.word)}
                >
                  <Book size={12} /> Real Speaker Examples
                </button>
              </div>
            </div>

            {result.categories?.length ? (
              <div className="px-5 sm:px-8 py-5 sm:py-6" data-testid="pronounce-categories">
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-3">
                  Sounds in this word
                </div>
                <div className="flex flex-wrap gap-2">
                  {result.categories.map((cid) => {
                    const meta = catLookup.get(cid);
                    return (
                      <div
                        key={cid}
                        className="inline-flex items-baseline gap-2 border thin-rule px-3 py-2 bg-paper"
                        data-testid={`pronounce-category-${cid}`}
                      >
                        <span className="font-serif text-sm sm:text-base text-ink">
                          {meta?.label || cid}
                        </span>
                        <span className="font-mono text-xs text-rust">
                          {meta?.ipa || ""}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="mt-10 sm:mt-12 grid grid-cols-1 sm:grid-cols-3 gap-px bg-rule">
            {[
              { t: "IPA", d: "See the exact American English phonetic spelling for any word." },
              { t: "Audio", d: "Tap to hear the word spoken in a natural General American voice." },
              { t: "Real Speakers", d: "Hear the word spoken in clips from curated American English YouTube channels — news anchors, late-night hosts, dialect coaches." },
            ].map((c) => (
              <div key={c.t} className="bg-surface p-5 sm:p-6">
                <div className="font-display text-2xl text-ink">{c.t}</div>
                <p className="mt-2 text-sm text-muted2 font-serif leading-relaxed">
                  {c.d}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
      <YouglishModal
        open={Boolean(ygQuery)}
        query={ygQuery || ""}
        onClose={() => setYgQuery(null)}
      />
    </div>
  );
}
