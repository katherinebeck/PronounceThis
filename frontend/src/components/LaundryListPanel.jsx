import React, { useEffect, useMemo, useState } from "react";
import { Play, ChevronLeft, ChevronRight, X, Volume2, Search } from "lucide-react";
import { fetchLaundryList } from "@/lib/api";
import { playWord } from "@/lib/audio";
import YouglishModal from "./CaptionSearchModal";
import { toast } from "sonner";

export default function LaundryListPanel({
  scene,
  categories,
  onHighlightChange,
}) {
  const [activeCat, setActiveCat] = useState(null);
  const [list, setList] = useState(null); // { sound, count, words }
  const [loading, setLoading] = useState(false);
  const [practiceIdx, setPracticeIdx] = useState(0);
  const [ygQuery, setYgQuery] = useState(null);

  // Reset when scene changes.
  useEffect(() => {
    setActiveCat(null);
    setList(null);
    setPracticeIdx(0);
    onHighlightChange?.(new Set());
  }, [scene?.id, onHighlightChange]);

  const selectCategory = async (catId) => {
    if (!scene) return;
    setActiveCat(catId);
    setLoading(true);
    setPracticeIdx(0);
    try {
      const data = await fetchLaundryList(scene.id, catId);
      setList(data);
      const set = new Set(
        (data.words || []).map((w) =>
          w.text.toLowerCase().replace(/[^a-z']/g, "")
        )
      );
      onHighlightChange?.(set);
    } catch {
      toast.error("Could not load list.");
      setList(null);
    } finally {
      setLoading(false);
    }
  };

  const clearList = () => {
    setActiveCat(null);
    setList(null);
    setPracticeIdx(0);
    onHighlightChange?.(new Set());
  };

  const cur = list?.words?.[practiceIdx];

  const counts = useMemo(() => {
    if (!scene) return {};
    const c = {};
    for (const t of scene.tokens) {
      if (!t.is_word) continue;
      for (const cat of t.categories || []) c[cat] = (c[cat] || 0) + 1;
    }
    return c;
  }, [scene]);

  return (
    <aside
      className="w-full lg:w-[360px] xl:w-[400px] lg:shrink-0 border-t lg:border-t-0 lg:border-l thin-rule bg-surface flex flex-col min-w-0"
      data-testid="laundry-list-panel"
    >
      <div className="px-7 py-7 border-b thin-rule">
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2">
          Sound Workouts
        </div>
        <div className="font-display text-3xl leading-none text-ink">
          Sound Lists
        </div>
        <p className="mt-3 text-sm text-muted2 font-serif leading-relaxed">
          Pull every word from the scene that contains a target sound. Practice
          it in isolation, then return to the lines.
        </p>
      </div>

      {!scene ? (
        <div className="px-7 py-10 text-sm text-muted2 font-serif italic">
          Upload a scene to see categorized sound lists.
        </div>
      ) : !activeCat ? (
        <div
          className="flex-1 overflow-auto scrollbar-thin"
          data-testid="categories-list"
        >
          {categories.map((c) => {
            const count = counts[c.id] || 0;
            return (
              <button
                key={c.id}
                type="button"
                disabled={count === 0}
                className={
                  "w-full text-left px-7 py-5 border-b thin-rule transition-colors group " +
                  (count === 0
                    ? "opacity-40 cursor-not-allowed"
                    : "hover:bg-paper/70")
                }
                data-testid={`category-${c.id}`}
                onClick={() => selectCategory(c.id)}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-display text-2xl text-ink leading-tight">
                      {c.label}
                    </div>
                    <div className="mt-1 font-mono text-xs text-rust tracking-tight">
                      {c.ipa}
                    </div>
                  </div>
                  <div className="font-mono text-xs text-muted2 shrink-0">
                    {count} {count === 1 ? "word" : "words"}
                  </div>
                </div>
                <div className="mt-2 text-xs text-muted2 font-serif italic">
                  {c.description}
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="flex-1 flex flex-col animate-slide-in-right min-h-0">
          <div className="px-7 py-5 border-b thin-rule flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">
                List · {list?.count ?? 0} words
              </div>
              <div className="font-display text-2xl text-ink truncate">
                {categories.find((x) => x.id === activeCat)?.label}
              </div>
            </div>
            <button
              type="button"
              className="text-muted2 hover:text-ink p-1"
              data-testid="close-list-button"
              aria-label="Close list"
              onClick={clearList}
            >
              <X size={18} />
            </button>
          </div>

          {loading ? (
            <div className="px-7 py-10 font-mono text-xs text-muted2">
              Loading…
            </div>
          ) : list?.count === 0 ? (
            <div className="px-7 py-10 text-sm text-muted2 font-serif italic">
              No words with that sound in this scene.
            </div>
          ) : (
            <>
              <div
                className="px-7 py-8 border-b thin-rule"
                data-testid="practice-card"
              >
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 mb-2">
                  Practice
                </div>
                <div className="flex items-center justify-between gap-4">
                  <button
                    type="button"
                    className="text-muted2 hover:text-ink disabled:opacity-30"
                    data-testid="practice-prev"
                    disabled={practiceIdx === 0}
                    onClick={() => setPracticeIdx((i) => Math.max(0, i - 1))}
                    aria-label="Previous"
                  >
                    <ChevronLeft size={22} />
                  </button>
                  <button
                    type="button"
                    className="flex-1 group flex flex-col items-center gap-2 py-4 hover:bg-paper/70 transition-colors"
                    data-testid="practice-play"
                    onClick={async () => {
                      try {
                        await playWord(cur?.text, { phonetic: !!cur?.is_proper_noun, arpabet: cur?.variant_label && cur?.arpabet?.length ? cur.arpabet.join(" ") : null });
                      } catch {
                        toast.error("Playback failed.");
                      }
                    }}
                    aria-label={`Play ${cur?.text}`}
                  >
                    <span className="font-serif text-5xl text-ink leading-none">
                      {cur?.text}
                    </span>
                    <span className="font-mono text-base text-rust">
                      {cur?.ipa || "—"}
                    </span>
                    <span className="mt-2 inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 group-hover:text-rust">
                      <Volume2 size={12} /> Tap to hear
                    </span>
                  </button>
                  <button
                    type="button"
                    className="text-muted2 hover:text-ink disabled:opacity-30"
                    data-testid="practice-next"
                    disabled={practiceIdx >= (list?.count ?? 1) - 1}
                    onClick={() =>
                      setPracticeIdx((i) =>
                        Math.min((list?.count ?? 1) - 1, i + 1)
                      )
                    }
                    aria-label="Next"
                  >
                    <ChevronRight size={22} />
                  </button>
                </div>
                <div className="mt-3 text-center font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 flex items-center justify-center gap-4">
                  <span>{practiceIdx + 1} / {list?.count}</span>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:text-rust"
                    data-testid="practice-youglish"
                    onClick={() => cur?.text && setYgQuery(cur.text)}
                    title="Hear real speakers say this word"
                  >
                    <Search size={11} /> Clips
                  </button>
                </div>
              </div>

              <div
                className="flex-1 overflow-auto scrollbar-thin px-6 py-5"
                data-testid="word-list"
              >
                <div className="grid grid-cols-2 gap-2">
                  {list.words.map((w, i) => (
                    <button
                      key={`${i}-${w.word}`}
                      type="button"
                      className={
                        "border thin-rule px-3 py-2 flex flex-col items-start gap-0.5 hover:border-ink transition-colors min-w-0 text-left " +
                        (i === practiceIdx
                          ? "border-rust bg-paper"
                          : "")
                      }
                      data-testid={`list-word-${i}`}
                      onClick={async () => {
                        setPracticeIdx(i);
                        try {
                          await playWord(w.text, { phonetic: !!w.is_proper_noun, arpabet: w.variant_label && w.arpabet?.length ? w.arpabet.join(" ") : null });
                        } catch (e) {
                          console.warn("Word audio playback failed", w.text, e);
                        }
                      }}
                    >
                      <span className="font-serif text-base leading-tight text-ink truncate w-full">
                        {w.text}
                      </span>
                      <span className="font-mono text-[10px] text-rust truncate w-full">
                        {w.ipa || "—"}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}
      <YouglishModal
        open={Boolean(ygQuery)}
        query={ygQuery || ""}
        onClose={() => setYgQuery(null)}
      />
    </aside>
  );
}
