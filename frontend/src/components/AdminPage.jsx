import React, { useEffect, useState, useCallback, useRef } from "react";
import { Loader2, UserCheck, UserX, Search, ShieldCheck, ShieldOff, Mic, Trash2, Volume2, RefreshCw, Link2, Check, AlertTriangle, Download } from "lucide-react";
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
      const res = await api.post("/admin/magic-link", { email });
      const url = res?.data?.login_url;
      if (!url) throw new Error("no url");
      await navigator.clipboard.writeText(url);
      setCopiedEmail(email);
      toast.success(`Sign-in link copied — expires in 15 min`);
      setTimeout(
        () => setCopiedEmail((cur) => (cur === email ? null : cur)),
        1800
      );
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't copy link");
    }
  };

  // ------------------------ Prewarm caption cache ------------------------
  const [prewarmStatus, setPrewarmStatus] = useState(null);
  const [prewarmStarting, setPrewarmStarting] = useState(false);
  const [ingestStatus, setIngestStatus] = useState(null);
  const [ingestStarting, setIngestStarting] = useState(false);

  const loadPrewarmStatus = useCallback(async () => {
    if (!authorized) return;
    try {
      const { data } = await api.get("/admin/prewarm/status");
      setPrewarmStatus(data);
    } catch {
      setPrewarmStatus(null);
    }
    try {
      const { data } = await api.get("/admin/ingest/status");
      setIngestStatus(data);
    } catch {
      setIngestStatus(null);
    }
  }, [authorized]);

  useEffect(() => {
    loadPrewarmStatus();
    const iv = setInterval(loadPrewarmStatus, 15000);
    return () => clearInterval(iv);
  }, [loadPrewarmStatus]);

  const startPrewarm = async () => {
    setPrewarmStarting(true);
    try {
      const { data } = await api.post("/admin/prewarm/start");
      toast.success(
        `Prewarm queued for ${data.words_queued} words — running in background`
      );
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not start prewarm");
    } finally {
      setPrewarmStarting(false);
      setTimeout(loadPrewarmStatus, 2000);
    }
  };

  const startIngest = async () => {
    setIngestStarting(true);
    try {
      const { data } = await api.post("/admin/ingest/channels/start");
      if (data?.already_running) {
        toast.info("Channel ingest already running");
      } else {
        toast.success(
          "Channel ingest started — fetches all 72 channels' recent videos"
        );
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not start ingest");
    } finally {
      setIngestStarting(false);
      setTimeout(loadPrewarmStatus, 2000);
    }
  };

  // ------------------------ Pronunciation overrides ------------------------
  const [overrides, setOverrides] = useState([]);
  const [ovWord, setOvWord] = useState("");
  const ovFileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const loadOverrides = useCallback(async () => {
    if (!authorized) return;
    try {
      const { data } = await api.get("/admin/pronunciation-overrides");
      setOverrides(data.overrides || []);
    } catch {
      // non-fatal; the rest of the page still works
    }
  }, [authorized]);

  useEffect(() => {
    loadOverrides();
  }, [loadOverrides]);

  const uploadOverride = async (e) => {
    e.preventDefault();
    const file = ovFileRef.current?.files?.[0];
    if (!file) return toast.error("Choose an audio file first");
    if (!ovWord.trim()) return toast.error("Enter a word");
    if (file.size > 2 * 1024 * 1024) return toast.error("Audio must be under 2 MB");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("word", ovWord.trim().toLowerCase());
      form.append("file", file);
      await api.post("/admin/pronunciation-overrides", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Saved pronunciation for "${ovWord.trim().toLowerCase()}"`);
      setOvWord("");
      if (ovFileRef.current) ovFileRef.current.value = "";
      loadOverrides();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const deleteOverride = async (word) => {
    if (!window.confirm(`Remove the manual pronunciation for "${word}"? The next lookup will regenerate it via ElevenLabs.`))
      return;
    try {
      await api.post("/admin/pronunciation-overrides/delete", { word });
      toast.success(`Removed "${word}"`);
      loadOverrides();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Delete failed");
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
            Accent Prep · Admin
          </div>
          <div className="font-display text-2xl text-ink mt-0.5">Memberships</div>
        </div>
        <a href="/" className="btn-secondary !py-2 !px-4" data-testid="admin-back">
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

        {/* Prewarm caption cache */}
        <section className="bg-surface border thin-rule p-6" data-testid="admin-prewarm">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Real Speakers · cache
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Prewarm popular words
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            Populate the Real Speakers cache with a curated list of ~1400
            common words + US places + auditioning vocabulary. Once cached,
            every student's first click on those words is instant. Runs in
            the background over several hours; already-cached words are
            skipped. Uses YouTube API quota (~100 units per fresh word).
          </p>
          {prewarmStatus ? (
            <div className="flex items-baseline gap-6 mb-4">
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                  Cached
                </div>
                <div className="font-display text-2xl text-ink">
                  {prewarmStatus.cached}
                  <span className="font-mono text-sm text-muted2 ml-1">
                    / {prewarmStatus.total}
                  </span>
                </div>
              </div>
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                  Coverage
                </div>
                <div className="font-display text-2xl text-rust">
                  {prewarmStatus.percent}%
                </div>
              </div>
            </div>
          ) : null}
          <button
            type="button"
            onClick={startPrewarm}
            disabled={prewarmStarting}
            className="btn-primary"
            data-testid="admin-prewarm-start"
          >
            {prewarmStarting ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {prewarmStatus?.pending
              ? `Prewarm ${prewarmStatus.pending} pending words`
              : "Prewarm all words"}
          </button>
        </section>

        {/* Bulk ingest full transcripts from all curated channels */}
        <section className="bg-surface border thin-rule p-6" data-testid="admin-ingest">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Real Speakers · deep index
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Bulk ingest channel transcripts
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            Walks every one of our 72 curated American-speaker YouTube
            channels, fetches up to 50 recent videos each (~4,000 videos
            total), and stores their full transcripts locally. Once
            complete, ANY word ever spoken in these channels is instantly
            searchable — no more "no video found" for common words like
            "dog", "summer", "winter". Runs in the background for several
            hours; safe to run repeatedly (skips already-indexed videos).
          </p>
          {ingestStatus ? (
            <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3 mb-4">
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                  Videos indexed
                </div>
                <div className="font-display text-2xl text-ink">
                  {ingestStatus.videos_indexed ?? 0}
                </div>
              </div>
              {ingestStatus.job ? (
                <>
                  <div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2">
                      Channels
                    </div>
                    <div className="font-display text-2xl text-ink">
                      {ingestStatus.job.channels_done ?? 0}
                      <span className="font-mono text-sm text-muted2 ml-1">
                        / {ingestStatus.job.channels_total ?? 0}
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
                </>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            onClick={startIngest}
            disabled={ingestStarting || ingestStatus?.job?.running}
            className="btn-primary"
            data-testid="admin-ingest-start"
          >
            {ingestStarting || ingestStatus?.job?.running ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {ingestStatus?.job?.running
              ? "Ingest running"
              : "Ingest all channels now"}
          </button>
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
                          <div className="inline-flex items-center gap-2 justify-end">
                            <button
                              type="button"
                              onClick={() => copyMagicLink(u.email)}
                              className="font-mono text-[10px] uppercase tracking-[0.2em] px-3 py-1.5 border thin-rule hover:bg-ink hover:text-surface hover:border-ink transition-colors inline-flex items-center gap-1.5"
                              data-testid={`admin-copy-link-${u.email}`}
                              title="Copy a one-time sign-in link for this user (expires in 15 min)"
                            >
                              {copiedEmail === u.email ? (
                                <>
                                  <Check size={11} />
                                  Copied
                                </>
                              ) : (
                                <>
                                  <Link2 size={11} />
                                  Copy link
                                </>
                              )}
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
                          </div>
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

        {/* Pronunciation overrides */}
        <section className="bg-surface border thin-rule p-6">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-1">
            Fix a pronunciation
          </div>
          <h2 className="font-display text-2xl text-ink mb-4">
            Record your own for tricky words
          </h2>
          <p className="font-serif text-sm text-muted2 italic mb-5 leading-relaxed">
            ElevenLabs sometimes mispronounces proper nouns like "Los Angeles". Upload
            an MP3 (2 MB max) of the correct pronunciation and the Play button will
            use YOUR recording forever for that word.
          </p>
          <form onSubmit={uploadOverride} className="grid gap-3 sm:grid-cols-[1.5fr_2fr_auto]">
            <input
              type="text"
              required
              placeholder="Word or phrase (e.g. Los Angeles)"
              value={ovWord}
              onChange={(e) => setOvWord(e.target.value)}
              className="w-full px-3 py-2.5 bg-paper border thin-rule font-serif text-base text-ink focus:outline-none focus:border-ink"
              data-testid="admin-ov-word"
            />
            <input
              type="file"
              accept="audio/mpeg,audio/mp3,audio/wav,audio/webm,audio/ogg,audio/mp4"
              ref={ovFileRef}
              className="w-full px-3 py-2 bg-paper border thin-rule font-serif text-sm text-ink file:mr-3 file:px-3 file:py-1.5 file:border-0 file:bg-ink file:text-surface file:font-mono file:text-[10px] file:uppercase file:tracking-[0.2em]"
              data-testid="admin-ov-file"
            />
            <button
              type="submit"
              disabled={uploading}
              className="btn-primary justify-center"
              data-testid="admin-ov-submit"
            >
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
              Save
            </button>
          </form>

          {overrides.length > 0 ? (
            <div className="mt-5 border thin-rule bg-paper divide-y divide-[color:var(--rule)]">
              {overrides.map((o) => (
                <div
                  key={o.word}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                  data-testid={`admin-ov-row-${o.word}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-serif text-base text-ink truncate">
                      {o.word}
                    </div>
                    <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 mt-0.5">
                      {(o.byte_size ? Math.round(o.byte_size / 1024) : "?")} kb
                      {o.content_type ? ` · ${o.content_type}` : ""}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => previewOverride(o.word)}
                    className="p-2 border thin-rule hover:bg-ink hover:text-surface transition-colors"
                    data-testid={`admin-ov-play-${o.word}`}
                    title="Play"
                  >
                    <Volume2 size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteOverride(o.word)}
                    className="p-2 border thin-rule hover:bg-rust hover:text-surface hover:border-rust transition-colors"
                    data-testid={`admin-ov-delete-${o.word}`}
                    title="Remove"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted2 mt-5">
              No overrides yet. Upload one for any word ElevenLabs gets wrong.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
