import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, X, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Admin: the slur list that excludes a Real Speakers video outright.
export function BlockedWords() {
  const [words, setWords] = useState([]);
  const [defaults, setDefaults] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/blocked-words");
      setWords(data.words || []);
      setDefaults(data.defaults || []);
    } catch {
      setWords([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (next) => {
    setBusy(true);
    try {
      const { data } = await api.post("/admin/blocked-words", { words: next });
      setWords(data.words || []);
      toast.success(`Saved. ${data.flagged} of ${data.scanned} videos now excluded.`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save words");
    } finally {
      setBusy(false);
    }
  };

  const add = (e) => {
    e.preventDefault();
    const w = draft.trim().toLowerCase();
    if (!w) return;
    setDraft("");
    if (words.includes(w)) return;
    save([...words, w]);
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-blocked-words">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Real Speakers · blocked words
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Blocked words
        <span className="font-mono text-sm text-muted2 ml-2" data-testid="blocked-word-count">{words.length}</span>
      </h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Any video whose captions contain one of these words (or its plural) is removed from Real
        Speakers entirely. Ordinary swearing is allowed. Saving re-checks every indexed video.
      </p>
      <form onSubmit={add} className="flex gap-3 mb-4">
        <input type="text" placeholder="Add a word…" value={draft} onChange={(e) => setDraft(e.target.value)}
          className="flex-1 px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
          data-testid="blocked-word-input" />
        <button type="submit" disabled={busy || !draft.trim()} className="btn-primary justify-center disabled:opacity-60" data-testid="blocked-word-add">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Add
        </button>
      </form>
      <div className="flex flex-wrap gap-2" data-testid="blocked-word-list">
        {words.map((w) => (
          <span key={w} className="inline-flex items-center gap-1.5 px-2.5 py-1 border thin-rule bg-paper font-mono text-xs text-ink" data-testid={`blocked-word-${w}`}>
            {w}
            <button type="button" disabled={busy} onClick={() => save(words.filter((x) => x !== w))}
              className="text-muted2 hover:text-rust" aria-label={`Remove ${w}`} data-testid={`blocked-word-remove-${w}`}>
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <button type="button" disabled={busy} onClick={() => save(defaults)}
        className="mt-4 font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 hover:text-ink inline-flex items-center gap-1.5"
        data-testid="blocked-word-reset">
        <RotateCcw size={11} /> Reset to default list
      </button>
    </section>
  );
}
