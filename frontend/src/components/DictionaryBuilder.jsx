import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square, Play, Check, SkipForward, RotateCcw, ArrowRight, Undo2, ArrowLeft, Volume2 } from "lucide-react";
import { api, fetchTTS } from "@/lib/api";
import { toast } from "sonner";
import { useRecorder } from "@/lib/useRecorder";
import { IpaPalette } from "./IpaPalette";
import { DictionaryTable } from "./DictionaryTable";

const inputCls =
  "w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink";

const LISTS = [
  { id: "dictionary", label: "Dictionary", hint: "Jump to any word (e.g. oner)" },
  { id: "names", label: "First names", hint: "Search a first name (e.g. Siobhan)" },
  { id: "surnames", label: "Surnames", hint: "Search a surname (e.g. Nguyen)" },
  { id: "places", label: "US places", hint: "Search a state or city (e.g. Worcester)" },
  { id: "countries", label: "Countries", hint: "Search a country or capital (e.g. Qatar)" },
  { id: "chains", label: "Brands & chains", hint: "Search a brand (e.g. Wawa)" },
];

// Admin: walk the CMU dictionary (or a curated list) one word at a time,
// record each word and confirm its IPA.
export function DictionaryBuilder() {
  const [list, setList] = useState(localStorage.getItem("dict_list") || "dictionary");
  const [history, setHistory] = useState([]); // words visited, for Back
  const [playing, setPlaying] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [words, setWords] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [ipa, setIpa] = useState("");
  const [saving, setSaving] = useState(false);
  const [jump, setJump] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const ipaRef = useRef(null);
  const rec = useRecorder();
  const current = words[0];

  const load = useCallback(async (start, includeStart = false) => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/dictionary/queue", { params: { start: start || undefined, limit: 12, list, include_start: includeStart || undefined } });
      setWords(data.words || []);
      setStats(data.stats || null);
    } catch {
      setWords([]);
    } finally {
      setLoading(false);
    }
  }, [list]);

  useEffect(() => {
    localStorage.setItem("dict_list", list);
    load(localStorage.getItem(`dict_cursor_${list}`) || undefined);
  }, [load, list]);
  useEffect(() => { setIpa(current?.ipa || ""); rec.reset(); }, [current?.word]); // eslint-disable-line react-hooks/exhaustive-deps

  const advance = () => {
    if (current) setHistory((h) => [...h.slice(-49), current.word]);
    setWords((w) => {
      const rest = w.slice(1);
      if (rest[0]) localStorage.setItem(`dict_cursor_${list}`, rest[0].word);
      if (rest.length < 4) load(rest[rest.length - 1]?.word || w[0]?.word);
      return rest;
    });
  };

  const save = async () => {
    if (!current || saving || rec.recording || rec.processing) return;
    if (!ipa.trim() && !rec.blob) { toast.error("Type the IPA or record a take first"); return; }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("word", current.word);
      fd.append("ipa", ipa.trim());
      if (!ipa.trim() && !rec.blob) return;
      if (rec.blob) fd.append("file", rec.blob, `${current.word}.wav`);
      await api.post("/admin/dictionary/entry", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(rec.blob
        ? `Saved “${current.word}” — your take is now re-voiced by ElevenLabs for members`
        : `Saved “${current.word}”`);
      setRefreshKey((k) => k + 1);
      advance();
    } catch (e) {
      toast.error(e?.response?.data?.detail === "invalid_ipa" ? "That IPA has characters I don't recognise" : e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const skip = async () => {
    if (!current) return;
    try {
      await api.post("/admin/dictionary/skip", { word: current.word });
      advance();
    } catch {
      toast.error("Could not skip");
    }
  };

  const revert = async () => {
    if (!current) return;
    const drop = window.confirm(`Revert “${current.word}” to the stock dictionary pronunciation?\n\nOK = also discard any recording of yours · Cancel = keep the recording, only remove IPA/stress changes`);
    try {
      const r = await api.post("/admin/dictionary/revert", { word: current.word, drop_recording: drop });
      toast.success(`“${current.word}” reverted${r.data.ipa ? ` to ${r.data.ipa}` : ""} — the next play re-renders it`);
      setIpa(r.data.ipa || "");
      setRefreshKey((k) => k + 1);
    } catch {
      toast.error("Could not revert");
    }
  };

  const doJump = (e) => {
    e.preventDefault();
    const w = jump.trim().toLowerCase();
    if (!w) return;
    if (current) setHistory((h) => [...h.slice(-49), current.word]);
    localStorage.setItem(`dict_cursor_${list}`, w);
    load(w, true);
    setJump("");
  };

  const goBack = () => {
    const prev = history[history.length - 1];
    if (!prev) return;
    setHistory((h) => h.slice(0, -1));
    load(prev, true);
  };

  const hear = async () => {
    if (!current || playing) return;
    setPlaying(true);
    try {
      const { audio_b64, mime } = await fetchTTS(current.word);
      const a = new Audio(`data:${mime || "audio/mpeg"};base64,${audio_b64}`);
      a.onended = () => setPlaying(false);
      a.onerror = () => setPlaying(false);
      await a.play();
    } catch {
      setPlaying(false);
      toast.error("Couldn't play that word right now.");
    }
  };

  const undo = async () => {
    if (undoing) return;
    setUndoing(true);
    try {
      const { data } = await api.post("/admin/dictionary/undo");
      toast.success(`Undid your last change to “${data.word}”`);
      setRefreshKey((k) => k + 1);
      load(data.word, true);
    } catch (e) {
      toast.error(e?.response?.data?.detail === "nothing_to_undo" ? "Nothing to undo" : "Undo failed");
    } finally {
      setUndoing(false);
    }
  };

  useEffect(() => {
    const onKey = (e) => {
      const t = e.target;
      const typing = (t.tagName === "INPUT" || t.tagName === "TEXTAREA") && !t.dataset.ipaInput;
      if (typing || !current) return;
      if (e.code === "Space") { e.preventDefault(); rec.toggle(); }
      else if (e.key === "Enter") { e.preventDefault(); save(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // re-bind each render so handlers see fresh state

  const pct = stats ? Math.min(100, ((stats.done + stats.skipped) / stats.total) * 100) : 0;

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-dictionary">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">My dictionary</div>
      <h2 className="font-display text-2xl text-ink mb-4">Check the dictionary, one word at a time</h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Words come A→Z from the CMU dictionary with their IPA filled in — edit it if you disagree, or jump
        to any word below. Names and words that aren't in the dictionary (e.g. <span className="not-italic text-ink">oner</span>) work too: jump to them, type the IPA and/or record. <span className="text-ink not-italic">Members always hear the ElevenLabs voice</span>,
        pronounced exactly as your IPA says; your own recording is kept only as a reference for you.
        Press <kbd className="font-mono not-italic">Space</kbd> to start/stop recording and <kbd className="font-mono not-italic">Enter</kbd> to save.
      </p>

      {stats ? (
        <div className="mb-5" data-testid="dictionary-progress">
          <div className="flex justify-between font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mb-1">
            <span>{stats.recorded.toLocaleString()} recorded · {stats.done.toLocaleString()} saved · {stats.skipped.toLocaleString()} skipped</span>
            <span>{stats.total.toLocaleString()} words</span>
          </div>
          <div className="h-1 bg-paper border thin-rule"><div className="h-full bg-rust" style={{ width: `${Math.max(pct, 0.3)}%` }} /></div>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1 mb-4" data-testid="dictionary-lists">
        {LISTS.map((l) => (
          <button key={l.id} type="button" onClick={() => { setList(l.id); setHistory([]); }}
                  className={"font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule " + (list === l.id ? "bg-ink text-surface" : "text-muted2 hover:text-ink")}
                  data-testid={`dictionary-list-${l.id}`}>{l.label}</button>
        ))}
      </div>

      <form onSubmit={doJump} className="flex gap-2 mb-3">
        <input type="text" value={jump} onChange={(e) => setJump(e.target.value)} placeholder={LISTS.find((l) => l.id === list)?.hint} className={inputCls} data-testid="dictionary-jump" />
        <button type="submit" className="btn-primary justify-center" data-testid="dictionary-jump-go"><ArrowRight size={14} /> Go</button>
      </form>
      <div className="flex gap-2 mb-5">
        <button type="button" onClick={goBack} disabled={!history.length} className="btn-secondary disabled:opacity-40" data-testid="dictionary-back"><ArrowLeft size={12} /> Back to previous word</button>
        <button type="button" onClick={undo} disabled={undoing} className="btn-secondary disabled:opacity-40" data-testid="dictionary-undo">{undoing ? <Loader2 size={12} className="animate-spin" /> : <Undo2 size={12} />} Undo last change</button>
      </div>

      {loading && !current ? (
        <div className="font-mono text-xs text-muted2 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Loading…</div>
      ) : !current ? (
        <div className="font-serif text-base text-muted2 italic" data-testid="dictionary-done">You've reached the end of this list.</div>
      ) : (
        <div className="border thin-rule bg-paper p-5" data-testid="dictionary-current">
          <div className="flex items-baseline justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-4 flex-wrap">
              <div className="font-display text-5xl text-ink leading-none" data-testid="dictionary-word">{current.word}</div>
              <button type="button" onClick={hear} disabled={playing} className="btn-secondary disabled:opacity-50" title="Hear how the app says it right now" data-testid="dictionary-hear">
                {playing ? <Loader2 size={12} className="animate-spin" /> : <Volume2 size={12} />} Hear it
              </button>
              {current.label && current.label.toLowerCase() !== current.word ? (
                <span className="font-serif text-sm text-muted2 italic" data-testid="dictionary-label">from “{current.label}”</span>
              ) : null}
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
              {rec.recording ? <span className="text-crimson inline-flex items-center gap-2"><span className="tally" /> Recording</span> : rec.processing ? "Cleaning up…" : rec.blob ? "Take ready" : "Space to record"}
            </div>
          </div>

          <div className="mt-4">
            <label className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 block mb-1">
              IPA {current.ipa ? <span className="text-muted2/70">· from dictionary: {current.ipa}</span> : <span className="text-rust">· not in dictionary — type it</span>}
            </label>
            <input
              ref={ipaRef}
              type="text"
              value={ipa}
              onChange={(e) => setIpa(e.target.value)}
              data-ipa-input="1"
              className={`${inputCls} font-mono text-2xl text-rust`}
              data-testid="dictionary-ipa"
            />
            <div className="mt-2"><IpaPalette inputRef={ipaRef} value={ipa} onChange={setIpa} /></div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {!rec.recording ? (
              <button type="button" onClick={rec.start} disabled={rec.processing} className="btn-primary justify-center" data-testid="dictionary-record">
                <Mic size={14} /> {rec.blob ? "Re-record" : "Record"}
              </button>
            ) : (
              <button type="button" onClick={rec.stop} className="btn-primary justify-center !bg-crimson !text-ink" data-testid="dictionary-stop">
                <Square size={14} /> Stop
              </button>
            )}
            {rec.blobUrl ? (
              <>
                <button type="button" onClick={() => new Audio(rec.blobUrl).play()} className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule hover:bg-ink hover:text-surface inline-flex items-center gap-2" data-testid="dictionary-preview">
                  <Play size={12} /> Listen
                </button>
                <button type="button" onClick={rec.reset} className="text-muted2 hover:text-ink p-2" title="Discard take" data-testid="dictionary-discard"><RotateCcw size={14} /></button>
              </>
            ) : null}
            <button type="button" disabled={saving || rec.recording || rec.processing} onClick={save} className="btn-primary justify-center" data-testid="dictionary-save">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Save &amp; next
            </button>
            <button type="button" onClick={revert} className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 text-muted2 hover:text-ink inline-flex items-center gap-2" title="Remove your IPA/stress changes for this word" data-testid="dictionary-revert">
              <Undo2 size={12} /> Revert to dictionary
            </button>
            <button type="button" onClick={skip} className="ml-auto font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 text-muted2 hover:text-ink inline-flex items-center gap-2" data-testid="dictionary-skip">
              Skip <SkipForward size={12} />
            </button>
          </div>
        </div>
      )}

      {words.length > 1 ? (
        <div className="mt-4 flex flex-wrap gap-2" data-testid="dictionary-upcoming">
          {words.slice(1, 12).map((w) => (
            <span key={w.word} className="font-mono text-[11px] px-2 py-1 border thin-rule text-muted2">{w.word}</span>
          ))}
        </div>
      ) : null}

      <DictionaryTable refreshKey={refreshKey} />
    </section>
  );
}
