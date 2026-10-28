import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Admin: pick which of your own scenes new trial users explore in step 02.
export function SampleScene() {
  const [state, setState] = useState({ current: null, scenes: [] });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/sample-scene");
      setState(data);
    } catch {
      toast.error("Could not load sample-scene settings");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const choose = async (scene) => {
    setBusy(true);
    try {
      await api.post("/admin/sample-scene", { scene_id: scene.id });
      toast.success(`"${scene.title}" is now the trial sample scene`);
      await load();
    } catch {
      toast.error("Could not set sample scene");
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!window.confirm("Remove the sample scene? New trial users will see a placeholder until you pick another.")) return;
    setBusy(true);
    try {
      await api.delete("/admin/sample-scene");
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="bg-surface border thin-rule p-6 mt-6" data-testid="admin-sample-scene">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">Guided trial · step 02</div>
      <h2 className="font-display text-2xl text-ink mb-4">Sample audition scene</h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Upload the scene as yourself in the app (Scene tab), then pick it here. It never expires and every signed-in
        trial user can explore and listen to it; downloads stay locked for them.
      </p>
      <div className="border thin-rule px-4 py-3 mb-5 flex items-center justify-between gap-4" data-testid="sample-scene-current">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Current</div>
          <div className={"font-display text-lg truncate " + (state.current ? "text-rust" : "text-muted2")}>
            {state.current ? `${state.current.title} · ${state.current.turns} turns` : "None set"}
          </div>
        </div>
        {state.current ? (
          <button type="button" className="btn-secondary !py-1.5 !px-3" onClick={clear} disabled={busy} data-testid="sample-scene-clear">
            Remove
          </button>
        ) : null}
      </div>
      {state.scenes.length === 0 ? (
        <p className="font-serif text-sm text-muted2" data-testid="sample-scene-empty">You haven't uploaded any scenes yet.</p>
      ) : (
        <ul className="border thin-rule divide-y divide-ink/10" data-testid="sample-scene-list">
          {state.scenes.map((s) => {
            const active = state.current?.id === s.id;
            return (
              <li key={s.id} className="px-4 py-3 flex items-center justify-between gap-4">
                <span className={"font-serif text-sm truncate " + (active ? "text-rust" : "text-ink")}>{s.title}</span>
                {active ? (
                  <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-rust shrink-0" data-testid={`sample-scene-pick-${s.id}`}>In use</span>
                ) : (
                <button
                  type="button"
                  className="btn-secondary !py-1.5 !px-3 shrink-0"
                  onClick={() => choose(s)}
                  disabled={busy}
                  data-testid={`sample-scene-pick-${s.id}`}
                >
                  Use as sample
                </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
