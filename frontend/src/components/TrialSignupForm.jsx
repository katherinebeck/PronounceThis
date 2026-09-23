import React from "react";
import { useAuth } from "@/lib/auth";
import AuthForm from "./AuthForm";

// Free-trial sign-up (email + password) used inside the trial popup.
export default function TrialSignupForm() {
  const { closePaywall } = useAuth();
  return (
    <div data-testid="trial-signup">
      <div className="font-mono text-[10px] uppercase tracking-[0.24em] text-muted2 mb-3">
        New here? Try Pronounce This for free
      </div>
      <AuthForm mode="signup" setMode={() => {}} compact onDone={closePaywall} />
      <p className="font-serif text-xs text-muted2 mt-3">Get 5 free words + 1 free scene. No credit card needed.</p>
    </div>
  );
}
