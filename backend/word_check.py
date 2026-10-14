"""Word Audio QA: an AI listener confirms a freshly generated single-word clip
really says the word in native American English before students hear it."""
import asyncio
import json
import logging
import os
import re
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

JUDGE_MODEL = ("gemini", "gemini-2.5-flash")
JUDGE_TIMEOUT_SECONDS = 15
MIN_NATURAL = 6

_PROMPT = (
    "You are a strict American-accent coach. This clip is supposed to be the single English word "
    "\"{word}\"{ipa_hint}, spoken once in native General American English. Listen and reply with JSON only, "
    "no prose: {{\"heard\": \"<the word(s) you actually hear>\", \"english\": <true if it sounds like native "
    "American English, false if it sounds like another language or a foreign/robotic accent>, "
    "\"matches\": <true if what you hear is the target word with the intended pronunciation>, "
    "\"natural\": <1-10 naturalness>, \"note\": \"<one short phrase>\"}}"
)


async def judge_word(audio_bytes: bytes, word: str, ipa: Optional[str] = None) -> Optional[dict]:
    """Returns {"ok", "heard", "english", "matches", "natural", "note"} or None if
    the judge is unavailable (callers fail open)."""
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key or not audio_bytes:
        return None
    path = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            path = f.name
        chat = LlmChat(api_key=key, session_id=f"word-qa-{word.lower()}",
                       system_message="You judge short pronunciation clips. Reply with JSON only.").with_model(*JUDGE_MODEL)
        ipa_hint = f" (IPA /{ipa.strip('/')}/)" if ipa else ""
        msg = UserMessage(text=_PROMPT.format(word=word, ipa_hint=ipa_hint),
                          file_contents=[FileContentWithMimeType(file_path=path, mime_type="audio/mpeg")])
        raw = await asyncio.wait_for(chat.send_message(msg), timeout=JUDGE_TIMEOUT_SECONDS)
        m = re.search(r"\{.*\}", str(raw), re.S)
        if not m:
            return None
        d = json.loads(m.group(0))
        natural = int(d.get("natural") or 0)
        ok = bool(d.get("english")) and bool(d.get("matches")) and natural >= MIN_NATURAL
        return {"ok": ok, "heard": str(d.get("heard") or "")[:60], "english": bool(d.get("english")),
                "matches": bool(d.get("matches")), "natural": natural, "note": str(d.get("note") or "")[:120]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("word QA judge unavailable for %s: %s", word, str(exc)[:160])
        return None
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
