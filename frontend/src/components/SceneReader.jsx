import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Play,
  Pause,
  Square,
  Loader2,
  Volume2,
  User,
  ChevronDown,
  Download,
  ArrowLeft,
} from "lucide-react";
import WordBlock from "./WordBlock";
import YouglishModal from "./CaptionSearchModal";
import GuidedNextStep from "./GuidedNextStep";
import { useAuth } from "@/lib/auth";
import { loadTurnAudio, withRetry } from "@/lib/audio";
import { fetchReaderVoices, downloadMyLines, fetchTurnTTS } from "@/lib/api";
import { toast } from "sonner";

// Pause between successive "Play My Lines" lines (same character).
const PAUSE_BETWEEN_MY_LINES_MS = 600;

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

// Persist the coach's per-scene picks (character + voice) so re-opening
// a scene remembers them. Scoped per browser.
function usePersistedScenePrefs(sceneId) {
  const key = sceneId ? `scene_prefs::${sceneId}` : null;
  const [prefs, setPrefs] = useState({ character: null, voice: null });
  useEffect(() => {
    if (!key) return;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw) setPrefs(JSON.parse(raw));
      else setPrefs({ character: null, voice: null });
    } catch (e) {
      console.warn("Could not load scene prefs from localStorage", e);
      setPrefs({ character: null, voice: null });
    }
  }, [key]);
  const update = (patch) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      if (key) {
        try {
          window.localStorage.setItem(key, JSON.stringify(next));
        } catch (e) {
          console.warn("Could not persist scene prefs", e);
        }
      }
      return next;
    });
  };
  return [prefs, update];
}

