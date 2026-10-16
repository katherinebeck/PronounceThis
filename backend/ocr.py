"""OCR for scanned script PDFs: pages with no text layer are rendered as
images and transcribed by Claude (vision), keeping screenplay layout."""
import asyncio
import base64
import io
import logging
import os
from typing import List, Optional

from PIL import Image

from llm import MODEL

logger = logging.getLogger(__name__)

MAX_SIDE = 1800
SYSTEM = (
    "You transcribe scanned screenplay / script pages for an accent coach. Output the page text exactly as "
    "printed, preserving screenplay layout as plain text: scene headings on their own line, CHARACTER NAMES in "
    "capitals on their own line before their dialogue, dialogue on the following lines, and stage directions / "
    "parentheticals as written. Keep page order top to bottom. Do not add commentary, headers, markdown, or "
    "notes. If something is illegible write [illegible]. If the page has no text, output nothing."
)


def _page_image_jpeg(page) -> Optional[bytes]:
    """Largest embedded image on the page, downsized and re-encoded as JPEG."""
    try:
        imgs = sorted(page.images, key=lambda i: len(i.data), reverse=True)
        if not imgs:
            return None
        img = Image.open(io.BytesIO(imgs[0].data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("page image extract failed: %s", exc)
        return None


async def _ocr_image(jpeg: bytes) -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=key)
    resp = await client.messages.create(
        model=MODEL, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg).decode("ascii")}},
            {"type": "text", "text": "Transcribe this script page."},
        ]}],
    )
    return "".join(getattr(b, "text", "") for b in resp.content).strip()


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def ocr_pages(reader, pages: List[str]) -> List[str]:
    """Fill in text for pages whose text layer is empty. Pages run in
    parallel; failures leave the page empty."""
    todo = [i for i, t in enumerate(pages) if not (t or "").strip()]
    if not todo or not available():
        return pages
    jpegs = await asyncio.gather(*[asyncio.to_thread(_page_image_jpeg, reader.pages[i]) for i in todo])

    async def _one(i: int, jpeg: Optional[bytes]) -> None:
        if not jpeg:
            return
        try:
            text = await _ocr_image(jpeg)
            if text:
                pages[i] = text
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR failed for page %d: %s", i + 1, exc)

    await asyncio.gather(*[_one(i, j) for i, j in zip(todo, jpegs)])
    logger.info("OCR: transcribed %d/%d scanned pages", sum(1 for i in todo if pages[i].strip()), len(todo))
    return pages
