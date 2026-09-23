import React, { useRef, createContext, useCallback, useContext, useEffect, useState } from "react";
import { fetchMe, logout as apiLogout } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { toast } from "sonner";

const AuthCtx = createContext(null);

export const AUTH_ERROR_TEXT = {
  inbox_already_linked:
    "This inbox already has a Pronounce This account under a different email address (for example the same Gmail with a +tag or dots). Sign in with that address instead.",
};

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

  const refreshSeq = useRef(0);
  const loginOpenRef = useRef(false);
  loginOpenRef.current = loginOpen;
  const refresh = useCallback(async () => {
    const seq = ++refreshSeq.current;
    try {
      const data = await fetchMe();
      if (seq === refreshSeq.current) setMe(data); // ignore stale responses
      if (data?.auth_error) {
        // Valid Supabase login we refuse to link: drop the session so the
        // user isn't silently stuck as a "visitor".
        await supabase.auth.signOut();
        if (!loginOpenRef.current) toast.error(AUTH_ERROR_TEXT[data.auth_error] || "We couldn't link your account. Please contact support.", { id: "auth-error" });
      }
      return data;
    } catch {
      if (seq === refreshSeq.current) setMe(null);
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

  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") {
        window.location.assign("/auth/reset");
        return;
      }
      if (event === "SIGNED_IN" || event === "SIGNED_OUT" || event === "TOKEN_REFRESHED") refresh();
    });
    return () => data.subscription.unsubscribe();
  }, [refresh]);

  const doLogout = useCallback(async () => {
    refreshSeq.current += 1;
    setMe((prev) => (prev ? { ...prev, authenticated: false, email: null, subscription_status: "none" } : prev));
    await supabase.auth.signOut();
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
