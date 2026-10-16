import React, { useCallback, useEffect, useState } from "react";
import { Mic, Square, Play, Volume2, RotateCcw, Loader2, Sparkles } from "lucide-react";
import { useRecorder } from "@/lib/useRecorder";
import { assessPronunciation, fetchPracticeStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import PractiseFeedback from "./PractiseFeedback";

const SUPPORTED = typeof window !== "undefined" && !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);

function micMessage(err) {
  const n = err?.name || "";
  if (n === "NotAllowedError" || n === "SecurityError") return "Microphone access was blocked. Allow the mic for this site in your browser settings, then try again.";
  if (n === "NotFoundError" || n === "DevicesNotFoundError") return "No microphone was found. Plug one in or check your system sound settings.";
  if (n === "NotReadableError") return "Your microphone is in use by another app. Close it and try again.";
  return "We couldn't start the microphone. Please try again.";
}

// "Practise This Word" — sits under the word result. Audio stays in the browser
// until Analyse is pressed; the server deletes it after scoring.
export default function PractiseWord({ word, onHearReference, referencePlaying, canHearReference = true }) {
  const { openPaywall } = useAuth();
  const [enabled, setEnabled] = useState(null);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [analysing, setAnalysing] = useState(false);
  const onMicError = useCallback((err) => setError(micMessage(err)), []);
  const rec = useRecorder({ onError: onMicError });

  // New word → clear the previous take and verdict; ask whether a trial user already used this word.
  useEffect(() => {
    rec.reset(); setResult(null); setError(null); setLocked(false);
    let alive = true;
    fetchPracticeStatus(word)
      .then((s) => { if (alive) { setEnabled(!!s.enabled); setLocked(!!s.locked); } })
      .catch(() => { if (alive) setEnabled(false); });
    return () => { alive = false; };
  }, [word]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!enabled || !word) return null;

  const startRecording = () => { setError(null); setResult(null); rec.start(); };

  const analyse = async () => {
    if (!rec.blob) return;
    if (locked) { openPaywall("practice"); return; }
    setAnalysing(true); setError(null); setResult(null);
    try {
      const r = await assessPronunciation(word, rec.blob);
      setResult(r);
      if (r.trial_locked) setLocked(true);
    } catch (e) {
      const status = e?.response?.status;
      if (status === 402) { setLocked(true); return; } // join popup opened by the global handler
      if (status === 401) return;
      const detail = e?.response?.data?.detail;
      if (status === 429) setError("You've reached the practice limit for this hour. Keep listening and try again a little later.");
      else if (typeof detail === "string") setError(detail);
      else if (!status) setError("We couldn't reach the server. Check your connection and try again.");
      else setError("Analysis failed. Please try again.");
    } finally {
      setAnalysing(false);
    }
  };

  const busy = rec.recording || rec.processing || analysing;

  return (
    <section className="mt-6 border thin-rule bg-surface animate-fade-in shadow-[0_30px_80px_-40px_rgba(0,0,0,0.9)]" data-testid="practise-panel">
      <div className="px-5 sm:px-8 py-6 sm:py-7">
        <h2 className="font-display font-bold text-2xl sm:text-3xl text-ink leading-tight tracking-tight">
          Practise This Word<span className="text-rust">.</span>
        </h2>
        <p className="mt-2 font-serif text-base text-muted2 max-w-2xl">
          Record yourself saying <span className="text-ink font-typewriter">{word}</span>, compare it with the American version, then get a score and sound-by-sound feedback.
        </p>

        {!SUPPORTED ? (
          <div className="mt-5 border thin-rule bg-paper px-4 py-3 font-serif text-sm text-ink" data-testid="practise-unsupported">
            Recording isn't supported in this browser. Try the latest Chrome, Safari, Edge or Firefox.
          </div>
        ) : (
          <>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              {!rec.recording ? (
                <button type="button" onClick={startRecording} disabled={rec.processing || analysing} className="btn-primary" data-testid="practise-record">
                  {rec.blob ? <><RotateCcw size={13} /> Record again</> : <><Mic size={13} /> Record</>}
                </button>
              ) : (
                <button type="button" onClick={rec.stop} className="btn-primary !bg-crimson" data-testid="practise-stop">
                  <Square size={13} /> Stop
                </button>
              )}
              {rec.recording ? (
                <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-crimson inline-flex items-center gap-2" data-testid="practise-recording-indicator"><span className="tally" /> Recording — say the word, then press Stop</span>
              ) : rec.processing ? (
                <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted2 inline-flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Trimming…</span>
              ) : null}
              {rec.blobUrl && !rec.recording ? (
                <button type="button" onClick={() => new Audio(rec.blobUrl).play()} disabled={busy} className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule hover:bg-ink hover:text-surface inline-flex items-center gap-2 disabled:opacity-60" data-testid="practise-play-take">
                  <Play size={12} /> Play my take
                </button>
              ) : null}
              {canHearReference ? (
                <button type="button" onClick={onHearReference} disabled={referencePlaying || rec.recording} className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule hover:bg-ink hover:text-surface inline-flex items-center gap-2 disabled:opacity-60" data-testid="practise-hear-reference">
                  {referencePlaying ? <Loader2 size={12} className="animate-spin" /> : <Volume2 size={12} />} Hear the American version
                </button>
              ) : null}
            </div>

            {rec.blob && !rec.recording ? (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button type="button" onClick={analyse} disabled={busy} className="btn-primary" data-testid={locked ? "practise-join" : "practise-analyse"}>
                  {analysing ? <><Loader2 size={13} className="animate-spin" /> Analysing…</>
                    : locked ? <><Sparkles size={13} /> Join Pronounce This to keep practising</>
                    : <><Sparkles size={13} /> Analyse My Pronunciation</>}
                </button>
                <span className="font-serif text-xs text-muted2">
                  {locked ? "Free trial includes one pronunciation check per word." : "Happy with your take? Nothing is sent until you press Analyse."}
                </span>
              </div>
            ) : null}
          </>
        )}

        {error ? <div className="mt-4 border border-crimson/40 bg-paper px-4 py-3 font-serif text-sm text-crimson" data-testid="practise-error">{error}</div> : null}
        <PractiseFeedback result={result} />
      </div>
    </section>
  );
}
