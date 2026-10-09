import React, { useEffect } from "react";
import Logo from "./Logo";
import { createPortal } from "react-dom";
import { X, Mail, Copy } from "lucide-react";
import { toast } from "sonner";

const SUPPORT_EMAIL = "info@katherinebeck.com";

export default function SupportModal({ open, onClose }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;

  const copy = async () => {
    try { await navigator.clipboard.writeText(SUPPORT_EMAIL); toast.success("Email address copied"); }
    catch { toast.error("Couldn't copy — the address is " + SUPPORT_EMAIL); }
  };

  return createPortal(
    <div className="popup-fonts fixed inset-0 z-50 flex items-center justify-center bg-stage/75 backdrop-blur-md p-4" onClick={onClose} data-testid="support-modal">
      <div className="theme-light relative w-full max-w-md bg-surface border thin-rule shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b thin-rule">
          <div>
            <Logo className="h-4 mb-1.5" />
            <div className="font-display text-2xl text-ink">Contact support</div>
          </div>
          <button type="button" className="text-muted2 hover:text-ink p-1" onClick={onClose} aria-label="Close" data-testid="support-close"><X size={20} /></button>
        </div>
        <div className="px-6 py-6">
          <p className="font-serif text-sm text-ink leading-relaxed">
            Questions, billing, or a word that sounds off? Email us directly and we'll get back to you.
          </p>
          <div className="mt-4 flex items-center gap-2 border thin-rule bg-paper px-3 py-2.5">
            <Mail size={14} className="text-muted2" />
            <span className="font-mono text-sm text-ink flex-1 break-all" data-testid="support-email">{SUPPORT_EMAIL}</span>
            <button type="button" onClick={copy} className="btn-secondary !py-1.5 !px-3" data-testid="support-copy"><Copy size={12} /> Copy</button>
          </div>
          <a href={`mailto:${SUPPORT_EMAIL}?subject=Pronounce%20This%20support`} className="btn-primary mt-4 w-full justify-center" data-testid="support-mailto">
            Open in my email app
          </a>
        </div>
      </div>
    </div>,
    document.body
  );
}
