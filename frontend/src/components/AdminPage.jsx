import React, { useEffect, useState, useCallback } from "react";
import { Loader2, UserCheck, UserX, Search, ShieldCheck, ShieldOff } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";

// Owner-only admin page for manual membership management. Reached via /admin.
// Access is enforced server-side (require_admin) — this UI just talks to the
// admin endpoints and shows friendly errors if the current user isn't an admin.
export default function AdminPage() {
  const { me, isAuthenticated, openLogin } = useAuth();
  const [authorized, setAuthorized] = useState(null); // null | true | false
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [granting, setGranting] = useState(false);
  const [grantEmail, setGrantEmail] = useState("");
  const [grantDays, setGrantDays] = useState(0);
  const [grantTitle, setGrantTitle] = useState("Group Coaching Access");

  // Check admin status when auth flips authenticated.
  useEffect(() => {
    if (!isAuthenticated) {
      setAuthorized(null);
      return;
    }
    (async () => {
      try {
        await api.get("/admin/whoami");
        setAuthorized(true);
      } catch (err) {
        setAuthorized(false);
      }
    })();
  }, [isAuthenticated]);

  const load = useCallback(async () => {
    if (!authorized) return;
    setLoading(true);
    try {
      const { data } = await api.get("/admin/users", {
        params: query ? { q: query } : {},
      });
      setUsers(data.users || []);
    } catch (e) {
      toast.error("Could not load users");
    } finally {
      setLoading(false);
    }
  }, [authorized, query]);

  useEffect(() => {
    load();
  }, [load]);

  const cancel = async (email) => {
    if (!window.confirm(`Cancel access for ${email}? They keep access until whatever end date is on record, or immediately if none.`))
      return;
    try {
      await api.post("/admin/memberships/cancel", { email });
      toast.success(`Cancelled ${email}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Cancel failed");
    }
  };

  const grant = async (e) => {
    e.preventDefault();
    if (!grantEmail.trim()) return;
    setGranting(true);
    try {
      await api.post("/admin/memberships/grant", {
        email: grantEmail.trim().toLowerCase(),
        offer_title: grantTitle,
        days: Number(grantDays) || 0,
      });
      toast.success(`Granted access to ${grantEmail}`);
      setGrantEmail("");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Grant failed");
    } finally {
      setGranting(false);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center px-4">
        <div className="max-w-md w-full bg-surface border thin-rule p-8 text-center">
          <ShieldOff size={22} className="mx-auto text-muted2 mb-3" />
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
            Admin
          </div>
          <p className="font-display text-2xl text-ink mt-1 mb-5">Sign in required</p>
          <button className="btn-primary" onClick={openLogin} data-testid="admin-signin">
            Sign in
          </button>
        </div>
      </div>
    );
  }

  if (authorized === false) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center px-4">
        <div className="max-w-md w-full bg-surface border thin-rule p-8 text-center">
          <ShieldOff size={22} className="mx-auto text-rust mb-3" />
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
            Admin
          </div>
          <p className="font-display text-2xl text-ink mt-1 mb-2">Not authorized</p>
          <p className="font-serif text-sm text-muted2 italic mb-5">
            You're signed in as <span className="font-mono not-italic">{me?.email}</span>, which is not an admin account.
          </p>
          <a href="/" className="btn-secondary inline-flex">Back to app</a>
        </div>
      </div>
    );
  }

  if (authorized === null) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center">
        <Loader2 className="animate-spin text-ink" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-paper">
      {/* Header */}
      <header className="border-b thin-rule bg-surface px-4 sm:px-8 py-4 flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
            Accent Coach · Admin
          </div>
          <div className="font-display text-2xl text-ink mt-0.5">Memberships</div>
        </div>
        <a href="/" className="btn-secondary !py-2 !px-4" data-testid="admin-back">
          Back to app
        </a>
      </header>

      <div className="max-w-5xl mx-auto px-4 sm:px-8 py-8 space-y-10">
        {/* Grant access */}
        <section className="bg-surface border thin-rule p-6">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Grant access
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Give a student membership
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            Use this for group-coaching students, refunds, or comping a friend.
            Set days = 0 for permanent access, or a number of days to auto-expire.
          </p>
          <form onSubmit={grant} className="grid gap-3 sm:grid-cols-[1.5fr_1fr_0.7fr_auto]">
            <input
              type="email"
              required
              placeholder="student@example.com"
              value={grantEmail}
              onChange={(e) => setGrantEmail(e.target.value)}
              className="w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
              data-testid="admin-grant-email"
            />
            <input
              type="text"
              placeholder="Offer title"
              value={grantTitle}
              onChange={(e) => setGrantTitle(e.target.value)}
              className="w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
              data-testid="admin-grant-title"
            />
            <input
              type="number"
              min="0"
              placeholder="Days"
              value={grantDays}
              onChange={(e) => setGrantDays(e.target.value)}
              className="w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
              data-testid="admin-grant-days"
              title="Days until this grant expires. 0 = never expires."
            />
            <button
              type="submit"
              disabled={granting}
              className="btn-primary justify-center"
              data-testid="admin-grant-submit"
            >
              {granting ? <Loader2 size={14} className="animate-spin" /> : <UserCheck size={14} />}
              Grant
            </button>
          </form>
        </section>

        {/* User list */}
        <section>
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-4">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
                All users
              </div>
              <h2 className="font-display text-2xl text-ink mt-0.5">
                {users.length} account{users.length === 1 ? "" : "s"}
              </h2>
            </div>
            <div className="relative sm:w-72">
              <Search
                size={13}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2 pointer-events-none"
              />
              <input
                type="search"
                placeholder="Search email…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 bg-surface border thin-rule font-serif text-sm text-ink focus:outline-none focus:border-ink"
                data-testid="admin-search"
              />
            </div>
          </div>

          <div className="bg-surface border thin-rule overflow-x-auto">
            <table className="w-full text-left font-serif text-sm">
              <thead>
                <tr className="border-b thin-rule bg-paper">
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Email</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Status</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Ends</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Trial</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted2">
                      <Loader2 size={14} className="inline animate-spin" /> Loading…
                    </td>
                  </tr>
                ) : users.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted2 italic">
                      No users yet.
                    </td>
                  </tr>
                ) : (
                  users.map((u) => {
                    const m = u.membership;
                    const active = m?.is_active;
                    return (
                      <tr key={u.email} className="border-b thin-rule last:border-b-0" data-testid={`admin-user-${u.email}`}>
                        <td className="px-4 py-3 break-all">{u.email}</td>
                        <td className="px-4 py-3">
                          {active ? (
                            <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] px-2 py-1 border thin-rule bg-ink text-surface">
                              <ShieldCheck size={11} />
                              {m?.offer_title || "Member"}
                            </span>
                          ) : (
                            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2">
                              Trial
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted2">
                          {m?.subscription_end_at
                            ? new Date(m.subscription_end_at).toLocaleDateString()
                            : active
                            ? "—"
                            : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted2">
                          {u.trial_word_used}w · {u.trial_scene_used}s
                        </td>
                        <td className="px-4 py-3 text-right">
                          {active ? (
                            <button
                              type="button"
                              onClick={() => cancel(u.email)}
                              className="font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-rust hover:text-surface hover:border-rust transition-colors inline-flex items-center gap-1.5"
                              data-testid={`admin-cancel-${u.email}`}
                            >
                              <UserX size={11} />
                              Cancel
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-3">
            Cancel = ends access at end of paid period (leave date empty to end immediately).
          </p>
        </section>
      </div>
    </div>
  );
}
