"""
Instagram Reels / Shorts content generator.

Takes the top 10 latest world news stories from NewsAPI and generates
explosive 30-second Instagram scripts with proven viral hooks.

Usage:
    from pipeline.writer.shorts_generator import generate_shorts
    result = await generate_shorts(config)
"""

import asyncio
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.json_utils import safe_json_parse

logger = get_logger("shorts_generator")

# ── News fetching ──────────────────────────────────────────────────────────────


def _fetch_top_headlines(api_key: str) -> list[dict]:
    """NewsAPI /v2/top-headlines — breaking news right now."""
    try:
        resp = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "language": "en",
                "pageSize": 20,
                "apiKey": api_key,
            },
            timeout=12,
        )
        resp.raise_for_status()
        return [
            a for a in resp.json().get("articles", [])
            if a.get("title") and "[Removed]" not in (a.get("title") or "")
        ]
    except Exception as exc:
        logger.warning(f"top-headlines fetch failed: {exc}")
        return []


def _fetch_latest_world_news(api_key: str) -> list[dict]:
    """NewsAPI /v2/everything sorted by publishedAt — most recent 24 hours."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "world OR global OR breaking OR crisis OR economy OR war OR election OR climate OR AI",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "from": since,
                "sources": "bbc-news,reuters,associated-press,the-guardian-uk,al-jazeera-english",
                "apiKey": api_key,
            },
            timeout=12,
        )
        resp.raise_for_status()
        return [
            a for a in resp.json().get("articles", [])
            if a.get("title") and "[Removed]" not in (a.get("title") or "")
        ]
    except Exception as exc:
        logger.warning(f"everything-world fetch failed: {exc}")
        return []


def _merge_and_dedupe(lists: list[list[dict]], cap: int = 25) -> list[dict]:
    """Merge multiple article lists, dedup by title prefix, cap at `cap`."""
    seen: set[str] = set()
    merged: list[dict] = []
    for lst in lists:
        for a in lst:
            key = (a.get("title") or "")[:60].lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(a)
                if len(merged) >= cap:
                    return merged
    return merged


# ── Script generation ──────────────────────────────────────────────────────────


_HOOK_GUIDE = """
HOOK FORMULAS (pick the best fit for each story):
1. BREAKING   → "BREAKING: [X] just happened — and nobody is ready for what comes next."
2. SHOCKING   → "[Number] [people/nations/dollars] just [action] and it's bigger than you think."
3. CURIOSITY  → "Most people have no idea this just happened. [Tease the news]."
4. PERSONAL   → "If you [own/use/invest in X], stop scrolling — this affects you directly."
5. CONTRAST   → "While you were sleeping, [event] just changed [topic] forever."
6. CONTROVERSY→ "Everyone's talking about [topic], but nobody's mentioning THIS part."
7. QUESTION   → "What happens when [shocking scenario]? We just found out."
"""


def _build_generation_prompt(articles: list[dict]) -> str:
    news_items = [
        {
            "n": i + 1,
            "title": a.get("title", ""),
            "desc": (a.get("description") or "")[:220],
            "source": a.get("source", {}).get("name", "Unknown"),
            "published": a.get("publishedAt", ""),
        }
        for i, a in enumerate(articles[:20])
    ]

    return f"""You are a TOP viral Instagram Reels scriptwriter specialising in news content.
You create 30-second scripts that make people STOP SCROLLING.

{_HOOK_GUIDE}

SCRIPT STRUCTURE (total: 80–95 words = ~30 seconds at natural speaking pace):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOOK      ≈ 15 words  (3–5 sec)  — Pattern-interrupt opener from the formulas above
STORY     ≈ 48 words  (15 sec)   — 3 punchy sentences: WHAT happened + KEY facts + WHO is involved
IMPACT    ≈ 22 words  (7 sec)    — "Here's what this means for YOU:" + direct consequence
CTA       ≈ 8 words   (3 sec)    — "Follow for daily updates" / "Share before it's gone" / "Drop your reaction below"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ABSOLUTE RULES:
- Only use REAL facts from the title/description provided — NEVER invent details
- Short punchy sentences. No filler words. Every word earns its place.
- Write exactly as SPOKEN ALOUD (contractions fine, rhetorical questions fine)
- Avoid passive voice — keep it active and urgent
- Each full_script = hook + "\\n\\n" + story + "\\n\\n" + impact + "\\n\\n" + cta

