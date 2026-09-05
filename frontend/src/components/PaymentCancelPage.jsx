import React from "react";
import { XCircle } from "lucide-react";

// Landing spot when a Stripe Checkout is cancelled (user clicked back or
// closed the tab). No side effects — just tell them and offer a way back.
export default function PaymentCancelPage() {
  return (
    <div className="min-h-screen bg-paper flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-surface border thin-rule px-8 py-12 text-center">
        <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          Accent Prep
        </div>
        <div className="inline-flex items-center justify-center w-14 h-14 border thin-rule bg-paper my-5">
          <XCircle size={22} className="text-muted2" />
        </div>
        <p
          className="font-display text-xl text-ink mb-2"
          data-testid="payment-cancel-status"
        >
          Checkout cancelled
        </p>
        <p className="font-serif text-sm text-muted2 italic leading-relaxed">
          No charge was made. Whenever you're ready, hit the Subscribe button
          in the app to try again.
        </p>
        <a href="/" className="btn-primary mt-6 inline-flex" data-testid="payment-cancel-home">
          Back to Accent Prep
        </a>
      </div>
    </div>
  );
}
