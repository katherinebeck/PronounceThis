import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Play, Trash2, Download, Search } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

const inputCls =
  "w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink";

// Everything the coach has saved into her dictionary, searchable + exportable.
export function DictionaryTable({ refreshKey }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/dictionary/entries", { params: { q: q || undefined, limit: 50 } });
      setRows(data.entries || []);
      setTotal(data.total || 0);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [q]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const play = async (word) => {
    try {
      const { data } = await api.get("/admin/dictionary/audio", { params: { word }, responseType: "blob" });
      const url = URL.createObjectURL(data);
      const a = new Audio(url);
      a.onended = () => URL.revokeObjectURL(url);
      a.play();
    } catch {
      toast.error("No recording for this word");
    }
  };

  const remove = async (word) => {
    try {
      await api.post("/admin/dictionary/entries/delete", { word });
      toast.success(`Removed “${word}”`);
      load();
    } catch {
      toast.error("Could not remove");
    }
  };

  const download = (kind) => {
    const base = process.env.REACT_APP_BACKEND_URL;
    window.open(`${base}/api/admin/dictionary/export.${kind}`, "_blank");
  };

  return (
    <div className="mt-8" data-testid="dictionary-table">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          Your dictionary · {total} words
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => download("csv")} className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule hover:bg-ink hover:text-surface inline-flex items-center gap-2" data-testid="dictionary-export-csv">
            <Download size={12} /> CSV
          </button>
          <button type="button" onClick={() => download("zip")} className="font-mono text-[11px] uppercase tracking-[0.2em] px-3 py-2 border thin-rule hover:bg-ink hover:text-surface inline-flex items-center gap-2" data-testid="dictionary-export-zip">
            <Download size={12} /> CSV + audio (zip)
          </button>
        </div>
      </div>
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2" />
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search your recorded words"
          className={`${inputCls} pl-9`}
          data-testid="dictionary-search"
        />
      </div>
      {loading ? (
        <div className="mt-3 font-mono text-xs text-muted2 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Loading…</div>
      ) : rows.length === 0 ? (
        <div className="mt-3 font-serif text-sm text-muted2 italic" data-testid="dictionary-empty">Nothing saved yet.</div>
      ) : (
        <ul className="mt-3 divide-y thin-rule border thin-rule max-h-96 overflow-y-auto" data-testid="dictionary-rows">
          {rows.map((r) => (
            <li key={r.word} className="flex items-center gap-3 px-3 py-2 bg-surface" data-testid={`dictionary-row-${r.word}`}>
              <span className="font-display text-lg text-ink w-40 truncate">{r.word}</span>
              <span className="font-mono text-sm text-rust flex-1 truncate">{r.ipa || "—"}</span>
              {r.ipa_custom ? <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted2">edited</span> : null}
              {r.has_audio ? (
                <button type="button" onClick={() => play(r.word)} className="text-muted2 hover:text-ink p-1" title="Play" data-testid={`dictionary-play-${r.word}`}>
                  <Play size={14} />
                </button>
              ) : <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted2">no audio</span>}
              <button type="button" onClick={() => remove(r.word)} className="text-muted2 hover:text-rust p-1" title="Remove" data-testid={`dictionary-delete-${r.word}`}>
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
