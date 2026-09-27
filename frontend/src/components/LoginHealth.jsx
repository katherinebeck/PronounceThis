import React from "react";
import { KeyRound, Clock, MailCheck, MailWarning } from "lucide-react";

const short = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");

// Admin → Users "Login" cell: has this member actually got in yet?
export default function LoginHealth({ user }) {
  const signedIn = Boolean(user.last_login_at);
  const legacy = signedIn && !user.supabase_sub;
  const last = user.last_auth_email;
  const bad = last && (last.status === "bounced" || last.status === "complained");
  const kindLabel = { welcome: "welcome", nudge: "reminder", reset: "reset", no_account: "no-account note" };

  return (
    <div className="flex flex-col gap-0.5 text-xs" data-testid={`admin-login-health-${user.email}`}>
      {signedIn ? (
        <span className="inline-flex items-center gap-1.5 text-ink">
          <KeyRound size={11} className="text-rust" />
          {legacy ? "Signed in (legacy link)" : "Password set"} · {short(user.last_login_at)}
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-crimson">
          <Clock size={11} />
          Never signed in
        </span>
      )}
      {last ? (
        <span className={`inline-flex items-center gap-1.5 ${bad ? "text-crimson" : "text-muted2"}`}>
          {bad ? <MailWarning size={11} /> : <MailCheck size={11} />}
          {kindLabel[last.kind] || last.kind} {bad ? last.status : last.status === "delivered" ? "delivered" : "sent"} {short(last.sent_at)}
        </span>
      ) : !signedIn ? (
        <span className="text-muted2">no link emailed yet</span>
      ) : null}
    </div>
  );
}
