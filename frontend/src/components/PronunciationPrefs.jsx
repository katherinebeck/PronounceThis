import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Search, Check, Trash2, BookOpen } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

const inputCls =
  "w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink";

// Admin: pick the General American pronunciation for a word from the
// dictionary's variants (or type ARPABET) — no recording needed. The IPA
// shown everywhere and the generated audio both follow the choice.
export function PronunciationPrefs() {
  const [prefs, setPrefs] = useState([]);
  const [word, setWord] = useState("");
  const [options, setOptions] = useState(null);
  const [custom, setCustom] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/pronunciations");
      setPrefs(data.prefs || []);
    } catch {
      setPrefs([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const lookup = async (e) => {
    e?.preventDefault?.();
    if (!word.trim()) return;
    setBusy(true);
    setPreview(null);
    setCustom("");
    try {
      const { data } = await api.get("/admin/pronunciations/options", { params: { word: word.trim() } });
      setOptions(data);
      if (!data.variants.length) toast.message("Not in the dictionary — type ARPABET below.");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Lookup failed");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!options || !custom.trim()) { setPreview(null); return; }
    const t = setTimeout(async () => {
      try {
        const { data } = await api.get("/admin/pronunciations/options", {
          params: { word: options.word, arpabet: custom.trim() },
        });
        setPreview(data.preview || { invalid: true });
      } catch { setPreview(null); }
    }, 300);
    return () => clearTimeout(t);
  }, [custom, options]);

  const save = async (arpabet) => {
    if (!options?.word || !arpabet) return;
    setBusy(true);
    try {
      const { data } = await api.post("/admin/pronunciations", { word: options.word, arpabet });
      toast.success(`${data.word} → ${data.ipa}`);
      setOptions(null);
      setWord("");
      setCustom("");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (w) => {
    if (!window.confirm(`Remove preferred pronunciation for "${w}"? It goes back to the dictionary default.`)) return;
    try {
      await api.post("/admin/pronunciations/delete", { word: w });
      toast.success(`Removed ${w}`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Remove failed");
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-pron-prefs">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Preferred pronunciations
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Choose the General American version of any word
      </h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        The dictionary sometimes lists a regional variant first (e.g. "because" as
        be-CAWZ). Look a word up, pick the pronunciation you teach, and both the IPA
        shown to students and the audio will follow it — no recording needed.
      </p>

      <form onSubmit={lookup} className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <input
          type="text"
          required
          placeholder="Word (e.g. because)"
          value={word}
          onChange={(e) => setWord(e.target.value)}
          className={inputCls}
          data-testid="pron-pref-word"
        />
        <button type="submit" disabled={busy} className="btn-primary justify-center" data-testid="pron-pref-lookup">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          Look up
        </button>
      </form>

      {options ? (
        <div className="mt-5 border thin-rule bg-paper p-4" data-testid="pron-pref-options">
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mb-3">
            {options.word}
            {options.current ? (
              <span className="ml-2 text-ink">· current: {options.current.ipa}</span>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            {options.variants.map((v, i) => (
              <button
                key={v.arpabet}
                type="button"
                disabled={busy}
                onClick={() => save(v.arpabet)}
                className="flex items-center justify-between gap-3 border thin-rule bg-surface px-3 py-2.5 hover:border-ink text-left"
                data-testid={`pron-pref-variant-${i}`}
              >
                <span className="font-mono text-lg text-rust">{v.ipa}</span>
                <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted2">{v.arpabet}</span>
                <Check size={14} className="text-muted2 shrink-0" />
              </button>
            ))}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto] items-center">
            <div>
              <input
                type="text"
                placeholder="Custom ARPABET, e.g. B IH0 K AH1 Z"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                className={inputCls}
                data-testid="pron-pref-custom"
              />
              <div className="mt-1.5 font-mono text-xs h-4" data-testid="pron-pref-preview">
                {preview?.invalid ? (
                  <span className="text-rust">Unknown phone — use CMU ARPABET; vowels need stress 0/1/2</span>
                ) : preview?.ipa ? (
                  <span className="text-rust text-base">{preview.ipa}</span>
                ) : null}
              </div>
            </div>
            <button
              type="button"
              disabled={busy || !preview?.ipa}
              onClick={() => save(preview.arpabet)}
              className="btn-primary justify-center self-start"
              data-testid="pron-pref-save-custom"
            >
              <Check size={14} /> Use custom
            </button>
          </div>
        </div>
      ) : null}

      {prefs.length ? (
        <ul className="mt-6 divide-y thin-rule border thin-rule" data-testid="pron-pref-list">
          {prefs.map((p) => (
            <li key={p.word} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <div className="flex items-baseline gap-3 min-w-0">
                <BookOpen size={12} className="text-muted2 shrink-0" />
                <span className="font-serif text-base text-ink">{p.word}</span>
                <span className="font-mono text-sm text-rust">{p.ipa}</span>
                <span className="hidden sm:inline font-mono text-[10px] uppercase tracking-[0.18em] text-muted2 truncate">{p.arpabet}</span>
              </div>
              <button
                type="button"
                onClick={() => remove(p.word)}
                className="text-muted2 hover:text-rust p-1"
                title="Remove"
                data-testid={`pron-pref-remove-${p.word}`}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
