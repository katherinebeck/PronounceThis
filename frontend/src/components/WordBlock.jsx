import React from "react";
import { playWord } from "@/lib/audio";
import { toast } from "sonner";

export default function WordBlock({ token, active, highlighted, onSetActive }) {
  const isWord = token.is_word;
  if (!isWord) {
    return <span className="puncwrap">{token.text}</span>;
  }
  const handleClick = async () => {
    if (onSetActive) onSetActive(token);
    try {
      await playWord(token.text);
    } catch (e) {
      toast.error(e.friendly || "Audio playback failed.");
    }
  };
  const cls = ["word-block"];
  if (active) cls.push("active");
  if (highlighted) cls.push("highlight");

  return (
    <button
      type="button"
      className={cls.join(" ")}
      data-testid="word-block"
      aria-label={`Play pronunciation of ${token.text}`}
      onClick={handleClick}
    >
      <span className="english">{token.text}</span>
      <span className={"ipa" + (token.ipa ? "" : " empty")}>
        {token.ipa || "·"}
      </span>
    </button>
  );
}
