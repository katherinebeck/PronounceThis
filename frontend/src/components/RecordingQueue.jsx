import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Mic, Square, Play, Check, SkipForward, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { useRecorder } from "@/lib/useRecorder";

// Admin: words students heard as synthetic audio, most-played first.
// Record each from the mic → saved as a permanent manual override.
export function RecordingQueue() {
  const [words, setWords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { recording, processing, blob, blobUrl, start, stop, reset } = useRecorder();
  const current = words[0];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/recording-queue");
      setWords(data.words || []);
    } catch {
      setWords([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!current || !blob) return;
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("word", current.word);
      fd.append("ipa", current.ipa || "");
      fd.append("file", blob, `${current.word}.wav`);
      await api.post("/admin/dictionary/entry", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Saved your recording of “${current.word}”`);
      reset();
      setWords((w) => w.slice(1));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const skip = async () => {
    if (!current) return;
    try {
      await api.post("/admin/recording-queue/dismiss", { word: current.word });
      reset();
      setWords((w) => w.slice(1));
    } catch {
      toast.error("Could not skip");
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-recording-queue">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Recording queue
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Record the words students actually hear
      </h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Every word a student played as synthetic audio lands here, most-played first.
        Record it once from your mic and your voice replaces the computer voice for everyone.
      </p>

      {loading ? (
        <div className="font-mono text-xs text-muted2 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Loading…</div>
      ) : !current ? (
        <div className="font-serif text-base text-muted2 italic" data-testid="recording-queue-empty">
          Queue is empty — every played word has your recording.
        </div>
      ) : (
        <div className="border thin-rule bg-paper p-5" data-testid="recording-queue-current">
          <div className="flex items-baseline justify-between gap-4 flex-wrap">
            <div>
              <div className="font-display text-4xl text-ink leading-none" data-testid="recording-queue-word">{current.word}</div>
              <div className="font-mono text-lg text-rust mt-2">{current.ipa || "—"}</div>
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 text-right">
              Played {current.count}× · {words.length} in queue
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {!recording ? (
              <button type="button" onClick={start} disabled={processing} className="btn-primary justify-center" data-testid="recording-queue-record">
                <Mic size={14} /> {blob ? "Re-record" : "Record"}
              </button>
            ) : (
              <button type="button" onClick={stop} className="btn-primary justify-center !bg-crimson !text-ink" data-testid="recording-queue-stop">
                <Square size={14} /> Stop
              </button>
            )}
            {blobUrl ? (
              <>
                <button
                  type="button"
                  onClick={() => new Audio(blobUrl).play()}
                  className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule hover:bg-ink hover:text-surface inline-flex items-center gap-2"
                  data-testid="recording-queue-preview"
                >
                  <Play size={12} /> Listen
                </button>
                <button
                  type="button"
                  disabled={saving}
                  onClick={save}
                  className="btn-primary justify-center"
                  data-testid="recording-queue-save"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Save &amp; next
                </button>
                <button type="button" onClick={reset} className="text-muted2 hover:text-ink p-2" title="Discard" data-testid="recording-queue-discard">
                  <RotateCcw size={14} />
                </button>
              </>
            ) : null}
            <button
              type="button"
              onClick={skip}
              className="ml-auto font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 text-muted2 hover:text-ink inline-flex items-center gap-2"
              data-testid="recording-queue-skip"
            >
              Skip <SkipForward size={12} />
            </button>
          </div>
          {recording ? (
            <div className="mt-3 font-mono text-[10px] uppercase tracking-[0.22em] text-crimson inline-flex items-center gap-2"><span className="tally" /> Recording — say the word, then Stop</div>
          ) : processing ? (
            <div className="mt-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Trimming clicks and silence…</div>
          ) : null}
        </div>
      )}

      {words.length > 1 ? (
        <div className="mt-4 flex flex-wrap gap-2" data-testid="recording-queue-upcoming">
          {words.slice(1, 13).map((w) => (
            <span key={w.word} className="font-mono text-[11px] px-2 py-1 border thin-rule text-muted2">
              {w.word} <span className="text-ink/60">×{w.count}</span>
            </span>
          ))}
          {words.length > 13 ? <span className="font-mono text-[11px] px-2 py-1 text-muted2">+{words.length - 13} more</span> : null}
        </div>
      ) : null}
    </section>
  );
}
