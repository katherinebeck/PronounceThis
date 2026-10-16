import React, { useEffect, useState } from "react";
import { Loader2, Plus, X, Globe } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Admin → Pronunciation → Accent guard: non-US slang that must be voiced in General American.
export function AccentGuard() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [word, setWord] = useState("");
  const [ipa, setIpa] = useState("");
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState("");

  const load = async () => {
    try { const { data } = await api.get("/admin/accent-guard"); setEntries(data.entries || []); }
    catch { toast.error("Couldn't load the accent guard list."); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!word.trim()) return;
    setSaving(true);
    try {
      const { data } = await api.post("/admin/accent-guard", { word: word.trim(), ipa: ipa.trim() || null });
      setEntries((cur) => [...cur.filter((x) => x.word !== data.entry.word), data.entry].sort((a, b) => a.word.localeCompare(b.word)));
      setWord(""); setIpa("");
      toast.success(`“${data.entry.word}” will now be voiced as /${data.entry.ipa}/ everywhere.`);
    } catch (err) {
      const d = err?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Couldn't add that word.");
    } finally { setSaving(false); }
  };

  const remove = async (w) => {
    try { await api.post("/admin/accent-guard/delete", { word: w }); setEntries((cur) => cur.filter((x) => x.word !== w)); }
    catch { toast.error("Couldn't remove that word."); }
  };

  const shown = entries.filter((e) => !q || e.word.includes(q.toLowerCase()));

  return (
    <section className="border thin-rule bg-surface p-5 sm:p-6" data-testid="accent-guard">
      <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2 inline-flex items-center gap-2"><Globe size={12} /> Accent guard · {entries.length} words</div>
      <h2 className="font-display text-2xl text-ink mt-1">Slang from other countries, spoken American</h2>
      <p className="font-serif text-sm text-muted2 mt-2 max-w-2xl">
        The voice picks an accent from context, so a word like “strewth” drags a line into Australian. Words listed here are always rendered with their American IPA — in scenes and in the Word tool. Your own My Dictionary entries take priority.
      </p>

      <form onSubmit={add} className="mt-4 flex flex-wrap items-center gap-2">
        <input value={word} onChange={(e) => setWord(e.target.value)} placeholder="word, e.g. strewth" className="border thin-rule bg-paper px-3 py-2 font-serif text-sm text-ink w-44" data-testid="accent-guard-word" />
        <input value={ipa} onChange={(e) => setIpa(e.target.value)} placeholder="American IPA (optional if in dictionary)" className="border thin-rule bg-paper px-3 py-2 font-mono text-sm text-ink w-72" data-testid="accent-guard-ipa" />
        <button type="submit" disabled={saving || !word.trim()} className="btn-primary" data-testid="accent-guard-add">
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Add
        </button>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search list" className="ml-auto border thin-rule bg-paper px-3 py-2 font-serif text-sm text-ink w-40" data-testid="accent-guard-search" />
      </form>

      {loading ? <div className="mt-4 text-muted2 text-sm font-serif">Loading…</div> : (
        <div className="mt-4 flex flex-wrap gap-2" data-testid="accent-guard-list">
          {shown.map((e) => (
            <span key={e.word} className="inline-flex items-center gap-2 border thin-rule bg-paper px-3 py-1.5" data-testid={`accent-guard-chip-${e.word.replace(/\W+/g, "-")}`}>
              <span className="font-serif text-sm text-ink">{e.word}</span>
              <span className="font-mono text-xs text-rust">/{e.ipa}/</span>
              <button type="button" onClick={() => remove(e.word)} className="text-muted2 hover:text-crimson" title="Remove" data-testid={`accent-guard-remove-${e.word.replace(/\W+/g, "-")}`}><X size={12} /></button>
            </span>
          ))}
          {!shown.length ? <span className="font-serif text-sm text-muted2 italic">No words match.</span> : null}
        </div>
      )}
    </section>
  );
}
