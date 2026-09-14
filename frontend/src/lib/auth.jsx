import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { fetchMe, logout as apiLogout } from "@/lib/api";

const AuthCtx = createContext(null);

/**
 * Auth + subscription state provider. Fetches /api/auth/me once on mount
 * and exposes a `refresh()` so any successful login / trial-consumption
 * / webhook update can pull the latest state.
 *
 * Shape of `me` (from backend AuthMeResponse):
 *   authenticated, email, subscription_status ("active" | "none"),
 *   subscription_offer_title, subscription_end_at,
 *   trial_word_used, trial_scene_used,
 *   trial_word_limit, trial_scene_limit,
 *   monthly_offer_url, annual_offer_url, member_portal_url
 */
export function AuthProvider({ children }) {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [paywallReason, setPaywallReason] = useState(""); // "word" | "scene" | "subscription"

  const refresh = useCallback(async () => {
    try {
      const data = await fetchMe();
      setMe(data);
      return data;
    } catch {
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    (async () => {
      await refresh();
      setLoading(false);
    })();
  }, [refresh]);

  const openLogin = useCallback(() => setLoginOpen(true), []);
  const closeLogin = useCallback(() => setLoginOpen(false), []);
  const openPaywall = useCallback((reason = "subscription") => {
    setPaywallReason(reason);
    setPaywallOpen(true);
  }, []);
  const closePaywall = useCallback(() => setPaywallOpen(false), []);

  const doLogout = useCallback(async () => {
    await apiLogout();
    await refresh();
  }, [refresh]);

  const isAuthenticated = !!me?.authenticated;
  const isSubscriber = me?.subscription_status === "active";
  const trialWordRemaining = Math.max(
    0,
    (me?.trial_word_limit ?? 5) - (me?.trial_word_used ?? 0),
  );
  const trialSceneRemaining = Math.max(
    0,
    (me?.trial_scene_limit ?? 1) - (me?.trial_scene_used ?? 0),
  );

  const value = {
    me,
    loading,
    isAuthenticated,
    isSubscriber,
    trialWordRemaining,
    trialSceneRemaining,
    refresh,
    logout: doLogout,
    loginOpen,
    openLogin,
    closeLogin,
    paywallOpen,
    paywallReason,
    openPaywall,
    closePaywall,
  };

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * Centralized handler for API errors that need to prompt the user to
 * either log in (401) or subscribe (402). Call from any `catch` block.
 * Returns true if it handled the error; caller can then bail silently.
 */
export function handleAuthError(err, auth) {
  const status = err?.response?.status;
  if (status === 401) {
    auth.openLogin();
    return true;
  }
  if (status === 402) {
    const detail = err?.response?.data?.detail;
    const kind =
      (typeof detail === "object" && detail?.kind) ||
      (typeof detail === "object" && detail?.code === "trial_exhausted"
        ? "generic"
        : "subscription");
    auth.openPaywall(kind);
    return true;
  }
  return false;
}
