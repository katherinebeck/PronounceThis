import React, { useEffect, useState } from "react";
import { Loader2, CheckCircle2, AlertTriangle, MailCheck, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

const LABEL = {
  sent: "Sent",
  delivered: "Delivered",
  delivery_delayed: "Delayed by their mail server",
  bounced: "Bounced — that address didn't accept it",
  complained: "Marked as spam by the inbox",
};

// Live delivery status for a password-link email + Resend button.
export default function ResetSentStatus({ email, initial }) {
  const [status, setStatus] = useState(initial?.status || "sent");
  const [sentAt, setSentAt] = useState(initial?.sent_at || null);
  const [resending, setResending] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    let tries = 0;
    let stop = false;
    const tick = async () => {
      try {
        const { data } = await api.get("/auth/password-link/status", { params: { email } });
        if (stop) return;
        if (data?.status && data.status !== "none") setStatus(data.status);
        if (data?.sent_at) setSentAt(data.sent_at);
        if (["delivered", "bounced", "complained"].includes(data?.status)) return;
      } catch { /* keep polling */ }
      if (++tries < 8 && !stop) setTimeout(tick, 4000);
    };
    const t = setTimeout(tick, 3000);
    return () => { stop = true; clearTimeout(t); };
  }, [email, sentAt]);

  const resend = async () => {
    setResending(true);
    setErr("");
    try {
      const { data } = await api.post("/auth/password-link", { email });
      setStatus(data.status || "sent");
      setSentAt(data.sent_at || new Date().toISOString());
    } catch (e) {
      setErr(e?.response?.status === 429 ? "Please wait a little before asking again." : "Couldn't resend right now.");
    } finally {
      setResending(false);
    }
  };

  const when = sentAt ? new Date(sentAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  const bad = status === "bounced" || status === "complained";
  const gmail = /@(gmail|googlemail)\./i.test(email);

  return (
    <div className="flex flex-col gap-3" data-testid="auth-reset-sent">
      <div className={`flex items-start gap-2 border thin-rule px-3 py-2.5 ${bad ? "bg-crimson/5" : "bg-paper"}`} data-testid="auth-reset-status">
        {bad ? <AlertTriangle size={15} className="text-crimson mt-0.5 shrink-0" />
          : status === "delivered" ? <CheckCircle2 size={15} className="text-rust mt-0.5 shrink-0" />
          : <MailCheck size={15} className="text-muted2 mt-0.5 shrink-0" />}
        <p className="font-serif text-sm text-ink leading-relaxed">
          <span className="font-semibold" data-testid="auth-reset-status-label">{LABEL[status] || "Sent"}</span>
          {when ? ` at ${when}` : ""} to <span className="font-mono text-rust break-all">{email}</span>.
        </p>
      </div>
      {!bad ? (
        <p className="font-serif text-sm text-ink leading-relaxed">
          Open the email and tap <b>Choose a new password</b> — on this device if you can.
          {gmail ? <> In Gmail it can land under the <b>Promotions</b> or <b>Updates</b> tab — or search for “Pronounce This”.</> : <> Not there? Check your spam or junk folder.</>}
        </p>
      ) : (
        <p className="font-serif text-sm text-ink leading-relaxed">Double-check the spelling, or try the email you used when you joined.</p>
      )}
      {err ? <p className="font-serif text-xs text-crimson" data-testid="auth-reset-error">{err}</p> : null}
      <button type="button" onClick={resend} disabled={resending}
        className="self-start font-mono text-[10px] uppercase tracking-[0.2em] text-muted2 hover:text-ink inline-flex items-center gap-1.5 disabled:opacity-60"
        data-testid="auth-reset-resend">
        {resending ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Send it again
      </button>
    </div>
  );
}
