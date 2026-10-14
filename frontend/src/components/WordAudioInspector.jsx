import React, { useState } from "react";
import { Loader2, Search, RefreshCw, Trash2, Play, Undo2, Ear } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { playWord } from "@/lib/audio";

const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—");
const ORIGIN = { recording: "Chosen take / recording (always wins)", coach_take: "Your raw take (archived)", generated: "Generated" };
const btn = "font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5 disabled:opacity-60";

// Admin → Audio check → Inspect a word: what members actually hear and why.
export default function WordAudioInspector() {
  const [word, setWord] = useState("");
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);

  const inspect = async (w = word) => {
    if (!w.trim()) return;
    setBusy(true);
    try { setD((await api.get(`/admin/word-audio?word=${encodeURIComponent(w.trim())}`)).data); }
    catch { toast.error("Couldn't inspect that word."); }
    finally { setBusy(false); }
  };
  const reset = async (drop) => {
    if (drop && !window.confirm(`Discard your recording for “${d.word}” too? Members will hear the generated voice.`)) return;
    setBusy(true);
    try {
      const r = await api.post("/admin/word-audio/reset", { word: d.word, drop_recording: drop });
      toast.success(`Cleared ${r.data.deleted} clip${r.data.deleted === 1 ? "" : "s"} — re-rendering…`);
      await playWord(d.word, {});
      await inspect(d.word);
    } catch { toast.error("Reset failed."); }
    finally { setBusy(false); }
  };

  const revert = async () => {
    const hasRec = d.clips.some((c) => c.origin === "recording");
    const drop = hasRec && window.confirm(`“${d.word}” has your recording. Discard it too and go fully back to the dictionary pronunciation?\n\nOK = discard recording as well · Cancel = keep the recording, only remove your IPA/stress changes`);
    setBusy(true);
    try {
      const r = await api.post("/admin/dictionary/revert", { word: d.word, drop_recording: drop });
      toast.success(`“${d.word}” reverted to the dictionary pronunciation${r.data.ipa ? ` (${r.data.ipa})` : ""} — re-rendering…`);
      await playWord(d.word, {});
      await inspect(d.word);
    } catch { toast.error("Revert failed."); }
    finally { setBusy(false); }
  };

  const [takes, setTakes] = useState(null);
  const [auditioning, setAuditioning] = useState(false);
  const playB64 = (b64) => new Audio(`data:audio/mpeg;base64,${b64}`).play();

  const audition = async () => {
    setAuditioning(true); setTakes(null);
    try { setTakes((await api.post("/admin/word-audio/auditions", { word: d.word })).data.takes); }
    catch { toast.error("Couldn't render takes."); }
    finally { setAuditioning(false); }
  };
  const pick = async (t) => {
    setBusy(true);
    try {
      await api.post("/admin/word-audio/pick", { word: d.word, audio_b64: t.audio_b64, label: t.label });
      toast.success(`Saved — members now hear this take for “${d.word}”`);
      setTakes(null);
      await inspect(d.word);
    } catch { toast.error("Couldn't save that take."); }
    finally { setBusy(false); }
  };

  return (
    <div className="border thin-rule bg-paper p-4 mt-6" data-testid="admin-word-inspector">
      <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mb-2">Inspect a word</div>
      <form onSubmit={(e) => { e.preventDefault(); inspect(); }} className="flex gap-2 mb-3">
        <input value={word} onChange={(e) => setWord(e.target.value)} placeholder="e.g. baton"
          className="flex-1 bg-surface border thin-rule px-3 py-2 font-serif text-sm text-ink" data-testid="admin-word-inspector-input" />
        <button type="submit" disabled={busy} className="btn-primary !py-2 !px-3 text-xs inline-flex items-center gap-1.5" data-testid="admin-word-inspector-go">
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />} Inspect
        </button>
      </form>
      {d ? (
        <div className="space-y-3" data-testid="admin-word-inspector-result">
          <div className="font-serif text-sm text-ink flex flex-wrap gap-x-4 gap-y-1">
            <span>Dictionary: <span className="font-mono text-rust">{d.dictionary_ipa || "—"}</span></span>
            <span>Your IPA: <span className="font-mono text-rust">{d.custom_ipa || "none"}</span></span>
            {d.preferred_arpabet && !d.custom_ipa ? <span>Forced pronunciation: <span className="font-mono text-rust">{d.preferred_arpabet}</span></span> : null}
            <span>Plays: {d.play_log?.count ?? 0}{d.play_log?.qa_flag ? <span className="text-crimson"> · flagged</span> : null}</span>
          </div>
          {d.clips.length === 0 ? (
            <p className="font-serif text-sm text-muted2 italic" data-testid="admin-word-inspector-empty">No cached audio — the next play will generate and check it.</p>
          ) : (
            <table className="w-full text-xs">
              <thead><tr className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted2 text-left border-b thin-rule">
                <th className="py-1.5 pr-3">Clip</th><th className="py-1.5 pr-3">Origin</th><th className="py-1.5 pr-3">Voice / model</th><th className="py-1.5 pr-3">Listener</th><th className="py-1.5">Made</th>
              </tr></thead>
              <tbody>{d.clips.map((c) => {
                const stale = c.origin === "generated" && (c.voice_id !== d.current.voice_id || c.model !== d.current.model || c.tts_version !== d.current.tts_version);
                return (
                  <tr key={c.word} className="border-b thin-rule font-serif align-top" data-testid={`admin-word-clip-${c.word}`}>
                    <td className="py-2 pr-3 font-mono text-ink">{c.word}</td>
                    <td className={"py-2 pr-3 " + (c.origin === "recording" ? "text-ink" : "text-muted2")}>{ORIGIN[c.origin]}{c.source ? ` · ${c.source}` : ""}</td>
                    <td className="py-2 pr-3 text-muted2">{c.origin === "generated" ? <>{c.voice_id === d.current.voice_id ? "current voice" : "old voice"} · {c.model || "v2"} · v{c.tts_version ?? "?"}{stale ? <span className="text-crimson"> · stale, re-renders on next play</span> : null}</> : "—"}</td>
                    <td className="py-2 pr-3 text-muted2">{c.qa ? <>{c.qa.ok ? "passed" : <span className="text-crimson">flagged</span>} · heard “{c.qa.heard}” · {c.qa.natural}/10{c.takes > 1 ? " · retake" : ""}</> : c.origin === "generated" ? <span className="text-crimson">not checked</span> : "—"}</td>
                    <td className="py-2 text-muted2 whitespace-nowrap">{when(c.created_at)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => playWord(d.word, {})} className={btn} data-testid="admin-word-inspector-play"><Play size={11} /> Play what members hear</button>
            <button type="button" onClick={() => reset(false)} disabled={busy} className={btn} data-testid="admin-word-inspector-regenerate"><RefreshCw size={11} /> Re-generate (keep recording)</button>
            {(d.custom_ipa || d.preferred_arpabet) ? (
              <button type="button" onClick={revert} disabled={busy} className={btn} data-testid="admin-word-inspector-revert"><Undo2 size={11} /> Revert to dictionary pronunciation</button>
            ) : null}
            {d.clips.some((c) => c.origin === "recording") ? (
              <button type="button" onClick={() => reset(true)} disabled={busy} className={btn + " text-crimson"} data-testid="admin-word-inspector-drop"><Trash2 size={11} /> Discard recording & re-generate</button>
            ) : null}
            <button type="button" onClick={audition} disabled={busy || auditioning} className={btn} data-testid="admin-word-inspector-audition">
              {auditioning ? <Loader2 size={11} className="animate-spin" /> : <Ear size={11} />} Audition takes
            </button>
          </div>
          {auditioning ? <p className="font-serif text-xs text-muted2 italic">Rendering a few different takes — about 10 seconds…</p> : null}
          {takes ? (
            <div className="border thin-rule bg-surface p-3" data-testid="admin-word-auditions">
              <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 mb-2">Pick the take that sounds right — it becomes what members hear</div>
              <ul className="divide-y thin-rule">
                {takes.map((t) => (
                  <li key={t.id} className="py-2 flex items-center gap-3" data-testid={`admin-word-take-${t.id}`}>
                    <button type="button" onClick={() => playB64(t.audio_b64)} className={btn} data-testid={`admin-word-take-play-${t.id}`}><Play size={11} /> Play</button>
                    <div className="flex-1 min-w-0">
                      <div className="font-serif text-sm text-ink">{t.label}</div>
                      <div className="font-mono text-[10px] text-muted2 truncate">sent as: {t.spoken}</div>
                    </div>
                    <button type="button" onClick={() => pick(t)} disabled={busy} className="btn-primary !py-1.5 !px-3 text-xs" data-testid={`admin-word-take-use-${t.id}`}>Use this</button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
