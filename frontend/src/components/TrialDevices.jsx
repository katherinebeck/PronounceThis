import React, { useCallback, useEffect, useState } from "react";
import { ShieldOff, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Admin: browsers/devices that opened more than one free-trial account.
export function TrialDevices() {
  const [devices, setDevices] = useState([]);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/trial-devices");
      setDevices(data.devices || []);
    } catch {
      setDevices([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = async (d) => {
    const blocked = !d.blocked;
    if (blocked && !window.confirm(`Block this device and its ${d.email_count} trial email(s)? They will hit the paywall until unblocked. Paying members are never affected.`)) return;
    try {
      await api.post("/admin/trial-devices/block", { device_id: d.device_id, blocked });
      toast.success(blocked ? "Device blocked." : "Device unblocked.");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not update device");
    }
  };

  const when = (iso) => (iso ? new Date(iso).toLocaleDateString() : "—");

  return (
    <section className="bg-surface border thin-rule p-6" data-testid="admin-trial-devices">
      <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
        Free trial · repeat devices
      </div>
      <h2 className="font-display text-2xl text-ink mb-4">
        Trial abuse
        <span className="font-mono text-sm text-muted2 ml-2" data-testid="trial-device-count">{devices.length}</span>
      </h2>
      <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
        Each browser gets a device cookie. These devices started trials with two or more emails.
        Blocking sends the device and those emails straight to the paywall.
      </p>
      {devices.length === 0 ? (
        <p className="font-serif text-sm text-muted2" data-testid="trial-devices-empty">No repeat-trial devices yet.</p>
      ) : (
        <div className="overflow-x-auto border thin-rule">
          <table className="w-full text-left font-serif text-sm" data-testid="trial-device-table">
            <thead className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 border-b thin-rule">
              <tr>
                <th className="px-3 py-2">Device</th>
                <th className="px-3 py-2">Emails</th>
                <th className="px-3 py-2">Used</th>
                <th className="px-3 py-2">Last seen</th>
                <th className="px-3 py-2 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y thin-rule">
              {devices.map((d) => (
                <tr key={d.device_id} className={d.blocked ? "bg-rust/5" : ""} data-testid={`trial-device-${d.device_id}`}>
                  <td className="px-3 py-2.5 font-mono text-xs text-muted2">{d.device_id.slice(0, 10)}…</td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-col gap-0.5">
                      {(d.emails || []).map((e) => <span key={e} className="text-ink text-xs font-mono break-all">{e}</span>)}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-muted2 whitespace-nowrap">{d.trial_word_used || 0}w · {d.trial_scene_used || 0}s</td>
                  <td className="px-3 py-2.5 text-xs text-muted2 whitespace-nowrap">{when(d.updated_at)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <button type="button" onClick={() => toggle(d)}
                      className={"font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule inline-flex items-center gap-1.5 " +
                        (d.blocked ? "bg-rust text-surface border-rust hover:bg-ink hover:border-ink" : "hover:bg-rust hover:text-surface hover:border-rust")}
                      data-testid={`trial-device-toggle-${d.device_id}`}>
                      {d.blocked ? <><ShieldCheck size={11} /> Unblock</> : <><ShieldOff size={11} /> Block</>}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
