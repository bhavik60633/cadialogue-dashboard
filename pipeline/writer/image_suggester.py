"""
Image idea suggester — GPT-4o-mini.
Generates 5 photorealistic, article-specific image concepts per section.
Each prompt describes a REAL scene directly relevant to the article content.
"""
import hashlib
import json
from dataclasses import dataclass

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("image_suggester")

# Session cache — avoid re-billing on repeat clicks
_cache: dict[str, list[dict]] = {}

_SYSTEM = """You are a photo editor for an Indian finance news website.
Your job: write image prompts that describe REAL, SPECIFIC scenes directly related to the article.

STRICT RULES:
1. Every prompt must describe something REAL that could actually be photographed — not abstract, not nature, not symbolic
2. The scene must be DIRECTLY about the article topic (company, event, financial concept described in the section)
3. Describe exactly what is IN the frame: specific objects, people, setting, action
4. Use real Indian finance contexts: offices, product shelves, factories, boardrooms, markets, Mumbai cityscape, Indian consumers
5. NO nature scenes, NO landscapes, NO trees, NO sunsets UNLESS the article is literally about agriculture/environment
6. Keep prompts under 80 words — shorter, more specific prompts produce better images
7. Do NOT include camera/lens specs — just describe the scene vividly"""


async def suggest_images(
    section_text: str,
    topic_title: str,
    section_id: str,
    config: Config,
    n: int = 5,
) -> list["ImageIdea"]:
    """Return n image ideas for the section. Results are cached by content hash."""
    cache_key = f"{section_id}:{hashlib.md5(section_text.encode()).hexdigest()}"
    if cache_key in _cache:
        logger.info(f"Cache hit for {section_id}")
        return [ImageIdea(**d) for d in _cache[cache_key]]

    logger.info(f"Suggesting {n} images for section {section_id}…")
    from ..utils.json_utils import gemini_json_call

    # Pull a meaningful excerpt
    excerpt = section_text[:700].strip()

    user_prompt = f"""Article title: {topic_title}

Section text:
{excerpt}

Generate {n} image ideas for this section. Each must show a REAL, SPECIFIC scene relevant to the text above.

Examples of GOOD prompts for a "Godrej Consumer Products Q4 profit" article:
- "Godrej Consumer Products office lobby in Mumbai with the company logo visible on the wall, Indian corporate employees in business attire walking through the glass entrance, modern interior, daytime"
- "Supermarket shelf stocked with Godrej household products — Good Knight, Cinthol soap, Hit mosquito spray — price tags visible, Indian grocery store aisle, fluorescent lighting, realistic photo"
- "Indian finance analyst in a modern Mumbai office reviewing quarterly earnings report on laptop screen showing profit charts, glass-walled conference room, corporate setting"
- "Godrej company annual report document open on a desk with reading glasses, pen, and a cup of chai beside it, natural window light, overhead shot"

Return ONLY valid JSON:
{{
  "ideas": [
    {{
      "description": "Short label (under 12 words) shown in the editor UI",
      "prompt": "The scene description for DALL-E (60-80 words). Specific, realistic, finance-relevant.",
      "alt_text": "SEO alt text for the image (under 120 characters)",
      "composition": "wide shot | close-up | overhead | eye-level | product shot"
    }}
  ]
}}

IMPORTANT: Every prompt must directly relate to: {topic_title}
Do NOT generate nature scenes, abstract art, or anything unrelated to the article."""

    full_prompt = f"{_SYSTEM}\n\n{user_prompt}"
    data = gemini_json_call(config, full_prompt, max_tokens=2000)
    ideas_raw = data.get("ideas", [])[:n]

    ideas = [
        ImageIdea(
            description=i.get("description", ""),
            composition=i.get("composition", "wide shot"),
            alt_text=i.get("alt_text", ""),
            dalle_prompt=i.get("prompt", i.get("dalle_prompt", "")),
        )
        for i in ideas_raw
        if i.get("prompt") or i.get("dalle_prompt")
    ]

    _cache[cache_key] = [idea.to_dict() for idea in ideas]
    logger.info(f"Got {len(ideas)} ideas for {section_id}: {[i.description for i in ideas]}")
    return ideas


@dataclass
class ImageIdea:
    description: str
    composition: str
    alt_text: str
    dalle_prompt: str

    def to_dict(self) -> dict:
        return {
            "description":  self.description,
            "composition":  self.composition,
            "alt_text":     self.alt_text,
            "dalle_prompt": self.dalle_prompt,
        }
