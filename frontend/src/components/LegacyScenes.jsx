import React, { useCallback, useEffect, useState } from "react";
import { Loader2, UserPlus, FileText } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Admin: scenes uploaded before ownership tracking (owner_email = null).
// Admin-only until explicitly assigned to the correct student here.
export function LegacyScenes() {
  const [scenes, setScenes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [emails, setEmails] = useState({});
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/scenes", { params: { unowned_only: true } });
      setScenes(data.scenes || []);
    } catch {
      setScenes([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const assign = async (id) => {
    const email = (emails[id] || "").trim();
    if (!email) return;
    setBusy(id);
    try {
      await api.post("/admin/scenes/assign", { scene_id: id, email });
      toast.success(`Scene assigned to ${email}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail === "user_not_found"
        ? "No account with that email — grant them access first" : "Could not assign");
    } finally {
      setBusy(null);
    }
  };

  if (!loading && scenes.length === 0) return null;

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-legacy-scenes">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Unassigned scenes
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Scenes uploaded before ownership tracking
      </h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        These scenes have no recorded uploader, so only you can see them. Type the
        student's email to hand a scene to its rightful owner — it then appears in
        their library and nobody else's.
      </p>
      {loading ? (
        <div className="font-mono text-xs text-muted2 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> Loading…</div>
      ) : (
        <ul className="divide-y thin-rule border thin-rule">
          {scenes.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5" data-testid={`legacy-scene-${s.id}`}>
              <FileText size={12} className="text-muted2 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-serif text-base text-ink truncate">{s.title || "Untitled"}</div>
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted2">
                  {s.word_count} words · {s.created_at ? new Date(s.created_at).toLocaleDateString() : ""}
                </div>
              </div>
              <input
                type="email"
                placeholder="student@email.com"
                value={emails[s.id] || ""}
                onChange={(e) => setEmails({ ...emails, [s.id]: e.target.value })}
                className="px-3 py-2 bg-paper border thin-rule font-serif text-sm text-ink focus:outline-none focus:border-ink w-56"
                data-testid={`legacy-scene-email-${s.id}`}
              />
              <button
                type="button"
                disabled={busy === s.id || !(emails[s.id] || "").trim()}
                onClick={() => assign(s.id)}
                className="btn-primary justify-center"
                data-testid={`legacy-scene-assign-${s.id}`}
              >
                {busy === s.id ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />} Assign
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
