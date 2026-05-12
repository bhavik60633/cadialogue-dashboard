"""
Real stock photo fetcher — Pexels API.

Uses GPT-4o-mini to generate precise search queries from article section text,
then fetches real, high-quality photographs from Pexels (free, commercial use).

Why Pexels instead of AI generation:
- Actual photographs taken by real cameras — zero AI artefacts
- Free tier: 200 requests/hour, unlimited downloads
- Commercial use allowed without attribution
- 3M+ curated professional photos
"""
import asyncio
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests as rq

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("stock_photo_fetcher")

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
IMAGES_DIR = Path(__file__).resolve().parents[1] / "state" / "images"


@dataclass
class StockPhoto:
    pexels_id: int
    description: str          # alt text / description
    photographer: str
    thumb_url: str            # small preview for the UI picker (~400px)
    full_url: str             # large download for publishing (~1920px)
    width: int
    height: int

    def to_dict(self) -> dict:
        return {
            "pexels_id":    self.pexels_id,
            "description":  self.description,
            "photographer": self.photographer,
            "thumb_url":    self.thumb_url,
            "full_url":     self.full_url,
            "width":        self.width,
            "height":       self.height,
        }


def _pexels_search(query: str, api_key: str, per_page: int = 5) -> list[StockPhoto]:
    """Search Pexels synchronously (called via run_in_executor)."""
    resp = rq.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": per_page, "orientation": "landscape"},
        timeout=10,
    )
    if resp.status_code == 401:
        raise ValueError("Invalid Pexels API key — get a free key at pexels.com/api")
    resp.raise_for_status()

    photos = []
    for p in resp.json().get("photos", []):
        src = p.get("src", {})
        photos.append(StockPhoto(
            pexels_id   = p["id"],
            description = p.get("alt", "") or f"Photo by {p.get('photographer', 'Pexels')}",
            photographer= p.get("photographer", "Pexels"),
            thumb_url   = src.get("medium", src.get("small", "")),
            full_url    = src.get("large2x", src.get("large", src.get("original", ""))),
            width       = p.get("width", 0),
            height      = p.get("height", 0),
        ))
    return photos


async def _generate_search_queries(
    section_text: str, topic_title: str, config: Config
) -> list[str]:
    """Ask Gemini/OpenAI for 3 precise Pexels search queries for this section."""

    prompt = f"""You are helping find real stock photos for an Indian finance news article.

Article topic: {topic_title}
Section text: {section_text[:500]}

Generate 3 short, specific Pexels search queries that will find REAL photographs relevant to this section.

Rules:
- Queries should be 2-5 words
- Focus on what's visually in the scene, not the concept
- Avoid brand names (Pexels doesn't have branded product photos)
- Use generic but specific terms: "Indian office meeting", "stock market trader", "retail supermarket shelf India"
- Order from most specific to most general

Return ONLY valid JSON:
{{"queries": ["query 1", "query 2", "query 3"]}}"""

    from ..utils.json_utils import gemini_json_call
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None,
        lambda: gemini_json_call(config, prompt, max_tokens=200)
    )
    queries = data.get("queries", [])[:3]
    logger.info(f"Pexels queries: {queries}")
    return queries


async def fetch_stock_photos(
    section_text: str,
    topic_title: str,
    section_id: str,
    config: Config,
    n: int = 8,
) -> list[StockPhoto]:
    """
    Return up to n real Pexels photos relevant to this article section.
    Falls back to generic finance queries if Pexels key is missing.
    """
    if not config.pexels_api_key:
        logger.warning("PEXELS_API_KEY not set — using placeholder response")
        return []

    queries = await _generate_search_queries(section_text, topic_title, config)

    loop = asyncio.get_event_loop()
    all_photos: list[StockPhoto] = []
    seen_ids: set[int] = set()

    per_query = max(3, n // len(queries))
    for q in queries:
        try:
            photos = await loop.run_in_executor(
                None, _pexels_search, q, config.pexels_api_key, per_query
            )
            for p in photos:
                if p.pexels_id not in seen_ids:
                    seen_ids.add(p.pexels_id)
                    all_photos.append(p)
        except Exception as exc:
            logger.warning(f"Pexels query '{q}' failed: {exc}")

    logger.info(f"Fetched {len(all_photos)} real photos for {section_id}")
    return all_photos[:n]


async def download_stock_photo(
    photo: StockPhoto,
    run_id: str,
    section_id: str,
    config: Config,
) -> dict[str, str]:
    """
    Download a Pexels photo and save it in 3 aspect ratios.
    Returns {"16:9": "/api/images/...", "1:1": "...", "4:3": "..."}
    """
    from PIL import Image
    from ..writer.image_generator import _crop_to_ratio, _ensure_dir

    logger.info(f"Downloading Pexels photo {photo.pexels_id} for {run_id}/{section_id}")

    loop = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(
        None,
        lambda: rq.get(photo.full_url, timeout=30).content,
    )

    img_original = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    out_dir = _ensure_dir(run_id)
    stem = f"{section_id}_pexels{photo.pexels_id}"

    ratios = {
        "16:9": (img_original if abs(img_original.width / img_original.height - 16/9) < 0.3
                 else _crop_to_ratio(img_original, 16, 9), f"{stem}_16x9.png"),
        "1:1":  (_crop_to_ratio(img_original, 1, 1),  f"{stem}_1x1.png"),
        "4:3":  (_crop_to_ratio(img_original, 4, 3),  f"{stem}_4x3.png"),
    }

    saved: dict[str, str] = {}
    for ratio_key, (pil_img, filename) in ratios.items():
        file_path = out_dir / filename
        pil_img.save(file_path, format="PNG", optimize=True)
        saved[ratio_key] = f"/api/images/{run_id}/{filename}"

    logger.info(f"Saved real photo in 3 ratios: {list(saved.keys())}")
    return saved
