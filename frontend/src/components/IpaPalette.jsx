import React from "react";

const GROUPS = [
  { label: "Vowels", symbols: ["i", "ɪ", "ɛ", "æ", "ə", "ʌ", "u", "ʊ", "ɔ", "ɑ", "ɝ", "ɚ"] },
  { label: "Diphthongs", symbols: ["eɪ", "aɪ", "oʊ", "aʊ", "ɔɪ"] },
  { label: "Consonants", symbols: ["θ", "ð", "ʃ", "ʒ", "tʃ", "dʒ", "ŋ", "ɹ", "j", "ɾ", "ɫ", "ʔ"] },
  { label: "Stress", symbols: ["ˈ", "ˌ", "·"] },
];

// Click-to-insert IPA symbols at the caret of the bound input.
export function IpaPalette({ inputRef, value, onChange }) {
  const insert = (sym) => {
    const el = inputRef.current;
    const s = el?.selectionStart ?? value.length;
    const e = el?.selectionEnd ?? value.length;
    const next = value.slice(0, s) + sym + value.slice(e);
    onChange(next);
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      el.setSelectionRange(s + sym.length, s + sym.length);
    });
  };
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2" data-testid="ipa-palette">
      {GROUPS.map((g) => (
        <div key={g.label} className="flex items-center gap-1.5">
          <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted2 mr-1">{g.label}</span>
          {g.symbols.map((s) => (
            <button
              key={s}
              type="button"
              tabIndex={-1}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => insert(s)}
              className="font-mono text-base leading-none px-2 py-1 border thin-rule bg-surface hover:bg-ink hover:text-surface transition-colors"
              data-testid={`ipa-key-${s}`}
            >
              {s}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
