import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Play,
  Pause,
  Square,
  Loader2,
  Volume2,
  User,
  Mic,
  BookOpen,
  Users,
  ChevronDown,
  SkipForward,
} from "lucide-react";
import WordBlock from "./WordBlock";
import YouglishModal from "./CaptionSearchModal";
import { loadTurnAudio } from "@/lib/audio";
import { fetchReaderVoices } from "@/lib/api";
import { toast } from "sonner";

// Pause between turns for Play My Lines (same-character, back-to-back).
const PAUSE_BETWEEN_MY_LINES_MS = 600;
// Between reader-voice lines in Run Lines (natural conversational beat).
const PAUSE_AFTER_READER_MS = 400;
// Extra buffer added to the estimated speak time before auto-advancing.
const USER_LINE_BUFFER_MS = 1000;
// Speaking speed estimate for the user's own lines: characters per second.
// ~2.5 words/sec × ~5 chars/word ≈ 12.5 chars/sec.
const USER_CHARS_PER_SEC = 12.5;

function normalize(w) {
  return (w || "").toLowerCase().replace(/[^a-z']/g, "");
}

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

// Persist the coach's per-scene picks (character + reader voice) so
// re-opening a scene remembers them. Scoped per browser.
function usePersistedScenePrefs(sceneId) {
  const key = sceneId ? `scene_prefs::${sceneId}` : null;
  const [prefs, setPrefs] = useState({ character: null, reader: null });
  useEffect(() => {
    if (!key) return;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) setPrefs(JSON.parse(raw));
      else setPrefs({ character: null, reader: null });
    } catch {
      setPrefs({ character: null, reader: null });
    }
  }, [key]);
  const update = (patch) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      if (key) {
        try {
          window.localStorage.setItem(key, JSON.stringify(next));
        } catch {}
      }
      return next;
    });
  };
  return [prefs, update];
}

