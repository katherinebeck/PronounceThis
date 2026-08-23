import React, { useEffect, useMemo, useState } from "react";
import { Volume2, Loader2, Search, Book } from "lucide-react";
import { pronounceWord, fetchSoundCategories } from "@/lib/api";
import { playWord } from "@/lib/audio";
import YouglishModal from "./YouglishModal";
import { toast } from "sonner";

// A small, focused word-lookup workbench: type anything, get IPA + ARPABET +
// sound categories, tap to hear Rachel say it, or open YouGlish for real
// speakers. Complements the full scene view.
export default function PronouncePage() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [playingHint, setPlayingHint] = useState(false);
  const [categoriesMeta, setCategoriesMeta] = useState([]);
  const [ygQuery, setYgQuery] = useState(null);
  const [history, setHistory] = useState(() => {
    try {
      const raw = window.localStorage.getItem("pronounceHistory");
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });

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
      setHistory((h) => {
        const next = [word, ...h.filter((x) => x.toLowerCase() !== word.toLowerCase())].slice(0, 8);
        try {
          window.localStorage.setItem("pronounceHistory", JSON.stringify(next));
        } catch {
          // localStorage unavailable — history is a nice-to-have, drop it.
        }
        return next;
      });
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

  const lookup = (w) => {
    setInput(w);
    setTimeout(() => submit(), 0);
  };

  return (
    <div className="flex-1 overflow-auto bg-paper" data-testid="pronounce-page">
      <div className="max-w-3xl mx-auto px-10 lg:px-14 py-12 lg:py-16">
        <div className="mb-10">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-3">
            Pronounce It · General American Accent Pronunciation Tool
          </div>
          <h1 className="font-display text-5xl lg:text-6xl text-ink leading-[0.98]">
            Pronounce it.
            <br />
            <em className="not-italic text-rust">One word at a time.</em>
          </h1>
          <p className="mt-5 text-lg text-muted2 font-serif leading-relaxed max-w-2xl">
            Type any word, character name, location name to see the American
            IPA, hear it spoken and pull real-speaker references from YouGlish.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="border thin-rule bg-surface p-3 flex items-center gap-3"
        >
          <Search size={16} className="text-muted2 ml-3" />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a word — Whitmore, February, Independence…"
            className="flex-1 bg-transparent outline-none font-serif text-xl text-ink placeholder:text-muted2/60"
            data-testid="pronounce-input"
            autoFocus
          />
          <button
            type="submit"
            className="btn-primary"
            data-testid="pronounce-submit"
            disabled={loading}
          >
            {loading ? (
              <>
                <Loader2 size={12} className="animate-spin" /> Looking up
              </>
            ) : (
              <>Pronounce</>
            )}
          </button>
        </form>

        {history.length > 0 && !result ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
              Recent
            </span>
            {history.map((w) => (
              <button
                key={w}
                type="button"
                className="font-mono text-xs px-2 py-1 border thin-rule bg-surface hover:border-ink"
                data-testid={`recent-${w}`}
                onClick={() => lookup(w)}
              >
                {w}
              </button>
            ))}
          </div>
        ) : null}

        {result ? (
          <div className="mt-10 border thin-rule bg-surface animate-fade-in" data-testid="pronounce-result">
            <div className="px-8 py-8 border-b thin-rule flex items-start justify-between gap-6 flex-wrap">
              <div className="min-w-0">
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">
                  {result.source === "cmu"
                    ? "CMU Pronouncing Dictionary"
                    : result.source === "llm"
                      ? "AI transcription (Claude)"
                      : "Not found"}
                </div>
                <div className="font-serif text-5xl lg:text-6xl text-ink mt-2 leading-none">
                  {result.word}
                </div>
                {result.ipa ? (
                  <div className="font-mono text-2xl lg:text-3xl text-rust mt-3 tracking-tight" data-testid="pronounce-ipa">
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
                  <Book size={12} /> YouGlish
                </button>
              </div>
            </div>

            {result.arpabet?.length ? (
              <div className="px-8 py-5 border-b thin-rule">
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2">
                  ARPABET
                </div>
                <div className="font-mono text-sm text-ink tracking-wide" data-testid="pronounce-arpabet">
                  {result.arpabet.join("  ")}
                </div>
              </div>
            ) : null}

            {result.categories?.length ? (
              <div className="px-8 py-6" data-testid="pronounce-categories">
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
                        <span className="font-serif text-base text-ink">
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
          <div className="mt-12 grid grid-cols-3 gap-px bg-rule">
            {[
              { t: "IPA", d: "See the exact American English phonetic spelling for any word." },
              { t: "Audio", d: "Tap to hear the word spoken in a natural General American voice." },
              { t: "Real Speakers", d: "Open YouGlish to hear it in real YouTube clips - great for names and locations." },
            ].map((c) => (
              <div key={c.t} className="bg-surface p-6">
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
