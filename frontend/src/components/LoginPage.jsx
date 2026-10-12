import React, { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import AuthForm from "./AuthForm";
import "./landing/landing.css";

// pronouncethis.us/login — standalone member login (logo, email, password).
export default function LoginPage() {
  const { loading, isAuthenticated } = useAuth();
  const [mode, setMode] = useState("signin");

  useEffect(() => {
    if (!loading && isAuthenticated) window.location.replace("/app");
  }, [loading, isAuthenticated]);

  if (loading || isAuthenticated) return <div className="min-h-screen bg-paper" data-testid="login-page-loading" />;

  return (
    <div className="landing login-page" data-testid="login-page">
      <div className="login-card-wrap">
        <a href="/" className="block text-center" data-testid="login-page-logo-link">
          <img src="/landing/logo.png" alt="Pronounce This." className="login-logo" data-testid="login-page-logo" />
        </a>
        <h1 className="login-title" data-testid="login-page-title">
          {mode === "forgot" ? "Reset your password" : "Log in to your account"}
        </h1>
        <div className="theme-light bg-surface border thin-rule login-card text-left">
          <AuthForm mode={mode} setMode={setMode} ctaLabel={mode === "forgot" ? undefined : "Log in"} onDone={() => window.location.assign("/app")} />
        </div>
        <p className="login-foot">
          Not a member yet? <a href="/" className="link-quiet" data-testid="login-page-join">See plans and try it free</a>
        </p>
      </div>
    </div>
  );
}
