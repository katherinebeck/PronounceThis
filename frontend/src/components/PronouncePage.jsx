import React, { useEffect, useMemo, useState } from "react";
import { Volume2, Loader2, Search, Book, ArrowRight } from "lucide-react";
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

  const submit = async (e, override) => {
    e?.preventDefault?.();
    const word = (override ?? input).trim();
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

  // Heuristic: words with a capital letter or a space are usually proper nouns
  // or multi-word phrases (e.g. "Los Angeles"), which ElevenLabs is most
  // likely to mispronounce. When Katherine hasn't uploaded a manual override
  // for one, we auto-open Real Speakers alongside the Play so the student
  // hears at least one real native speaker say the word.
  const looksProper = (w) => /[A-Z]/.test(w || "") || /\s/.test(w || "");

  const play = async () => {
    if (!result?.word) return;
    setPlayingHint(true);
    try {
      const audio = await playWord(result.word, { phonetic: looksProper(input.trim()) });
      // If ElevenLabs generated this (no admin override) AND the word looks
      // like a proper noun, also open Real Speakers so the student can
      // sanity-check against a real human.
      if (audio && !audio.manualOverride && looksProper(input.trim())) {
        setYgQuery(input.trim());
      }
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
          <div className="reveal font-mono text-sm sm:text-base uppercase tracking-[0.2em] text-rust mb-2">
            Pronounce This · Prepare for your next audition. Hear how to pronounce every word.
          </div>
          <div className="reveal font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-3">
            The General American Accent Pronunciation Tool Specifically Designed For Actors
          </div>
          <h1 className="reveal reveal-2 font-display font-bold text-3xl sm:text-4xl lg:text-5xl text-ink leading-[0.98] tracking-tight">
            Pronounce This<span className="text-rust">.</span>
          </h1>
          <p className="reveal reveal-3 mt-4 sm:mt-5 text-lg sm:text-lg text-muted2 font-serif leading-relaxed max-w-2xl">
            Type any word, name or location to see it written
            phonetically (IPA) and hear it spoken in an American accent.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="reveal reveal-4 border border-ink/70 bg-surface p-2 sm:p-3 flex items-center gap-2 sm:gap-3 transition-[border-color,box-shadow] duration-200 focus-within:border-rust focus-within:shadow-[0_0_0_1px_rgba(229,169,60,0.35),0_24px_60px_-30px_rgba(229,169,60,0.4)]"
        >
          <Search size={16} className="hidden sm:block text-muted2 ml-3" />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a word"
            className="flex-1 min-w-0 bg-transparent outline-none font-serif text-lg sm:text-xl text-ink placeholder:text-muted2/60 pl-3 sm:pl-0"
            data-testid="pronounce-input"
            autoFocus
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            data-form-type="other"
            name="pronounce-word"
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
          <div className="mt-8 sm:mt-10 border thin-rule bg-surface animate-fade-in shadow-[0_30px_80px_-40px_rgba(0,0,0,0.9)]" data-testid="pronounce-result">
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
        ) : null}

        {/* Audition scene invitation — same visual weight as the main hero
            so it reads as a second, equally-important on-ramp. */}
        <div className="mt-10 sm:mt-12 pt-8 sm:pt-10 border-t border-ink/30">
          <h2 className="font-display font-bold text-3xl sm:text-4xl lg:text-5xl text-ink leading-[0.98] tracking-tight">
            Scene Preparation<span className="text-rust">.</span>
          </h2>
          <p className="mt-4 sm:mt-5 text-lg sm:text-lg text-muted2 font-serif leading-relaxed max-w-2xl">
            Upload an audition scene as a PDF. Each word will be transcribed in
            American IPA, click any word to hear it spoken aloud, pull laundry
            lists by sound to practice tricky sounds and download an audio
            sample of your character's dialogue for practice.
          </p>
          <button
            type="button"
            onClick={() => onGoToScenes?.()}
            className="mt-6 sm:mt-8 btn-primary text-[11px] sm:text-[12px] px-6 py-3 sm:px-7 sm:py-3.5"
            data-testid="scenes-promo-banner"
          >
            Audition Scene <ArrowRight size={13} />
          </button>
        </div>
      </div>
      <YouglishModal
        open={Boolean(ygQuery)}
        query={ygQuery || ""}
        onClose={() => setYgQuery(null)}
      />
    </div>
  );
}