export default function SceneReader({ scene, highlightSet }) {
  const { isGuidedTrial, guidedDone, me, refresh, openPaywall } = useAuth();
  const [activeIdx, setActiveIdx] = useState(null);
  const [playingTurn, setPlayingTurn] = useState(null); // int | null
  const [loadingTurn, setLoadingTurn] = useState(null);
  const [running, setRunning] = useState(false);
  const [readerRunning, setReaderRunning] = useState(false);
  const [bundleProgress, setBundleProgress] = useState(null); // {mode, done, total}
  const [downloading, setDownloading] = useState(false);
  const [downloadingReader, setDownloadingReader] = useState(false);
  const [ygQuery, setYgQuery] = useState(null);
  const [voices, setVoices] = useState([]);
  const [prefs, setPrefs] = usePersistedScenePrefs(scene?.id);
  const audioRef = useRef(null);
  const stopRef = useRef(false);

  // Load available voices once.
  useEffect(() => {
    fetchReaderVoices()
      .then(setVoices)
      .catch(() => setVoices([]));
  }, []);

  // A saved voice that no longer exists (e.g. after a voice swap) falls back to default.
  useEffect(() => {
    if (voices.length && prefs.voice && !voices.some((v) => v.key === prefs.voice)) {
      setPrefs({ voice: null });
    }
  }, [voices, prefs.voice, setPrefs]);

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

  // Guided trial, sample scene: one on-screen pointer at a time until they've heard a line.
  const coachHint =
    scene.is_sample && isGuidedTrial && !guidedDone.scene
      ? (prefs.character ? "play" : "character")
      : null;

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
    setRunning(false);
    setReaderRunning(false);
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
      // Guided trial step 02 is complete once a line has been fetched — don't wait for playback to end.
      if (scene.is_sample && isGuidedTrial && !me?.sample_scene_explored) refresh();
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
      await playOneTurn(turnIndex, { voice: prefs.voice });
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
      stopEverything();
    }
  };

  const handlePlayMyLines = async () => {
    if (running) {
      stopEverything();
      return;
    }
    if (!prefs.character) {
      toast.error("Pick your character first.");
      return;
    }
    stopEverything();
    stopRef.current = false;
    setRunning(true);
    try {
      const mine = grouped.filter((t) => t.speaker === prefs.character);
      if (!mine.length) {
        toast.error(`No lines found for ${prefs.character}.`);
        return;
      }
      for (let i = 0; i < mine.length; i++) {
        if (stopRef.current) break;
        if (i > 0) {
          await new Promise((r) => setTimeout(r, PAUSE_BETWEEN_MY_LINES_MS));
          if (stopRef.current) break;
        }
        await playOneTurn(mine[i].index, { voice: prefs.voice });
      }
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
    } finally {
      setRunning(false);
      setPlayingTurn(null);
    }
  };

  const handlePlayReaderLines = async () => {
    if (readerRunning) {
      stopEverything();
      return;
    }
    if (!prefs.character) {
      toast.error("Pick your character first.");
      return;
    }
    stopEverything();
    stopRef.current = false;
    setReaderRunning(true);
    try {
      for (const turn of grouped) {
        if (stopRef.current) break;
        if (turn.speaker === prefs.character) {
          // Leave room for me to say my line: ~0.42s per word, plus a beat.
          const words = (turn.text || "").split(/\s+/).filter(Boolean).length;
          await new Promise((r) => setTimeout(r, Math.round(words * 420 * 1.1) + 400));
          continue;
        }
        await playOneTurn(turn.index, { voice: readerVoice });
        await new Promise((r) => setTimeout(r, 400));
      }
    } catch (e) {
      toast.error(e.friendly || "Playback failed.");
    } finally {
      setReaderRunning(false);
      setPlayingTurn(null);
    }
  };

  const downloadBundle = async (mode) => {
    if (isGuidedTrial) {
      openPaywall("unlock");
      return;
    }
    if (!prefs.character) {
      toast.error("Pick your character first.");
      return;
    }
    const setBusy = mode === "reader" ? setDownloadingReader : setDownloading;
    setBusy(true);
    try {
      // Pre-warm each line as its own short request (3 at a time) so the
      // bundle call only has to stitch cached audio — no proxy timeouts.
      const voice = mode === "reader" ? readerVoice : prefs.voice;
      const wanted = mode === "reader"
        ? grouped.filter((t) => t.speaker !== prefs.character)
        : grouped.filter((t) => t.speaker === prefs.character);
      let done = 0;
      setBundleProgress({ mode, done, total: wanted.length });
      const queue = [...wanted];
      const worker = async () => {
        while (queue.length) {
          const turn = queue.shift();
          await withRetry(() => fetchTurnTTS(scene.id, turn.index, { voice }));
          done += 1;
          setBundleProgress({ mode, done, total: wanted.length });
        }
      };
      await Promise.all(Array.from({ length: Math.min(3, queue.length) }, worker));
      setBundleProgress(null);
      const { blob, filename } = await withRetry(() => downloadMyLines(scene.id, {
        character: prefs.character,
        voice,
        mode,
      }));
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Give the browser a beat to start the download, then release the URL.
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast.success(
        mode === "reader"
          ? `Downloaded your reader track — the other characters speak, you fill the gaps.`
          : `Downloaded ${prefs.character}'s lines.`
      );
    } catch (e) {
      const msg =
        e?.response?.data?.detail ||
        e.friendly ||
        e.message ||
        "Download failed.";
      toast.error(msg);
    } finally {
      setBusy(false);
      setBundleProgress(null);
    }
  };
  // Reader defaults to the voice I'm not using, so partner lines sound like
  // a different person.
  const readerVoice =
    prefs.readerVoice ||
    voices.find((v) => v.key !== (prefs.voice || voices[0]?.key))?.key ||
    prefs.voice;
  const handleDownloadMyLines = () => downloadBundle("mine");
  const handleDownloadReaderLines = () => downloadBundle("reader");

  if (!scene) return null;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-paper">
      <div className="px-4 sm:px-6 lg:px-10 xl:px-14 pt-6 sm:pt-8 pb-4 sm:pb-5 border-b thin-rule">
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
            <span data-testid="scene-stat-words">{stats.total} words</span>
            <span data-testid="scene-stat-ipa">
              {stats.transcribed} transcribed in IPA
            </span>
            <span data-testid="scene-stat-turns">
              {grouped.length} {grouped.length === 1 ? "turn" : "turns"}
            </span>
          </div>
        </div>

        {/* Practice controls, grouped: (1) my lines (2) reader track. */}
        {speakers.length > 0 ? (
          <div className="mt-5 flex flex-col gap-3 max-w-[78ch]" data-testid="scene-controls">
            <section className="border thin-rule bg-surface/60 p-4 flex flex-col gap-3" data-testid="my-lines-panel">
              <div className="flex items-baseline justify-between gap-3">
                <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust whitespace-nowrap">My Lines</div>
                <div className="font-serif text-xs text-muted2 italic hidden sm:block">Hear only your character, in the voice you pick.</div>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <CharacterPicker
                  speakers={speakers}
                  value={prefs.character}
                  onChange={(c) => setPrefs({ character: c })}
                />
                {coachHint === "character" ? <GuidedHint text="Start here — choose your character" /> : null}
                <VoicePicker
                  voices={voices}
                  value={prefs.voice}
                  onChange={(v) => setPrefs({ voice: v })}
                  label="My voice"
                />
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  className={"btn-primary " + (running ? "!bg-rust" : "")}
                  onClick={handlePlayMyLines}
                  data-testid="play-my-lines-button"
                >
                  {running ? (
                    <><Square size={12} fill="currentColor" /> Stop</>
                  ) : (
                    <><Play size={12} fill="currentColor" /> Play My Lines</>
                  )}
                </button>
                {coachHint === "play" ? <GuidedHint text="Now play the dialogue" /> : null}
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleDownloadMyLines}
                  data-testid="download-my-lines-button"
                  disabled={downloading || running || readerRunning}
                  title="Download every one of your character's lines as a single MP3 (with a 2-second pause between lines) for offline drilling"
                >
                  {downloading ? (
                    <><Loader2 size={12} className="animate-spin" /> {bundleProgress?.mode === "mine" ? `Preparing ${bundleProgress.done}/${bundleProgress.total}` : "Bundling"}</>
                  ) : (
                    <><Download size={12} /> Download My Lines</>
                  )}
                </button>
              </div>
            </section>

            <section className="border thin-rule bg-surface/60 p-4 flex flex-col gap-3" data-testid="reader-panel">
              <div className="flex items-baseline justify-between gap-3">
                <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust whitespace-nowrap">Reader's Lines</div>
                <div className="font-serif text-xs text-muted2 italic hidden sm:block">Download the other character's lines to use as practice as you rehearse speaking your lines.</div>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <VoicePicker
                  voices={voices}
                  value={readerVoice}
                  onChange={(v) => setPrefs({ readerVoice: v })}
                  label="Reader's voice"
                  testId="reader-voice-picker"
                />
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  className={"btn-primary " + (readerRunning ? "!bg-rust" : "")}
                  onClick={handlePlayReaderLines}
                  data-testid="play-reader-lines-button"
                  disabled={downloadingReader || running}
                  title="Hear the other characters' lines in order, with a pause where your lines go"
                >
                  {readerRunning ? (
                    <><Square size={12} fill="currentColor" /> Stop</>
                  ) : (
                    <><Play size={12} fill="currentColor" /> Play My Reader's Lines</>
                  )}
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleDownloadReaderLines}
                  data-testid="download-reader-lines-button"
                  disabled={downloadingReader || running || readerRunning}
                  title="Download the other characters' lines as one MP3, with silence where your lines go (10% longer than it takes to say them) so you can rehearse against it"
                >
                  {downloadingReader ? (
                    <><Loader2 size={12} className="animate-spin" /> {bundleProgress?.mode === "reader" ? `Preparing ${bundleProgress.done}/${bundleProgress.total}` : "Bundling"}</>
                  ) : (
                    <><Download size={12} /> Download My Reader's Lines</>
                  )}
                </button>
              </div>
            </section>
          </div>
        ) : null}
      </div>

      <div
        className="flex-1 overflow-auto scrollbar-thin px-4 sm:px-6 lg:px-10 xl:px-14 py-6 sm:py-8 animate-fade-in"
        data-testid="scene-reader"
      >
        {scene.is_sample && isGuidedTrial && guidedDone.scene ? <GuidedNextStep mode="unlock" /> : null}
        <div className="max-w-[78ch] flex flex-col gap-8">
          {grouped.map((turn) => {
            const isMine = prefs.character && turn.speaker === prefs.character;
            const dimOthers =
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
                onOpenReference={setYgQuery}
                sceneId={scene.id}
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

const pickerCls =
  "flex items-center gap-3 border border-ink/40 bg-elevated px-4 py-3 hover:border-rust focus-within:border-rust transition-colors";

// Pointer pill that sits beside a control during the guided trial.
function GuidedHint({ text }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 bg-rust text-stage font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-2 whitespace-nowrap animate-fade-in motion-safe:animate-pulse"
      data-testid="guided-hint"
    >
      <ArrowLeft size={11} strokeWidth={2.5} />
      {text}
    </span>
  );
}
const pickerLabel = "font-mono text-[10px] uppercase tracking-[0.24em] text-rust";
const pickerSelect =
  "appearance-none bg-transparent outline-none font-display font-semibold text-base text-ink pr-1 cursor-pointer";

function CharacterPicker({ speakers, value, onChange }) {
  return (
    <label className={pickerCls} data-testid="character-picker-wrap">
      <User size={16} className="text-rust shrink-0" />
      <div className="flex flex-col leading-tight">
        <span className={pickerLabel}>Choose your character</span>
        <span className="inline-flex items-center gap-1">
          <select
            value={value || ""}
            onChange={(e) => onChange(e.target.value || null)}
            className={pickerSelect}
            data-testid="character-picker"
          >
            <option value="">Pick who you're playing…</option>
            {speakers.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <ChevronDown size={14} className="text-muted2" />
        </span>
      </div>
    </label>
  );
}

function VoicePicker({ voices, value, onChange, label = "Choose your scene partner's voice", testId = "voice-picker" }) {
  return (
    <label className={pickerCls} data-testid={`${testId}-wrap`}>
      <Volume2 size={16} className="text-rust shrink-0" />
      <div className="flex flex-col leading-tight">
        <span className={pickerLabel}>{label}</span>
        <span className="inline-flex items-center gap-1">
          <select
            value={value || voices[0]?.key || ""}
            onChange={(e) => onChange(e.target.value || null)}
            className={pickerSelect}
            data-testid={testId}
          >
            {voices.map((v) => (
              <option key={v.key} value={v.key}>{v.label}</option>
            ))}
          </select>
          <ChevronDown size={14} className="text-muted2" />
        </span>
      </div>
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
  onOpenReference,
  sceneId,
}) {
  const isNarration = !turn.speaker;
  return (
    <div
      className={
        "relative group border-l-2 pl-6 py-1 transition-all " +
        (playing
          ? "border-rust bg-[rgba(200,90,79,0.06)]"
          : "border-transparent hover:border-rule") +
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
              ? "bg-rust text-stage border-rust"
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
                className="inline-flex items-center gap-1 text-[9px] tracking-[0.24em] text-ink bg-elevated px-1.5 py-0.5"
                data-testid={`turn-you-badge-${turn.index}`}
              >
                You
              </span>
            ) : null}
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
            key={`${turn.index}:${i}:${tok.text}`}
            token={tok}
            active={activeIdx === `${turn.index}:${i}`}
            highlighted={
              tok.is_word && highlightSet?.has(normalize(tok.text))
            }
            onSetActive={() => onSetActive(`${turn.index}:${i}`)}
            onOpenReference={onOpenReference}
            sceneId={sceneId}
          />
        ))}
      </div>
    </div>
  );
}
