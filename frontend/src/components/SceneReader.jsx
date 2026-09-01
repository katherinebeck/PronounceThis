import React, { useEffect, useMemo, useRef, useState } from "react";
import { Play, Pause, Square, Loader2, Volume2 } from "lucide-react";
import WordBlock from "./WordBlock";
import YouglishModal from "./CaptionSearchModal";
import { loadTurnAudio } from "@/lib/audio";
import { toast } from "sonner";

// Pause between turns. Same speaker (rare with our merge, but possible for
// narration-then-narration): a short breath. Different speaker: a real beat.
const PAUSE_SAME_MS = 250;
const PAUSE_CHANGE_MS = 750;

function normalize(w) {
  return (w || "").toLowerCase().replace(/[^a-z']/g, "");
}

// Strip leading/trailing pure-whitespace tokens so each turn starts and ends
// tightly around real content.
function trimEdgeWhitespace(tokens) {
  let start = 0;
  let end = tokens.length;
  while (start < end) {
    const t = tokens[start];
    if (!t.is_word && /^\s*$/.test(t.text)) start++;
    else break;
  }
  while (end > start) {
    const t = tokens[end - 1];
    if (!t.is_word && /^\s*$/.test(t.text)) end--;
    else break;
  }
  return tokens.slice(start, end);
}

export default function SceneReader({ scene, highlightSet }) {
  const [activeIdx, setActiveIdx] = useState(null);
  const [playingTurn, setPlayingTurn] = useState(null); // int | null
  const [loadingTurn, setLoadingTurn] = useState(null);
  const [scenePlaying, setScenePlaying] = useState(false);
  const [ygQuery, setYgQuery] = useState(null); // string | null → modal
  const audioRef = useRef(null);
  const stopRef = useRef(false);

  const stats = useMemo(() => {
    const words = (scene?.tokens || []).filter((t) => t.is_word);
    const transcribed = words.filter((w) => w.ipa).length;
    return { total: words.length, transcribed };
  }, [scene]);

  // Group tokens by turn_index preserving order. Tokens with turn_index=null
  // (speaker labels like "FRIEND:" living in the gap between turns) are
  // dropped — the speaker is already rendered as a header above each turn.
  const grouped = useMemo(() => {
    if (!scene) return [];
    const byTurn = new Map();
    for (const tok of scene.tokens) {
      if (tok.turn_index === null || tok.turn_index === undefined) continue;
      const ti = tok.turn_index;
      if (!byTurn.has(ti)) byTurn.set(ti, []);
      byTurn.get(ti).push(tok);
    }
    const turnsMeta = new Map((scene.turns || []).map((t) => [t.index, t]));
    return Array.from(byTurn.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([ti, toks]) => ({
        index: ti,
        speaker: turnsMeta.get(ti)?.speaker || null,
        text: turnsMeta.get(ti)?.text || "",
        tokens: trimEdgeWhitespace(toks),
      }));
  }, [scene]);

  // Cleanup on unmount / scene change.
  useEffect(() => {
    return () => {
      stopRef.current = true;
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, [scene?.id]);

  const stopEverything = () => {
    stopRef.current = true;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    setPlayingTurn(null);
    setLoadingTurn(null);
    setScenePlaying(false);
  };

  const playOneTurn = (turnIndex) =>
    new Promise(async (resolve, reject) => {
      if (stopRef.current) return resolve();
      setLoadingTurn(turnIndex);
      let url;
      try {
        url = await loadTurnAudio(scene.id, turnIndex);
      } catch (e) {
        setLoadingTurn(null);
        reject(e);
        return;
      }
      if (stopRef.current) {
        setLoadingTurn(null);
        return resolve();
      }
      const audio = new Audio(url);
      audioRef.current = audio;
      setLoadingTurn(null);
      setPlayingTurn(turnIndex);
      audio.onended = () => {
        setPlayingTurn(null);
        resolve();
      };
      audio.onerror = () => {
        setPlayingTurn(null);
        reject(new Error("Playback error"));
      };
      audio.play().catch(reject);
    });

  const handlePlayTurn = async (turnIndex) => {
    // If this turn is already playing, treat as toggle to stop.
    if (playingTurn === turnIndex) {
      stopEverything();
      return;
    }
    stopEverything();
    stopRef.current = false;
    try {
      await playOneTurn(turnIndex);
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
      stopEverything();
    }
  };

  const handlePlayScene = async () => {
    if (scenePlaying) {
      stopEverything();
      return;
    }
    stopEverything();
    stopRef.current = false;
    setScenePlaying(true);
    try {
      let prevSpeaker = null;
      for (const t of grouped) {
        if (stopRef.current) break;
        const pause =
          prevSpeaker === null
            ? 0
            : t.speaker && t.speaker === prevSpeaker
              ? PAUSE_SAME_MS
              : PAUSE_CHANGE_MS;
        if (pause > 0) {
          await new Promise((r) => setTimeout(r, pause));
          if (stopRef.current) break;
        }
        await playOneTurn(t.index);
        prevSpeaker = t.speaker;
      }
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
    } finally {
      setScenePlaying(false);
      setPlayingTurn(null);
    }
  };

  if (!scene) return null;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-paper">
      <div className="px-6 lg:px-10 xl:px-14 pt-8 pb-5 border-b thin-rule">
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div className="min-w-0">
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
              <span data-testid="scene-stat-words">
                {stats.total} words
              </span>
              <span data-testid="scene-stat-ipa">
                {stats.transcribed} transcribed in IPA
              </span>
              <span data-testid="scene-stat-turns">
                {grouped.length} {grouped.length === 1 ? "turn" : "turns"}
              </span>
              <span>Click a word to hear it — or play the whole scene</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={
                "btn-primary " + (scenePlaying ? "!bg-rust" : "")
              }
              data-testid="play-scene-button"
              onClick={handlePlayScene}
            >
              {scenePlaying ? (
                <>
                  <Square size={12} fill="currentColor" /> Stop
                </>
              ) : (
                <>
                  <Play size={12} fill="currentColor" /> Play Scene
                </>
              )}
            </button>
          </div>
        </div>
      </div>
      <div
        className="flex-1 overflow-auto scrollbar-thin px-6 lg:px-10 xl:px-14 py-8 animate-fade-in"
        data-testid="scene-reader"
      >
        <div className="max-w-[78ch] flex flex-col gap-8">
          {grouped.map((turn) => (
            <TurnBlock
              key={turn.index}
              turn={turn}
              activeIdx={activeIdx}
              onSetActive={setActiveIdx}
              highlightSet={highlightSet}
              playing={playingTurn === turn.index}
              loading={loadingTurn === turn.index}
              onTogglePlay={() => handlePlayTurn(turn.index)}
              scenePlaying={scenePlaying}
              onOpenReference={setYgQuery}
            />
          ))}
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

function TurnBlock({
  turn,
  activeIdx,
  onSetActive,
  highlightSet,
  playing,
  loading,
  onTogglePlay,
  scenePlaying,
  onOpenReference,
}) {
  const isNarration = !turn.speaker;
  return (
    <div
      className={
        "relative group border-l-2 pl-6 py-1 transition-colors " +
        (playing
          ? "border-rust bg-[rgba(200,90,79,0.06)]"
          : "border-transparent hover:border-[#E5E1D8]")
      }
      data-testid={`turn-${turn.index}`}
    >
      <div className="flex items-center gap-3 mb-2">
        <button
          type="button"
          className={
            "shrink-0 inline-flex items-center justify-center w-8 h-8 border thin-rule transition-colors " +
            (playing
              ? "bg-rust text-white border-rust"
              : "bg-surface hover:bg-paper hover:border-ink")
          }
          data-testid={`turn-play-${turn.index}`}
          onClick={onTogglePlay}
          disabled={scenePlaying && !playing}
          aria-label={playing ? "Stop line" : "Play line"}
        >
          {loading ? (
            <Loader2 size={13} className="animate-spin" />
          ) : playing ? (
            <Pause size={13} fill="currentColor" />
          ) : (
            <Play size={13} fill="currentColor" />
          )}
        </button>
        {turn.speaker ? (
          <div
            className={
              "font-mono text-[10px] uppercase tracking-[0.28em] " +
              (playing ? "text-rust" : "text-muted2")
            }
            data-testid={`turn-speaker-${turn.index}`}
          >
            {turn.speaker}
          </div>
        ) : (
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 italic">
            {isNarration ? "Narration" : ""}
          </div>
        )}
        {playing ? (
          <span className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.22em] text-rust">
            <Volume2 size={12} /> Now speaking
          </span>
        ) : null}
      </div>
      <div className="scene-flow">
        {turn.tokens.map((tok, i) => (
          <WordBlock
            key={i}
            token={tok}
            active={activeIdx === `${turn.index}:${i}`}
            highlighted={
              tok.is_word && highlightSet?.has(normalize(tok.text))
            }
            onSetActive={() => onSetActive(`${turn.index}:${i}`)}
            onOpenReference={onOpenReference}
          />
        ))}
      </div>
    </div>
  );
}
