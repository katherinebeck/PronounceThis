import React, { useEffect, useState } from "react";
import Logo from "./Logo";
import { X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import AuthForm from "./AuthForm";

const TITLES = { signin: "Sign in", signup: "Create your account", forgot: "Reset your password" };
const BLURBS = {
  signin: "Welcome back. Enter your email and password.",
  signup: "Get 1 free word and a sample audition scene. No credit card needed.",
  forgot: "Enter your email and we'll send you a link to choose a new password.",
};

export default function LoginModal() {
  const { loginOpen, closeLogin, openPaywall } = useAuth();
  const [mode, setMode] = useState("signin");

  useEffect(() => {
    if (!loginOpen) return undefined;
    setMode("signin");
    const onKey = (e) => { if (e.key === "Escape") closeLogin(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [loginOpen, closeLogin]);

  if (!loginOpen) return null;

  return (
    <div className="popup-fonts fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-stage/90 sm:bg-stage/75 sm:backdrop-blur-md p-0 sm:p-4 overflow-y-auto"
         onClick={closeLogin} data-testid="login-modal">
      <div className="theme-light relative w-full max-w-md bg-surface border thin-rule shadow-2xl max-h-[92dvh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b thin-rule">
          <div>
            <Logo className="h-4 mb-1.5" />
            <div className="font-display text-2xl text-ink" data-testid="login-title">{TITLES[mode]}</div>
          </div>
          <button type="button" className="text-muted2 hover:text-ink p-1" onClick={closeLogin} aria-label="Close" data-testid="login-close">
            <X size={20} />
          </button>
        </div>
        <div className="px-6 py-6">
          <p className="font-serif text-base text-muted2 mb-4 leading-relaxed">{BLURBS[mode]}</p>
          <AuthForm mode={mode} setMode={setMode} onDone={closeLogin} />
          {mode !== "forgot" ? (
            <button type="button" onClick={() => { closeLogin(); openPaywall("join"); }}
                    className="mt-5 font-mono text-xs uppercase tracking-[0.16em] text-rust hover:text-ink" data-testid="login-see-plans">
              Ready to join? See plans →
            </button>
          ) : null}
          <p className="font-serif text-sm text-muted2 mt-4 leading-relaxed" data-testid="login-spam-note">
            Don't see our email? Check your spam or junk folder.
          </p>
        </div>
      </div>
    </div>
  );
}
