import React, { useCallback, useEffect, useState } from "react";
import { Flag, EyeOff, Check } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Admin: clips members flagged from the Real Speakers player.
export function ClipReports() {
  const [reports, setReports] = useState([]);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/clip-reports");
      setReports(data.reports || []);
    } catch {
      setReports([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const resolve = async (video_id, action) => {
    try {
      await api.post("/admin/clip-reports/resolve", { video_id, action });
      toast.success(action === "hide" ? "Clip hidden for everyone." : "Report dismissed.");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not update report");
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-clip-reports">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Real Speakers · reported by members
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Reported clips
        <span className="font-mono text-sm text-muted2 ml-2" data-testid="clip-report-count">{reports.length}</span>
      </h2>
      {reports.length === 0 ? (
        <p className="font-serif text-sm text-muted2 italic" data-testid="clip-reports-empty">
          Nothing waiting. When a member taps “Report clip” under a video it shows up here.
        </p>
      ) : (
        <ul className="divide-y thin-rule border thin-rule" data-testid="clip-report-list">
          {reports.map((r) => (
            <li key={r.video_id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-3 py-3" data-testid={`clip-report-${r.video_id}`}>
              <div className="min-w-0">
                <a href={`https://www.youtube.com/watch?v=${r.video_id}`} target="_blank" rel="noreferrer"
                  className="font-serif text-sm text-ink underline underline-offset-4 decoration-ink/30 truncate block">
                  {r.title || r.video_id}
                </a>
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted2 mt-1 flex flex-wrap gap-x-3">
                  <span className="inline-flex items-center gap-1"><Flag size={10} />{(r.reporters || []).length} report{(r.reporters || []).length === 1 ? "" : "s"}</span>
                  {r.channel_title ? <span>{r.channel_title}</span> : null}
                  {r.query ? <span>word: {r.query}</span> : null}
                  {r.last_reason ? <span className="text-rust">{r.last_reason}</span> : null}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button type="button" onClick={() => resolve(r.video_id, "hide")}
                  className="font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-rust hover:text-surface hover:border-rust inline-flex items-center gap-1.5"
                  data-testid={`clip-report-hide-${r.video_id}`}>
                  <EyeOff size={11} /> Hide
                </button>
                <button type="button" onClick={() => resolve(r.video_id, "dismiss")}
                  className="font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule text-muted2 hover:bg-ink hover:text-surface inline-flex items-center gap-1.5"
                  data-testid={`clip-report-dismiss-${r.video_id}`}>
                  <Check size={11} /> Keep
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