export default function SceneReader({ scene, highlightSet }) {
  const [activeIdx, setActiveIdx] = useState(null);
  const [playingTurn, setPlayingTurn] = useState(null); // int | null
  const [loadingTurn, setLoadingTurn] = useState(null);
  const [mode, setMode] = useState("read"); // "read" | "mine" | "run"
  const [running, setRunning] = useState(false); // any auto-playback in progress
  const [ygQuery, setYgQuery] = useState(null);
  const [readerVoices, setReaderVoices] = useState([]);
  const [prefs, setPrefs] = usePersistedScenePrefs(scene?.id);
  const audioRef = useRef(null);
  const stopRef = useRef(false);
  const skipRef = useRef(false); // Run Lines: user tapped "Skip to next"

  // Load available reader voices once.
  useEffect(() => {
    fetchReaderVoices()
      .then(setReaderVoices)
      .catch(() => setReaderVoices([]));
  }, []);

  const stats = useMemo(() => {
    const words = (scene?.tokens || []).filter((t) => t.is_word);
    const transcribed = words.filter((w) => w.ipa).length;
    return { total: words.length, transcribed };
  }, [scene]);

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

  // Distinct speakers in the scene (excluding narration).
  const speakers = useMemo(() => {
    const seen = new Set();
    const out = [];
    for (const t of grouped) {
      if (t.speaker && !seen.has(t.speaker)) {
        seen.add(t.speaker);
        out.push(t.speaker);
      }
    }
    return out;
  }, [grouped]);

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

  // Escape / Space handling in Run Lines: Space = skip user's line.
  useEffect(() => {
    if (mode !== "run" || !running) return undefined;
    const onKey = (e) => {
      if (e.key === " " || e.code === "Space") {
        e.preventDefault();
        skipRef.current = true;
      } else if (e.key === "Escape") {
        stopEverything();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, running]);

  const stopEverything = () => {
    stopRef.current = true;
    skipRef.current = false;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }
    setPlayingTurn(null);
    setLoadingTurn(null);
    setRunning(false);
  };

  const playOneTurn = (turnIndex, { voice = null } = {}) =>
    new Promise(async (resolve, reject) => {
      if (stopRef.current) return resolve();
      setLoadingTurn(turnIndex);
      let url;
      try {
        url = await loadTurnAudio(scene.id, turnIndex, { voice });
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

  // Mode 2: play only the auditioning character's lines back-to-back.
  const handlePlayMyLines = async () => {
    if (running) {
      stopEverything();
      return;
    }
    if (!prefs.character) {
      toast.error("Pick which character you're auditioning for first.");
      return;
    }
    stopEverything();
    stopRef.current = false;
    setRunning(true);
    try {
      const mine = grouped.filter((t) => t.speaker === prefs.character);
      for (let i = 0; i < mine.length; i++) {
        if (stopRef.current) break;
        if (i > 0) {
          await new Promise((r) => setTimeout(r, PAUSE_BETWEEN_MY_LINES_MS));
          if (stopRef.current) break;
        }
        await playOneTurn(mine[i].index);
      }
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
    } finally {
      setRunning(false);
      setPlayingTurn(null);
    }
  };

  // Mode 3: reader voice speaks other-character lines; wait during user's.
  const handleRunLines = async () => {
    if (running) {
      stopEverything();
      return;
    }
    if (!prefs.character) {
      toast.error("Pick your character first.");
      return;
    }
    if (!prefs.reader) {
      toast.error("Pick a reader voice for the other characters.");
      return;
    }
    stopEverything();
    stopRef.current = false;
    skipRef.current = false;
    setRunning(true);
    try {
      for (let i = 0; i < grouped.length; i++) {
        if (stopRef.current) break;
        const t = grouped[i];
        const isMine = t.speaker === prefs.character;
        if (isMine) {
          // Waiting for the actor to say their line out loud. Highlight it,
          // auto-advance after estimated speak time, but honor tap-to-skip.
          setPlayingTurn(t.index);
          const estMs = Math.max(
            1500,
            Math.round((t.text.length / USER_CHARS_PER_SEC) * 1000) + USER_LINE_BUFFER_MS,
          );
          const stepMs = 100;
          let waited = 0;
          skipRef.current = false;
          while (waited < estMs && !stopRef.current && !skipRef.current) {
            await new Promise((r) => setTimeout(r, stepMs));
            waited += stepMs;
          }
          setPlayingTurn(null);
        } else {
          // Reader voice speaks this line.
          await playOneTurn(t.index, { voice: prefs.reader });
          if (stopRef.current) break;
          await new Promise((r) => setTimeout(r, PAUSE_AFTER_READER_MS));
        }
      }
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
    } finally {
      setRunning(false);
      setPlayingTurn(null);
    }
  };

  if (!scene) return null;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-paper">
      <div className="px-4 sm:px-6 lg:px-10 xl:px-14 pt-6 sm:pt-8 pb-4 sm:pb-5 border-b thin-rule">
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
            </div>
          </div>
        </div>

        {/* Mode tabs */}
        <div
          className="mt-5 inline-flex border thin-rule overflow-hidden"
          role="tablist"
          data-testid="scene-mode-tabs"
        >
          {[
            { id: "read", label: "Read", icon: BookOpen },
            { id: "mine", label: "Play My Lines", icon: Mic },
            { id: "run",  label: "Run Lines",     icon: Users },
          ].map((m) => {
            const Icon = m.icon;
            const active = mode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                role="tab"
                aria-selected={active}
                data-testid={`mode-tab-${m.id}`}
                onClick={() => {
                  stopEverything();
                  setMode(m.id);
                }}
                className={
                  "inline-flex items-center gap-2 px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.22em] border-r thin-rule last:border-r-0 transition-colors " +
                  (active ? "bg-ink text-surface" : "text-ink hover:bg-paper")
                }
              >
                <Icon size={12} />
                {m.label}
              </button>
            );
          })}
        </div>

        {/* Mode-specific controls */}
        {(mode === "mine" || mode === "run") && speakers.length > 0 ? (
          <div className="mt-4 flex items-center gap-3 flex-wrap">
            <CharacterPicker
              speakers={speakers}
              value={prefs.character}
              onChange={(c) => setPrefs({ character: c })}
            />
            {mode === "run" ? (
              <ReaderVoicePicker
                voices={readerVoices}
                value={prefs.reader}
                onChange={(v) => setPrefs({ reader: v })}
              />
            ) : null}
            <button
              type="button"
              className={"btn-primary " + (running ? "!bg-rust" : "")}
              onClick={mode === "mine" ? handlePlayMyLines : handleRunLines}
              data-testid={mode === "mine" ? "play-my-lines-button" : "run-lines-button"}
            >
              {running ? (
                <>
                  <Square size={12} fill="currentColor" /> Stop
                </>
              ) : (
                <>
                  <Play size={12} fill="currentColor" />{" "}
                  {mode === "mine" ? "Play My Lines" : "Start Practicing"}
                </>
              )}
            </button>
            {mode === "run" && running ? (
              <button
                type="button"
                onClick={() => (skipRef.current = true)}
                className="btn-secondary"
                data-testid="run-lines-skip"
                title="Skip to next line (or press Space)"
              >
                <SkipForward size={12} /> Skip
              </button>
            ) : null}
          </div>
        ) : null}

        {mode === "run" && running ? (
          <div className="mt-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
            Press <span className="text-ink">Space</span> to skip your line ·{" "}
            <span className="text-ink">Esc</span> to stop
          </div>
        ) : null}
      </div>

      <div
        className="flex-1 overflow-auto scrollbar-thin px-4 sm:px-6 lg:px-10 xl:px-14 py-6 sm:py-8 animate-fade-in"
        data-testid="scene-reader"
      >
        <div className="max-w-[78ch] flex flex-col gap-8">
          {grouped.map((turn) => {
            const isMine =
              prefs.character && turn.speaker === prefs.character;
            const dimOthers =
              (mode === "mine" || mode === "run") &&
              prefs.character &&
              turn.speaker &&
              !isMine;
            return (
              <TurnBlock
                key={turn.index}
                turn={turn}
                activeIdx={activeIdx}
                onSetActive={setActiveIdx}
                highlightSet={highlightSet}
                playing={playingTurn === turn.index}
                loading={loadingTurn === turn.index}
                onTogglePlay={() => handlePlayTurn(turn.index)}
                autoPlaying={running}
                isMine={isMine}
                dimOthers={dimOthers}
                mode={mode}
                waitingForUser={
                  mode === "run" && running &&
                  playingTurn === turn.index && isMine
                }
                onOpenReference={setYgQuery}
              />
            );
          })}
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

function CharacterPicker({ speakers, value, onChange }) {
  return (
    <label className="inline-flex items-center gap-2 border thin-rule bg-surface px-3 py-2 font-mono text-[11px] uppercase tracking-[0.22em]">
      <User size={12} className="text-muted2" />
      <span className="text-muted2">You are</span>
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="bg-transparent outline-none text-ink pr-1"
        data-testid="character-picker"
      >
        <option value="">— pick —</option>
        {speakers.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
      <ChevronDown size={11} className="text-muted2 -ml-1" />
    </label>
  );
}

function ReaderVoicePicker({ voices, value, onChange }) {
  return (
    <label className="inline-flex items-center gap-2 border thin-rule bg-surface px-3 py-2 font-mono text-[11px] uppercase tracking-[0.22em]">
      <Volume2 size={12} className="text-muted2" />
      <span className="text-muted2">Reader</span>
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="bg-transparent outline-none text-ink pr-1"
        data-testid="reader-voice-picker"
      >
        <option value="">— pick —</option>
        {voices.map((v) => (
          <option key={v.key} value={v.key}>
            {v.label} ({v.gender})
          </option>
        ))}
      </select>
      <ChevronDown size={11} className="text-muted2 -ml-1" />
    </label>
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
  autoPlaying,
  isMine,
  dimOthers,
  mode,
  waitingForUser,
  onOpenReference,
}) {
  const isNarration = !turn.speaker;
  return (
    <div
      className={
        "relative group border-l-2 pl-6 py-1 transition-all " +
        (playing
          ? "border-rust bg-[rgba(200,90,79,0.06)]"
          : "border-transparent hover:border-[#E5E1D8]") +
        (dimOthers ? " opacity-45" : "") +
        (isMine ? " border-l-ink" : "")
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
          disabled={autoPlaying && !playing}
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
              "font-mono text-[10px] uppercase tracking-[0.28em] flex items-center gap-1.5 " +
              (playing ? "text-rust" : isMine ? "text-ink" : "text-muted2")
            }
            data-testid={`turn-speaker-${turn.index}`}
          >
            {turn.speaker}
            {isMine ? (
              <span
                className="inline-flex items-center gap-1 text-[9px] tracking-[0.24em] text-ink bg-[#E5E1D8] px-1.5 py-0.5"
                data-testid={`turn-you-badge-${turn.index}`}
              >
                <Mic size={9} /> You
              </span>
            ) : null}
          </div>
        ) : (
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 italic">
            {isNarration ? "Narration" : ""}
          </div>
        )}
        {playing && !waitingForUser ? (
          <span className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.22em] text-rust">
            <Volume2 size={12} /> Now speaking
          </span>
        ) : null}
        {waitingForUser ? (
          <span className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.22em] text-ink">
            <Mic size={12} /> Your turn — speak now
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
