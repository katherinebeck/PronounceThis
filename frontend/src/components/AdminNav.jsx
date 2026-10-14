import React from "react";
import {
  Users, UserPlus, RefreshCw, Link2, ShieldAlert, Flag, Ban, EyeOff, Youtube,
  BookOpen, SlidersHorizontal, Gauge, Mail, Download, ShoppingBag, Eye, Mic,
} from "lucide-react";

export const ADMIN_TABS = [
  { group: "Members", items: [
    { key: "users", label: "All users", icon: Users },
    { key: "buyers", label: "New buyers", icon: ShoppingBag },
    { key: "grant", label: "Grant access", icon: UserPlus },
    { key: "stripe", label: "Stripe sync", icon: RefreshCw },
    { key: "kajabi", label: "Kajabi", icon: Link2 },
    { key: "trial", label: "Trial abuse", icon: ShieldAlert },
  ] },
  { group: "Real Speakers", items: [
    { key: "reports", label: "Clip reports", icon: Flag },
    { key: "blocked", label: "Blocked words", icon: Ban },
    { key: "hidden", label: "Hidden clips", icon: EyeOff },
    { key: "index", label: "Channel index", icon: Youtube },
  ] },
  { group: "Pronunciation", items: [
    { key: "dictionary", label: "My Dictionary", icon: BookOpen },
    { key: "recording", label: "Recording queue", icon: Mic },
    { key: "prefs", label: "Pronunciations", icon: SlidersHorizontal },
  ] },
  { group: "System", items: [
    { key: "credits", label: "Audio budget", icon: Gauge },
    { key: "kit", label: "Kit (email)", icon: Mail },
    { key: "emails", label: "Email previews", icon: Eye },
    { key: "export", label: "Export data", icon: Download },
  ] },
];

export const ALL_TAB_KEYS = ADMIN_TABS.flatMap((g) => g.items.map((i) => i.key));
export const tabLabel = (key) => ADMIN_TABS.flatMap((g) => g.items).find((i) => i.key === key)?.label || "Admin";

export default function AdminNav({ tab, setTab, alerts = {} }) {
  return (
    <nav className="admin-nav" data-testid="admin-nav" aria-label="Admin sections">
      {ADMIN_TABS.map((g) => (
        <div key={g.group} className="admin-nav-group">
          <div className="admin-nav-group-label">{g.group}</div>
          {g.items.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={"admin-nav-item" + (tab === key ? " is-active" : "")}
              aria-current={tab === key ? "page" : undefined}
              data-testid={`admin-nav-${key}`}
            >
              <Icon size={18} className="shrink-0" />
              <span className="truncate">{label}</span>
              {alerts[key] ? <span className="admin-nav-dot" aria-label="needs attention" /> : null}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
