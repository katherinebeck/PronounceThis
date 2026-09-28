import React from "react";
import { useAuth } from "@/lib/auth";
import AuthForm from "./AuthForm";

// Free-trial sign-up (email + password) used inside the trial popup.
export default function TrialSignupForm() {
  const { closePaywall } = useAuth();
  return (
    <div data-testid="trial-signup">
      <p className="font-serif text-base text-muted2 mb-4">Get 5 free words + 1 free scene. No credit card needed.</p>
      <AuthForm mode="signup" setMode={() => {}} compact onDone={closePaywall} />
    </div>
  );
}
