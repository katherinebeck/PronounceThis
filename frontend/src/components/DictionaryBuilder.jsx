import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square, Play, Check, SkipForward, RotateCcw, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useRecorder } from "@/lib/useRecorder";
import { IpaPalette } from "./IpaPalette";
import { DictionaryTable } from "./DictionaryTable";

const inputCls =
  "w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink";

// Admin: walk the CMU dictionary A→Z, record each word and confirm its IPA.
export function DictionaryBuilder() {
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

  const load = useCallback(async (start) => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/dictionary/queue", { params: { start: start || undefined, limit: 12 } });
      setWords(data.words || []);
      setStats(data.stats || null);
    } catch {
      setWords([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(localStorage.getItem("dict_cursor") || undefined); }, [load]);
  useEffect(() => { setIpa(current?.ipa || ""); rec.reset(); }, [current?.word]); // eslint-disable-line react-hooks/exhaustive-deps

  const advance = () => {
    setWords((w) => {
      const rest = w.slice(1);
      if (rest[0]) localStorage.setItem("dict_cursor", rest[0].word);
      if (rest.length < 4) load(rest[rest.length - 1]?.word || w[0]?.word);
      return rest;
    });
  };

  const save = async () => {
    if (!current || saving || rec.recording || rec.processing) return;
    if (!ipa.trim()) { toast.error("Type the IPA first"); return; }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("word", current.word);
      fd.append("ipa", ipa.trim());
      if (rec.blob) fd.append("file", rec.blob, `${current.word}.wav`);
      await api.post("/admin/dictionary/entry", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Saved “${current.word}”${rec.blob ? " with your recording" : ""}`);
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

  const doJump = (e) => {
    e.preventDefault();
    const w = jump.trim().toLowerCase();
    if (!w) return;
    localStorage.setItem("dict_cursor", w);
    load(w);
    setJump("");
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
      <h2 className="font-display text-2xl text-ink mb-4">Record the dictionary, one word at a time</h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Words come A→Z from the CMU dictionary with their IPA filled in — edit it if you disagree.
        Press <kbd className="font-mono not-italic">Space</kbd> to start/stop recording and <kbd className="font-mono not-italic">Enter</kbd> to save.
        Clicks and silence at the edges are trimmed automatically.
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

      <form onSubmit={doJump} className="flex gap-2 mb-5">
        <input type="text" value={jump} onChange={(e) => setJump(e.target.value)} placeholder="Jump to a word (e.g. because)" className={inputCls} data-testid="dictionary-jump" />
        <button type="submit" className="btn-primary justify-center" data-testid="dictionary-jump-go"><ArrowRight size={14} /> Go</button>
      </form>

      {loading && !current ? (
        <div className="font-mono text-xs text-muted2 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Loading…</div>
      ) : !current ? (
        <div className="font-serif text-base text-muted2 italic" data-testid="dictionary-done">You've reached the end of the dictionary.</div>
      ) : (
        <div className="border thin-rule bg-paper p-5" data-testid="dictionary-current">
          <div className="flex items-baseline justify-between gap-4 flex-wrap">
            <div className="font-display text-5xl text-ink leading-none" data-testid="dictionary-word">{current.word}</div>
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
