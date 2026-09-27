import React, { useEffect, useState, useCallback, useRef } from "react";
import { Loader2, UserCheck, UserX, Search, ShieldCheck, ShieldOff, Mic, Trash2, Volume2, RefreshCw, Link2, Unlink, Check, AlertTriangle, Download, Pencil, ChevronLeft, ChevronRight, Mail } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";
import { PronunciationPrefs } from "./PronunciationPrefs";
import CreditMeter from "./CreditMeter";
import KitStatus from "./KitStatus";
import { DictionaryBuilder } from "./DictionaryBuilder";
import { HiddenVideos } from "./HiddenVideos";
import LoginHealth from "./LoginHealth";
import { ClipReports } from "./ClipReports";
import { BlockedWords } from "./BlockedWords";
import { TrialDevices } from "./TrialDevices";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "./ui/alert-dialog";

// Owner-only admin page for manual membership management. Reached via /admin.
// Access is enforced server-side (require_admin) — this UI just talks to the
// admin endpoints and shows friendly errors if the current user isn't an admin.
export default function AdminPage() {
  const { me, isAuthenticated, openLogin } = useAuth();
  const [authorized, setAuthorized] = useState(null); // null | true | false
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const PAGE_SIZE = 25;
  const [loading, setLoading] = useState(false);
  const [granting, setGranting] = useState(false);
  const [grantEmail, setGrantEmail] = useState("");
  const [grantName, setGrantName] = useState("");
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
        params: { page, limit: PAGE_SIZE, ...(query ? { q: query } : {}) },
      });
      setUsers(data.users || []);
      setTotal(data.total ?? (data.users || []).length);
    } catch (e) {
      toast.error("Could not load users");
    } finally {
      setLoading(false);
    }
  }, [authorized, query, page]);

  const submitSearch = (e) => {
    e?.preventDefault?.();
    setPage(1);
    setQuery(searchDraft.trim());
  };
  const clearSearch = () => {
    setSearchDraft("");
    setPage(1);
    setQuery("");
  };
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // 1 … 4 5 [6] 7 8 … 20 — always show first/last, a window round the current page.
  const pageItems = (cur, n) => {
    if (n <= 7) return Array.from({ length: n }, (_, i) => i + 1);
    const items = [1];
    const lo = Math.max(2, cur - 1), hi = Math.min(n - 1, cur + 1);
    if (lo > 2) items.push("…");
    for (let i = lo; i <= hi; i++) items.push(i);
    if (hi < n - 1) items.push("…");
    items.push(n);
    return items;
  };

  useEffect(() => {
    load();
  }, [load]);

  // ------------------------ Payment health ---------------------------------
  const [health, setHealth] = useState(null);

  const loadHealth = useCallback(async () => {
    if (!authorized) return;
    try {
      const { data } = await api.get("/admin/payment-health");
      setHealth(data);
    } catch {
      setHealth(null);
    }
  }, [authorized]);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

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

  const unlinkLogin = async (email) => {
    if (!window.confirm(`Unlink the password login from ${email}? The next sign-in from this inbox (any alias) will re-link to this account.`))
      return;
    try {
      await api.post("/admin/users/unlink-login", { email });
      toast.success(`Unlinked login for ${email}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Unlink failed");
    }
  };

  const [editingEnd, setEditingEnd] = useState(null); // { email, value }
  const [savingEnd, setSavingEnd] = useState(false);

  const saveEnd = async () => {
    if (!editingEnd) return;
    setSavingEnd(true);
    try {
      const { data } = await api.post("/admin/memberships/set-end", {
        email: editingEnd.email,
        subscription_end_at: editingEnd.value || null,
      });
      toast.success(data.subscription_end_at
        ? `Access now ends ${new Date(data.subscription_end_at).toLocaleDateString()}`
        : "Access now has no end date");
      setEditingEnd(null);
      load();
    } catch (e) {
      const d = e?.response?.data?.detail || "";
      toast.error(d.startsWith("stripe_membership") ? "This member pays via Stripe — change dates in Stripe" : d || "Could not update");
    } finally {
      setSavingEnd(false);
    }
  };

  const [pendingDelete, setPendingDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const confirmDelete = async () => {
    const email = pendingDelete;
    if (!email) return;
    setDeleting(true);
    try {
      await api.post("/admin/users/delete", { email });
      toast.success(`Deleted ${email}`);
      setPendingDelete(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  const grant = async (e) => {
    e.preventDefault();
    if (!grantEmail.trim()) return;
    setGranting(true);
    try {
      await api.post("/admin/memberships/grant", {
        email: grantEmail.trim().toLowerCase(),
        first_name: grantName.trim(),
        offer_title: grantTitle,
        days: Number(grantDays) || 0,
      });
      toast.success(`Granted access to ${grantEmail} — welcome email on its way if they've never signed in`);
      setGrantEmail("");
      setGrantName("");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Grant failed");
    } finally {
      setGranting(false);
    }
  };

  // ------------------------ Data export -----------------------------------
  const [exporting, setExporting] = useState(null);

  const exportCsv = async (kind) => {
    setExporting(kind);
    try {
      const res = await api.get(`/admin/export/${kind}.csv`, { responseType: "blob" });
      const match = /filename="([^"]+)"/.exec(res.headers["content-disposition"] || "");
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = match ? match[1] : `${kind}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Downloaded ${kind}.csv`);
    } catch (err) {
      toast.error(`Could not export ${kind}`);
    } finally {
      setExporting(null);
    }
  };

  // ------------------------ Stripe resync ---------------------------------
  const [syncEmail, setSyncEmail] = useState("");
  const [syncing, setSyncing] = useState(false);

  const stripeSync = async (e) => {
    e.preventDefault();
    if (!syncEmail.trim()) return;
    setSyncing(true);
    try {
      const res = await api.post("/admin/stripe/sync", {
        email: syncEmail.trim().toLowerCase(),
      });
      const d = res?.data || {};
      if (d.active_found) {
        toast.success(
          `Synced ${d.synced} subscription${d.synced === 1 ? "" : "s"} — active membership found`
        );
      } else if (d.synced > 0) {
        toast.success(
          `Synced ${d.synced} subscription${d.synced === 1 ? "" : "s"} (none active)`
        );
      } else if (d.reason === "no_stripe_customer") {
        toast.warning("No Stripe customer found for this email");
      } else if (d.reason === "stripe_error") {
        toast.error(`Stripe error: ${d.error || "unknown"}`);
      } else {
        toast.info("Nothing to sync");
      }
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  // ------------------------ Copy magic link ------------------------------
  // Track which email row just had its link copied so we can flash a Check
  // icon instead of the link icon for a second.
  const [copiedEmail, setCopiedEmail] = useState(null);

  const copyMagicLink = async (email) => {
    try {
      const res = await api.post("/admin/password-link", { email });
      const url = res?.data?.link;
      if (!url) throw new Error("no url");
      await navigator.clipboard.writeText(url);
      setCopiedEmail(email);
      toast.success("Set-password link copied — paste it into Kajabi, WhatsApp or an email");
      setTimeout(
        () => setCopiedEmail((cur) => (cur === email ? null : cur)),
        1800
      );
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't create link");
    }
  };

  const [sendingEmail, setSendingEmail] = useState(null);
  const sendWelcome = async (email) => {
    setSendingEmail(email);
    try {
      const res = await api.post("/admin/password-link/send", { email });
      toast.success(`Welcome email sent to ${email} (${res?.data?.status || "sent"})`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't send email");
    } finally {
      setSendingEmail(null);
    }
  };

  // ------------------------ Channel transcript index ------------------------
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingestStarting, setIngestStarting] = useState(false);

  const loadIngestStatus = useCallback(async () => {
    if (!authorized) return;
    try {
      const { data } = await api.get("/admin/ingest/status");
      setIngestStatus(data);
    } catch {
      setIngestStatus(null);
    }
  }, [authorized]);

  useEffect(() => {
    loadIngestStatus();
    const iv = setInterval(loadIngestStatus, 15000);
    return () => clearInterval(iv);
  }, [loadIngestStatus]);

  const startIngest = async () => {
    setIngestStarting(true);
    try {
      const { data } = await api.post("/admin/ingest/channels/start");
      if (data?.already_running) {
        toast.info("Channel ingest already running");
      } else {
        toast.success("Channel ingest started — indexing every curated channel in the background");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not start ingest");
    } finally {
      setIngestStarting(false);
      setTimeout(loadIngestStatus, 2000);
    }
  };



  const previewOverride = async (word) => {
    try {
      const { data } = await api.post("/tts", { word });
      if (data?.audio_b64) {
        const a = new Audio(`data:audio/mpeg;base64,${data.audio_b64}`);
        a.play();
      }
    } catch (err) {
      toast.error("Could not play — " + (err?.response?.data?.detail || "unknown error"));
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="theme-light min-h-screen bg-paper flex items-center justify-center px-4">
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
      <div className="theme-light min-h-screen bg-paper flex items-center justify-center px-4">
        <div className="max-w-md w-full bg-surface border thin-rule p-8 text-center">
          <ShieldOff size={22} className="mx-auto text-rust mb-3" />
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
            Admin
          </div>
          <p className="font-display text-2xl text-ink mt-1 mb-2">Not authorized</p>
          <p className="font-serif text-sm text-muted2 italic mb-5">
            You're signed in as <span className="font-mono not-italic">{me?.email}</span>, which is not an admin account.
          </p>
          <a href="/app" className="btn-secondary inline-flex">Back to app</a>
        </div>
      </div>
    );
  }

  if (authorized === null) {
    return (
      <div className="theme-light min-h-screen bg-paper flex items-center justify-center">
        <Loader2 className="animate-spin text-ink" />
      </div>
    );
  }

  return (
    <div className="theme-light min-h-screen bg-paper">
      {/* Header */}
      <header className="border-b thin-rule bg-surface px-4 sm:px-8 py-4 flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
            Pronounce This · Admin
          </div>
          <div className="font-display text-2xl text-ink mt-0.5">Memberships</div>
        </div>
        <a href="/app" className="btn-secondary !py-2 !px-4" data-testid="admin-back">
          Back to app
        </a>
      </header>

      <div className="max-w-5xl mx-auto px-4 sm:px-8 py-8 space-y-10">
        {/* Payment health banner — visible only when something is off */}
        {health && (health.stuck_users_count > 0 || health.failed_webhooks_count > 0) ? (
          <section
            className="bg-rust/10 border thin-rule border-rust p-5"
            data-testid="admin-payment-health"
          >
            <div className="flex items-start gap-3">
              <AlertTriangle size={20} className="text-rust shrink-0 mt-0.5" />
              <div className="flex-1">
                <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust mb-1">
                  Payment Health · needs attention
                </div>
                <h3 className="font-display text-lg text-ink mb-2">
                  {health.stuck_users_count > 0
                    ? `${health.stuck_users_count} paying user${health.stuck_users_count === 1 ? "" : "s"} stuck on Free Trial`
                    : `${health.failed_webhooks_count} webhook${health.failed_webhooks_count === 1 ? "" : "s"} failed to process`}
                </h3>
                {health.stuck_users.slice(0, 5).map((u) => (
                  <div
                    key={u.email}
                    className="flex items-center justify-between gap-2 text-sm font-serif py-1 border-b thin-rule border-rust/30 last:border-b-0"
                  >
                    <span className="text-ink truncate">{u.email}</span>
                    <button
                      type="button"
                      onClick={async () => {
                        setSyncEmail(u.email);
                        try {
                          const res = await api.post("/admin/stripe/sync", {
                            email: u.email,
                          });
                          if (res?.data?.active_found) {
                            toast.success(`Fixed ${u.email}`);
                          } else {
                            toast.info(`Synced ${u.email} — no active sub in Stripe`);
                          }
                          loadHealth();
                          load();
                        } catch (e) {
                          toast.error(`Sync failed for ${u.email}`);
                        }
                      }}
                      className="font-mono text-[10px] uppercase tracking-[0.2em] px-2.5 py-1 border thin-rule border-rust text-rust hover:bg-rust hover:text-surface transition-colors"
                      data-testid={`admin-health-fix-${u.email}`}
                    >
                      <RefreshCw size={10} className="inline mr-1" />
                      Fix
                    </button>
                  </div>
                ))}
                {health.failed_webhooks_count > 0 ? (
                  <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-3">
                    {health.failed_webhooks_count} webhook{health.failed_webhooks_count === 1 ? "" : "s"} with errors — last:{" "}
                    {health.failed_webhooks[0]?.handler_error}
                  </div>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}

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
          <form onSubmit={grant} className="grid gap-3 sm:grid-cols-[1.5fr_0.8fr_1fr_0.7fr_auto]">
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
              placeholder="First name"
              value={grantName}
              onChange={(e) => setGrantName(e.target.value)}
              className="w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
              data-testid="admin-grant-name"
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

        {/* Sync from Stripe */}
        <section className="bg-surface border thin-rule p-6" data-testid="admin-stripe-sync">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Sync from Stripe
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Repair a paying member stuck on Free Trial
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            If a customer paid through Stripe but the app still shows them as
            "Free trial", enter their email here. This pulls their current
            subscription state directly from Stripe and updates their
            membership record — no waiting on webhooks.
          </p>
          <form onSubmit={stripeSync} className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <input
              type="email"
              required
              placeholder="member@example.com"
              value={syncEmail}
              onChange={(e) => setSyncEmail(e.target.value)}
              className="w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
              data-testid="admin-stripe-sync-email"
            />
            <button
              type="submit"
              disabled={syncing}
              className="btn-primary justify-center"
              data-testid="admin-stripe-sync-submit"
            >
              {syncing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              Sync from Stripe
            </button>
          </form>
        </section>

        <CreditMeter />

        <KitStatus />

        {/* Data export */}
        <section className="bg-surface border thin-rule p-6" data-testid="admin-export">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Your data
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Export users &amp; memberships
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            Download a CSV snapshot of every account and every membership
            record (including Stripe customer and subscription IDs) for your
            own records or to hand to another team.
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              disabled={exporting !== null}
              onClick={() => exportCsv("users")}
              className="btn-primary justify-center"
              data-testid="admin-export-users"
            >
              {exporting === "users" ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              Users CSV
            </button>
            <button
              type="button"
              disabled={exporting !== null}
              onClick={() => exportCsv("memberships")}
              className="btn-primary justify-center"
              data-testid="admin-export-memberships"
            >
              {exporting === "memberships" ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              Memberships CSV
            </button>
          </div>
        </section>

        {/* Bulk ingest full transcripts from all curated channels */}
        <section className="bg-surface border thin-rule p-6" data-testid="admin-ingest">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Real Speakers · YouTube channel index
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Channel transcript index
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            Walks every one of our {ingestStatus?.curated_channels ?? "curated"} American-speaker
            YouTube channels, fetches up to 200 recent videos each and stores
            their transcripts locally so any word spoken in them is instantly
            searchable. Refreshes itself weekly; safe to run any time (skips
            videos already indexed).
          </p>
          {ingestStatus?.stale_lock ? (
            <div className="mb-4 border border-rust/60 bg-rust/10 px-4 py-3 font-serif text-sm text-ink flex items-center gap-2" data-testid="admin-ingest-stale">
              <AlertTriangle size={14} className="text-rust shrink-0" />
              The last run stalled (server restart). Press the button below to take over and resume.
            </div>
          ) : null}
          {ingestStatus ? (
            <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3 mb-4">
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                  Videos indexed
                </div>
                <div className="font-display text-2xl text-ink" data-testid="admin-ingest-videos">
                  {ingestStatus.videos_indexed ?? 0}
                </div>
              </div>
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                  Channels with videos
                </div>
                <div className="font-display text-2xl text-ink">
                  {ingestStatus.channels_with_videos ?? 0}
                  <span className="font-mono text-sm text-muted2 ml-1">
                    / {ingestStatus.curated_channels ?? 0}
                  </span>
                </div>
              </div>
              {ingestStatus.job ? (
                <>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                      This run
                    </div>
                    <div className="font-display text-2xl text-ink">
                      {ingestStatus.job.channels_done ?? 0}
                      <span className="font-mono text-sm text-muted2 ml-1">
                        / {ingestStatus.job.channels_total ?? 0} channels
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                      Status
                    </div>
                    <div className={"font-display text-lg " + (ingestStatus.job.running ? "text-rust" : "text-ink")}>
                      {ingestStatus.job.running ? "Running…" : "Idle"}
                    </div>
                  </div>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                      Last full pass
                    </div>
                    <div className="font-display text-lg text-ink">
                      {ingestStatus.job.last_full_finished_at
                        ? new Date(ingestStatus.job.last_full_finished_at).toLocaleDateString()
                        : "Never completed"}
                    </div>
                  </div>
                </>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            onClick={startIngest}
            disabled={ingestStarting || (ingestStatus?.job?.running && !ingestStatus?.stale_lock)}
            className="btn-primary"
            data-testid="admin-ingest-start"
          >
            {ingestStarting || (ingestStatus?.job?.running && !ingestStatus?.stale_lock) ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {ingestStatus?.stale_lock
              ? "Resume stalled index"
              : ingestStatus?.job?.running
              ? "Indexing running"
              : "Index all channels now"}
          </button>
          {ingestStatus?.by_channel?.length ? (
            <details className="mt-5" data-testid="admin-ingest-by-channel">
              <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 hover:text-ink">
                Videos per channel
              </summary>
              <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1 max-h-72 overflow-auto scrollbar-thin">
                {ingestStatus.by_channel.map((c) => (
                  <div key={c.channel} className="flex justify-between gap-3 font-serif text-sm text-ink border-b thin-rule py-1">
                    <span className="truncate">{c.channel}</span>
                    <span className="font-mono text-xs text-muted2 tabular-nums">{c.videos}</span>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </section>


        <ClipReports />
        <BlockedWords />
        <HiddenVideos />
        <TrialDevices />

        {/* User list */}
        <section>
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-4">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
                All users
              </div>
              <h2 className="font-display text-2xl text-ink mt-0.5" data-testid="admin-users-total">
                {total} account{total === 1 ? "" : "s"}
                {query ? <span className="font-mono text-sm text-muted2 ml-2">matching “{query}”</span> : null}
              </h2>
            </div>
            <form onSubmit={submitSearch} className="flex gap-2 sm:w-[28rem]" data-testid="admin-search-form">
              <div className="relative flex-1">
                <Search
                  size={13}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-muted2 pointer-events-none"
                />
                <input
                  type="search"
                  placeholder="Search by name or email…"
                  value={searchDraft}
                  onChange={(e) => setSearchDraft(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-surface border thin-rule font-serif text-sm text-ink focus:outline-none focus:border-ink"
                  data-testid="admin-search"
                />
              </div>
              <button type="submit" className="btn-primary !py-2 !px-4" data-testid="admin-search-submit">
                Search
              </button>
              {query ? (
                <button type="button" onClick={clearSearch} className="btn-secondary !py-2 !px-3" data-testid="admin-search-clear">
                  Clear
                </button>
              ) : null}
            </form>
          </div>

          <div className="bg-surface border thin-rule overflow-x-auto">
            <table className="w-full text-left font-serif text-sm">
              <thead>
                <tr className="border-b thin-rule bg-paper">
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Email</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Status</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Ends</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Trial</th>
                  <th className="px-4 py-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">Login</th>
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
                        <td className="px-4 py-3 whitespace-nowrap">{u.email}</td>
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
                          {editingEnd?.email === u.email ? (
                            <div className="inline-flex items-center gap-1.5" data-testid={`admin-end-editor-${u.email}`}>
                              <input
                                type="date"
                                value={editingEnd.value}
                                onChange={(e) => setEditingEnd({ ...editingEnd, value: e.target.value })}
                                className="px-2 py-1 bg-paper border thin-rule font-mono text-xs text-ink focus:outline-none focus:border-ink"
                                data-testid={`admin-end-input-${u.email}`}
                              />
                              <button type="button" disabled={savingEnd} onClick={saveEnd}
                                className="p-1 border thin-rule hover:bg-ink hover:text-surface" title="Save"
                                data-testid={`admin-end-save-${u.email}`}>
                                {savingEnd ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                              </button>
                              <button type="button" onClick={() => setEditingEnd(null)}
                                className="p-1 text-muted2 hover:text-ink" title="Cancel"
                                data-testid={`admin-end-cancel-${u.email}`}>
                                <UserX size={11} />
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setEditingEnd({
                                email: u.email,
                                value: m?.subscription_end_at ? m.subscription_end_at.slice(0, 10) : "",
                              })}
                              className="inline-flex items-center gap-1.5 hover:text-ink group"
                              title="Edit access end date"
                              data-testid={`admin-end-edit-${u.email}`}
                            >
                              {m?.subscription_end_at
                                ? new Date(m.subscription_end_at).toLocaleDateString()
                                : active ? "No end" : "—"}
                              <Pencil size={10} className="opacity-40 group-hover:opacity-100" />
                            </button>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted2">
                          {u.trial_word_used}w · {u.trial_scene_used}s
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <LoginHealth user={u} />
                        </td>
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          <div className="inline-flex items-center gap-2 justify-end">
                            <button
                              type="button"
                              onClick={() => copyMagicLink(u.email)}
                              className="font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5"
                              data-testid={`admin-copy-link-${u.email}`}
                              title="Copy a set-password link for this member (paste into Kajabi, WhatsApp or an email)"
                            >
                              {copiedEmail === u.email ? (
                                <>
                                  <Check size={11} />
                                  Copied
                                </>
                              ) : (
                                <>
                                  <Link2 size={11} />
                                  Password link
                                </>
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={() => sendWelcome(u.email)}
                              disabled={sendingEmail === u.email}
                              className="font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                              data-testid={`admin-send-welcome-${u.email}`}
                              title="Email this member a personal set-password link now"
                            >
                              {sendingEmail === u.email ? <Loader2 size={11} className="animate-spin" /> : <Mail size={11} />}
                              Email link
                            </button>
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
                            {u.supabase_sub ? (
                              <button
                                type="button"
                                onClick={() => unlinkLogin(u.email)}
                                className="font-mono text-[10px] uppercase tracking-[0.2em] px-2.5 py-1.5 border thin-rule text-muted2 hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5"
                                data-testid={`admin-unlink-login-${u.email}`}
                                title="Unlink the password login so this inbox can sign in again with a different alias"
                              >
                                <Unlink size={11} />
                              </button>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => setPendingDelete(u.email)}
                              className="font-mono text-[10px] uppercase tracking-[0.2em] px-2.5 py-1.5 border thin-rule text-muted2 hover:bg-rust hover:text-surface hover:border-rust transition-colors inline-flex items-center gap-1.5"
                              data-testid={`admin-delete-${u.email}`}
                              title="Delete this user completely"
                            >
                              <Trash2 size={11} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mt-4" data-testid="admin-users-pager">
            <span className="font-serif text-sm text-muted2">
              Displaying <span className="text-ink font-semibold">{total ? (page - 1) * PAGE_SIZE + 1 : 0} - {Math.min(page * PAGE_SIZE, total)}</span> of{" "}
              <span className="text-ink font-semibold">{total}</span> accounts
            </span>
            {totalPages > 1 ? (
              <nav className="flex items-center gap-1" aria-label="Pagination">
                <button type="button" className="p-2 text-muted2 hover:text-ink disabled:opacity-30" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} data-testid="admin-users-prev" aria-label="Previous page">
                  <ChevronLeft size={16} />
                </button>
                {pageItems(page, totalPages).map((it, i) =>
                  it === "…" ? (
                    <span key={`gap-${i}`} className="px-2 font-mono text-sm text-muted2">…</span>
                  ) : (
                    <button
                      key={it}
                      type="button"
                      onClick={() => setPage(it)}
                      aria-current={it === page ? "page" : undefined}
                      className={
                        "min-w-[2.25rem] h-9 px-2 font-mono text-sm rounded-full transition-colors " +
                        (it === page ? "bg-ink text-stage" : "text-muted2 hover:text-ink hover:bg-surface")
                      }
                      data-testid={`admin-users-page-${it}`}
                    >
                      {it}
                    </button>
                  )
                )}
                <button type="button" className="p-2 text-muted2 hover:text-ink disabled:opacity-30" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} data-testid="admin-users-next" aria-label="Next page">
                  <ChevronRight size={16} />
                </button>
              </nav>
            ) : null}
          </div>

          <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-3">
            Click a date to extend or shorten access (clear it for no end) · Cancel = ends access at end of paid period · Chain icon = unlink password login · Trash = delete the user entirely.
          </p>
        </section>

        <AlertDialog open={!!pendingDelete} onOpenChange={(o) => { if (!o && !deleting) setPendingDelete(null); }}>
          <AlertDialogContent className="bg-paper border thin-rule rounded-none max-w-md" data-testid="admin-delete-dialog">
            <AlertDialogHeader>
              <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-rust mb-1">
                Permanent
              </div>
              <AlertDialogTitle className="font-display text-2xl text-ink font-normal">
                Are you sure you want to delete this user?
              </AlertDialogTitle>
              <AlertDialogDescription className="font-serif text-base text-muted2 leading-relaxed pt-2">
                <span className="font-mono text-sm text-ink break-all">{pendingDelete}</span>
                <br />
                Their account, trial usage, memberships and sign-in links will be
                removed. This cannot be undone. Any Stripe customer record is left
                untouched.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter className="gap-2 sm:gap-3">
              <AlertDialogCancel
                disabled={deleting}
                className="rounded-none border thin-rule bg-surface font-mono text-[11px] uppercase tracking-[0.2em] hover:bg-ink hover:text-surface"
                data-testid="admin-delete-cancel"
              >
                Keep user
              </AlertDialogCancel>
              <AlertDialogAction
                disabled={deleting}
                onClick={(e) => { e.preventDefault(); confirmDelete(); }}
                className="rounded-none bg-rust text-surface font-mono text-[11px] uppercase tracking-[0.2em] hover:bg-ink inline-flex items-center gap-2"
                data-testid="admin-delete-confirm"
              >
                {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                Yes, delete user
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>


        <DictionaryBuilder />

        <PronunciationPrefs />


      </div>
    </div>
  );
}
