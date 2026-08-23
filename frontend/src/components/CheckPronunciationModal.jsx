import React, { useEffect, useRef, useState } from "react";
import { X, Mic, Square, Check, AlertCircle, RefreshCw } from "lucide-react";

const SR =
  typeof window !== "undefined"
    ? window.SpeechRecognition || window.webkitSpeechRecognition
    : null;

// Loose "close enough" comparison. Case- and punctuation-insensitive; also
// tolerates the plural / possessive tail ("mary's" vs "mary", "bus" vs "buses").
function normalize(s) {
  return (s || "").toLowerCase().replace(/[^a-z]/g, "");
}
function editDistance(a, b) {
  if (a === b) return 0;
  if (!a) return b.length;
  if (!b) return a.length;
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i][0] = i;
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + cost,
      );
    }
  }
  return dp[a.length][b.length];
}
function grade(target, transcript) {
  const t = normalize(target);
  const s = normalize(transcript);
  if (!t || !s) return { level: "miss", note: "We couldn't hear a word." };
  if (t === s) return { level: "match", note: "Nailed it." };
  // Consider first spoken word only when transcript is a phrase.
  const first = s.split(/\s+/)[0] || s;
  if (first === t) return { level: "match", note: "Nailed it." };
  const d = editDistance(t, first);
  const ratio = d / Math.max(t.length, first.length);
  if (ratio <= 0.25) return { level: "close", note: "Very close — try once more." };
  if (ratio <= 0.5) return { level: "off", note: `We heard "${transcript}".` };
  return { level: "miss", note: `We heard "${transcript}".` };
}

/**
 * Modal that records the user via the browser's SpeechRecognition API and
 * compares the transcript against the target word. Runs entirely in the
 * browser (no server round-trip, no extra API cost) and works in Chrome,
 * Edge and Safari. If the API is missing (Firefox, etc.) we surface a
 * graceful fallback message.
 */
export default function CheckPronunciationModal({ open, word, onClose }) {
  const recRef = useRef(null);
  const [state, setState] = useState("idle"); // idle | listening | done | error
  const [transcript, setTranscript] = useState("");
  const [result, setResult] = useState(null);
  const [errorText, setErrorText] = useState("");

  const reset = () => {
    setState("idle");
    setTranscript("");
    setResult(null);
    setErrorText("");
  };

  useEffect(() => {
    if (open) reset();
    return () => {
      if (recRef.current) {
        try {
          recRef.current.stop();
        } catch {
          // recognition may already be stopped — ignore
        }
      }
    };
  }, [open, word]);

  const start = () => {
    if (!SR) {
      setState("error");
      setErrorText(
        "This browser does not support live speech recognition. Try Chrome, Edge, or Safari."
      );
      return;
    }
    reset();
    setState("listening");
    const rec = new SR();
    recRef.current = rec;
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 3;

    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      setTranscript(finalText || interim);
    };
    rec.onerror = (e) => {
      setState("error");
      const map = {
        "not-allowed": "Please allow microphone access to use this feature.",
        "service-not-allowed": "Speech recognition is blocked by the browser.",
        "no-speech": "We didn't hear anything — tap the mic and try again.",
        network: "A network issue interrupted speech recognition.",
      };
      setErrorText(map[e.error] || `Recognition error: ${e.error}`);
    };
    rec.onend = () => {
      const spoken = finalText.trim() || transcript.trim();
      setTranscript(spoken);
      if (spoken) {
        setResult(grade(word, spoken));
      }
      setState((s) => (s === "listening" ? "done" : s));
    };
    try {
      rec.start();
    } catch (e) {
      setState("error");
      setErrorText("Could not start the microphone.");
    }
  };

  const stop = () => {
    if (recRef.current) {
      try {
        recRef.current.stop();
      } catch {
        // recognition may already be finished — ignore
      }
    }
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const levelColor = {
    match: "text-sage",
    close: "text-rust",
    off: "text-rust",
    miss: "text-muted2",
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4 animate-fade-in"
      data-testid="check-pronunciation-modal"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg bg-surface border thin-rule shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 py-5 border-b thin-rule">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
              Check how you say — General American Accent
            </div>
            <div className="font-display text-3xl text-ink mt-1">{word}</div>
          </div>
          <button
            type="button"
            className="text-muted2 hover:text-ink p-1"
            onClick={onClose}
            data-testid="check-close"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-8 py-10 flex flex-col items-center gap-6">
          <button
            type="button"
            className={
              "w-24 h-24 rounded-full border-2 flex items-center justify-center transition-colors " +
              (state === "listening"
                ? "border-rust bg-rust text-white animate-pulse"
                : "border-ink text-ink hover:bg-ink hover:text-surface")
            }
            data-testid="check-mic-button"
            onClick={state === "listening" ? stop : start}
            aria-label={state === "listening" ? "Stop recording" : "Start recording"}
          >
            {state === "listening" ? <Square size={28} /> : <Mic size={30} />}
          </button>
          <div className="text-center min-h-[60px]">
            {state === "idle" && (
              <div className="font-serif text-muted2 italic">
                Tap the mic, then say <span className="text-ink">&quot;{word}&quot;</span>.
              </div>
            )}
            {state === "listening" && (
              <>
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-rust mb-2">
                  Listening…
                </div>
                {transcript && (
                  <div className="font-serif text-xl text-ink">
                    {transcript}
                  </div>
                )}
              </>
            )}
            {state === "done" && result && (
              <>
                <div
                  className={
                    "font-mono text-[10px] uppercase tracking-[0.25em] mb-1 " +
                    (levelColor[result.level] || "text-muted2")
                  }
                  data-testid="check-result-level"
                >
                  {result.level === "match" && (
                    <span className="inline-flex items-center gap-1">
                      <Check size={12} /> Match
                    </span>
                  )}
                  {result.level === "close" && (
                    <span className="inline-flex items-center gap-1">
                      Close
                    </span>
                  )}
                  {(result.level === "off" || result.level === "miss") && (
                    <span className="inline-flex items-center gap-1">
                      <AlertCircle size={12} /> Not quite
                    </span>
                  )}
                </div>
                <div className="font-serif text-lg text-ink" data-testid="check-transcript">
                  {result.note}
                </div>
              </>
            )}
            {state === "error" && (
              <div className="font-serif text-rust" data-testid="check-error">
                {errorText}
              </div>
            )}
          </div>
          {state === "done" || state === "error" ? (
            <button
              type="button"
              className="btn-secondary"
              data-testid="check-retry"
              onClick={start}
            >
              <RefreshCw size={12} /> Try again
            </button>
          ) : null}
        </div>

        <div className="px-6 py-3 border-t thin-rule font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
          Speech recognized locally in your browser · en-US
        </div>
      </div>
    </div>
  );
}
