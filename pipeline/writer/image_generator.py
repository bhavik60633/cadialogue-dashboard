"""
Image generator — gpt-image-1 (OpenAI's latest model, April 2025+).

Generates one image at 1536×1024 (3:2 landscape) in high quality,
then Pillow-crops to 1:1 and 4:3 to give 3 aspect ratios.
Returns base64 → decoded → saved as PNG.
Falls back to dall-e-3 if gpt-image-1 is unavailable on the key tier.
"""
import asyncio
import base64
import io
from pathlib import Path
from typing import Optional

from openai import OpenAI
from PIL import Image

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("image_generator")

IMAGES_DIR = Path(__file__).resolve().parents[1] / "state" / "images"
PRIMARY_MODEL   = "gpt-image-1"
FALLBACK_MODEL  = "dall-e-3"


def _ensure_dir(run_id: str) -> Path:
    d = IMAGES_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _crop_to_ratio(img: Image.Image, ratio_w: int, ratio_h: int) -> Image.Image:
    """Center-crop PIL image to the given aspect ratio (no upscaling)."""
    orig_w, orig_h = img.size
    target_aspect = ratio_w / ratio_h
    orig_aspect   = orig_w / orig_h

    if orig_aspect > target_aspect:          # too wide — trim sides
        new_w = int(orig_h * target_aspect)
        left  = (orig_w - new_w) // 2
        return img.crop((left, 0, left + new_w, orig_h))
    else:                                    # too tall — trim top/bottom
        new_h = int(orig_w / target_aspect)
        top   = (orig_h - new_h) // 2
        return img.crop((0, top, orig_w, top + new_h))


def _enhance_realism_prompt(prompt: str) -> str:
    """
    Add a minimal photorealism suffix to the prompt.
    Keep it short so the model focuses on the CONTENT, not the style meta-text.
    Key: telling the model what NOT to do (no painting, no illustration) is
    more effective than long camera-spec preambles.
    """
    suffix = (
        ". Photorealistic photograph, NOT a painting, NOT an illustration, "
        "NOT digital art, NOT fantasy. Real-world scene, sharp focus, "
        "professional editorial photography. No text overlays, no watermarks."
    )
    return prompt + suffix


async def generate_image(
    dalle_prompt: str,
    run_id: str,
    section_id: str,
    idea_index: int,
    config: Config,
) -> dict[str, str]:
    """
    Generate one image in 3 aspect ratios.

    Returns:
        {"16:9": "/api/images/...", "1:1": "/api/images/...", "4:3": "/api/images/..."}
    """
    logger.info(f"Generating image ({PRIMARY_MODEL}) for {run_id}/{section_id} idea #{idea_index}")

    enhanced_prompt = _enhance_realism_prompt(dalle_prompt)
    client = OpenAI(api_key=config.openai_api_key)
    loop   = asyncio.get_event_loop()

    # ── Try gpt-image-1 first (returns base64) ────────────────────────────────
    img_bytes: Optional[bytes] = None
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: client.images.generate(
                model=PRIMARY_MODEL,
                prompt=enhanced_prompt,
                size="1536x1024",   # 3:2 landscape — best native ratio
                quality="high",
                n=1,
                # gpt-image-1 returns b64_json by default
            ),
        )
        raw_b64 = resp.data[0].b64_json
        if raw_b64:
            img_bytes = base64.b64decode(raw_b64)
            logger.info("gpt-image-1 generation successful")
        else:
            logger.warning("gpt-image-1 returned no b64_json — checking url field")
            if resp.data[0].url:
                import requests as rq
                img_bytes = rq.get(resp.data[0].url, timeout=30).content

    except Exception as exc:
        logger.warning(f"gpt-image-1 failed ({exc}) — falling back to dall-e-3")

    # ── Fallback: dall-e-3 (returns URL) ─────────────────────────────────────
    if not img_bytes:
        logger.info("Using dall-e-3 fallback")
        import requests as rq
        resp2 = await loop.run_in_executor(
            None,
            lambda: client.images.generate(
                model=FALLBACK_MODEL,
                prompt=enhanced_prompt[:960],   # DALL-E 3 max 1000 chars
                size="1792x1024",
                quality="hd",
                n=1,
            ),
        )
        img_bytes = rq.get(resp2.data[0].url, timeout=30).content
        logger.info("dall-e-3 fallback successful")

    # ── Save 3 ratios ─────────────────────────────────────────────────────────
    img_original = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    out_dir = _ensure_dir(run_id)
    stem    = f"{section_id}_idea{idea_index}"

    ratios = {
        "16:9": (img_original,                         f"{stem}_16x9.png"),
        "1:1":  (_crop_to_ratio(img_original, 1, 1),   f"{stem}_1x1.png"),
        "4:3":  (_crop_to_ratio(img_original, 4, 3),   f"{stem}_4x3.png"),
    }

    saved: dict[str, str] = {}
    for ratio_key, (pil_img, filename) in ratios.items():
        file_path = out_dir / filename
        pil_img.save(file_path, format="PNG", optimize=True)
        saved[ratio_key] = f"/api/images/{run_id}/{filename}"
        logger.info(f"Saved {ratio_key}: {file_path.name}  ({pil_img.size[0]}×{pil_img.size[1]})")

    logger.info(f"✓ Image generation complete — 3 ratios saved for {run_id}/{section_id}")
    return saved