I have {len(news_items)} headlines below. Select the TOP 10 most impactful stories and write a script for each.
Prioritise recency, global impact, and stories that directly affect everyday people.

Headlines:
{json.dumps(news_items, indent=2)}

Return ONLY valid JSON — no markdown, no commentary:
{{
  "scripts": [
    {{
      "n": 1,
      "hook_style": "BREAKING|SHOCKING|CURIOSITY|PERSONAL|CONTRAST|CONTROVERSY|QUESTION",
      "hook": "...",
      "story": "...",
      "impact": "...",
      "cta": "...",
      "full_script": "...",
      "word_count": 88
    }}
  ]
}}"""


def _call_openai(prompt: str, config: Config) -> list[dict]:
    client = config.make_ai_client()
    response = client.chat.completions.create(
        model=config.ai_model,          # GPT-4o — quality scripts, not mini
        max_tokens=8000,
        temperature=0.72,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    return safe_json_parse(raw).get("scripts", [])


# ── Public API ─────────────────────────────────────────────────────────────────


async def generate_shorts(config: Config) -> dict:
    """
    Fetch top 10 latest world news + generate 30-second Instagram scripts.

    Returns:
        {
            "generated_at": ISO timestamp,
            "total": int,
            "scripts": [{
                "headline": {title, description, source, url, published_at, image_url},
                "hook_style": str,
                "hook": str,
                "story": str,
                "impact": str,
                "cta": str,
                "full_script": str,
                "word_count": int,
                "estimated_seconds": float,
            }]
        }
    """
    if not config.newsapi_key:
        raise RuntimeError("NEWSAPI_KEY is not configured in .env")

    logger.info("Fetching latest world headlines for Shorts generation…")
    loop = asyncio.get_event_loop()

    # Fetch both sources in parallel
    top_raw, world_raw = await asyncio.gather(
        loop.run_in_executor(None, _fetch_top_headlines, config.newsapi_key),
        loop.run_in_executor(None, _fetch_latest_world_news, config.newsapi_key),
    )

    # Merge: put world (freshest) first so AI picks the most recent
    articles = _merge_and_dedupe([world_raw, top_raw], cap=25)

    if not articles:
        raise RuntimeError(
            "NewsAPI returned no articles. Check NEWSAPI_KEY or try again later."
        )

    logger.info(f"Fetched {len(articles)} unique headlines. Generating scripts via GPT-4o…")

    prompt = _build_generation_prompt(articles)
    try:
        scripts_raw = await asyncio.wait_for(
            loop.run_in_executor(None, _call_openai, prompt, config),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise RuntimeError("GPT-4o timed out generating scripts (>90s). Try again.")
    except Exception as exc:
        raise RuntimeError(f"Script generation failed: {exc}")

    if not scripts_raw:
        raise RuntimeError("GPT-4o returned no scripts. Try refreshing.")

    # Assemble final response — map each script back to its source article
    result: list[dict] = []
    for s in scripts_raw[:10]:
        idx = int(s.get("n", 1)) - 1
        article = articles[idx] if 0 <= idx < len(articles) else articles[0]
        word_count = int(s.get("word_count", len((s.get("full_script") or "").split())))
        result.append({
            "headline": {
                "title":        article.get("title", ""),
                "description":  (article.get("description") or "")[:300],
                "source":       article.get("source", {}).get("name", "Unknown"),
                "url":          article.get("url", ""),
                "published_at": article.get("publishedAt", ""),
                "image_url":    article.get("urlToImage") or "",
            },
            "hook_style":         s.get("hook_style", "BREAKING"),
            "hook":               s.get("hook", ""),
            "story":              s.get("story", ""),
            "impact":             s.get("impact", ""),
            "cta":                s.get("cta", ""),
            "full_script":        s.get("full_script", ""),
            "word_count":         word_count,
            "estimated_seconds":  round(word_count / 2.6, 1),  # ~156 wpm natural pace
        })

    logger.info(f"Generated {len(result)} Instagram Shorts scripts ✓")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total":         len(result),
        "scripts":       result,
    }
