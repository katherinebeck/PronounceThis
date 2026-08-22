import React from "react";
import { playWord } from "@/lib/audio";
import { toast } from "sonner";

export default function WordBlock({
  token,
  active,
  highlighted,
  onSetActive,
  onOpenReference,
}) {
  const isWord = token.is_word;
  if (!isWord) {
    return <span className="puncwrap">{token.text}</span>;
  }
  const handleClick = async (e) => {
    // Shift/Cmd/Ctrl-click → look up on YouGlish instead of playing.
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      e.preventDefault();
      onOpenReference?.(token.text);
      return;
    }
    if (onSetActive) onSetActive(token);
    try {
      await playWord(token.text);
    } catch (err) {
      toast.error(err.friendly || "Audio playback failed.");
    }
  };
  const handleContext = (e) => {
    e.preventDefault();
    onOpenReference?.(token.text);
  };
  const cls = ["word-block"];
  if (active) cls.push("active");
  if (highlighted) cls.push("highlight");
  if (token.is_proper_noun) cls.push("proper-noun");

  return (
    <span className="word-block-wrap" data-testid="word-block-wrap">
      <button
        type="button"
        className={cls.join(" ")}
        data-testid="word-block"
        data-proper-noun={token.is_proper_noun ? "1" : "0"}
        aria-label={
          token.is_proper_noun
            ? `Play ${token.text}. Right-click for real-speaker reference.`
            : `Play pronunciation of ${token.text}`
        }
        onClick={handleClick}
        onContextMenu={handleContext}
      >
        <span className="english">{token.text}</span>
        <span className={"ipa" + (token.ipa ? "" : " empty")}>
          {token.ipa || "·"}
        </span>
      </button>
      {token.is_proper_noun ? (
        <button
          type="button"
          className="pn-ref-btn"
          data-testid="word-youglish-button"
          aria-label={`Hear real speakers say ${token.text}`}
          title="Hear real speakers on YouGlish"
          onClick={(e) => {
            e.stopPropagation();
            onOpenReference?.(token.text);
          }}
        >
          Y
        </button>
      ) : null}
    </span>
  );
}
