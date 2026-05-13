"""
Topical Authority Engine — hub/spoke cluster architecture.

Builds and maintains a topic map for cadialogue.in:
  - Detects parent topics from published content
  - Generates content roadmap (articles to write next)
  - Identifies coverage gaps
  - Calculates authority score per topic cluster

Topic cluster structure (hub/spoke):
  Hub:   "Mutual Funds in India — Complete Guide"
  Spokes:
    - best mutual funds for beginners india
    - SIP vs lump sum investment india
    - direct vs regular mutual fund india
    - how to start SIP in India
    - top flexi cap mutual funds 2025
    - mutual fund NAV explained
    - ELSS tax saving mutual funds
    - best small cap funds india
    ... 8-15 spoke articles per hub

A strong topical cluster signals domain expertise to Google,
dramatically boosting ranking probability for ALL articles in the cluster.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..config import Config
from ..utils.json_utils import gemini_json_call
from ..utils.logger import get_logger
from .embeddings_store import embed_text, get_similar_articles, load_embeddings

logger = get_logger("seo.topic_authority")

STATE_DIR      = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
TOPIC_MAP_FILE  = STATE_DIR / "topic_map.json"

# Cadialogue.in primary topic pillars
CADIALOGUE_PILLARS = [
    "Indian Stock Market & Equities",
    "Mutual Funds & SIP Investment",
    "RBI Monetary Policy & Banking",
    "Indian Economy & Budget",
    "Personal Finance & Tax Planning",
    "Gold & Commodity Prices India",
    "Cryptocurrency in India",
    "SEBI Regulations & IPO",
    "Real Estate India",
    "Chartered Accountant & ICAI",
    "Current Affairs India",
    "AI & Technology for Finance",
    "Startups & Venture Capital India",
    "GST & Taxation India",
]


# ── Persistence ───────────────────────────────────────────────────────────────

def load_topic_map() -> dict:
    """
    Load the topic authority map.
    Schema: {
      "pillars": [{
        "pillar_id": str,
        "name": str,
        "description": str,
        "hub_article": {post_id, url, title} | None,
        "spoke_articles": [{post_id, url, title, score}],
        "coverage_score": float,    # 0-1
        "gaps": [str],              # suggested missing articles
        "roadmap": [{title, kw, priority}],
      }],
      "authority_score": float,     # overall site authority 0-100
      "last_updated": float,
    }
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not TOPIC_MAP_FILE.exists():
        return {"pillars": [], "authority_score": 0, "last_updated": 0}
    try:
        return json.loads(TOPIC_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"pillars": [], "authority_score": 0, "last_updated": 0}


def save_topic_map(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TOPIC_MAP_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Pillar assignment ─────────────────────────────────────────────────────────

def _assign_article_to_pillar(
    post_title: str,
    post_excerpt: str,
    pillar_names: list[str],
    config: Config,
) -> tuple[str, float]:
    """
    Assign an article to the best-matching pillar using embedding cosine similarity.
    Returns (pillar_name, confidence_score).
    """
    if not config.has_openai:
        # Fallback: keyword matching
        text = f"{post_title} {post_excerpt}".lower()
        for pillar in pillar_names:
            if any(w in text for w in pillar.lower().split()[:3]):
                return pillar, 0.6
        return pillar_names[0], 0.3

    # Embed the article
    article_vec = embed_text(f"{post_title}. {post_excerpt[:300]}", config)

    # Embed each pillar name and find best match
    best_pillar = pillar_names[0]
    best_score  = -1.0

    from .embeddings_store import _cosine_similarity
    for pillar in pillar_names:
        p_vec = embed_text(pillar, config)
        score = _cosine_similarity(article_vec, p_vec)
        if score > best_score:
            best_score  = score
            best_pillar = pillar

    return best_pillar, round(best_score, 4)


# ── Content gap generation ─────────────────────────────────────────────────────

def _generate_content_roadmap(
    pillar_name: str,
    existing_titles: list[str],
    config: Config,
    n: int = 8,
) -> list[dict]:
    """
    Use GPT-4o to generate n article ideas that fill coverage gaps for a pillar.
    Considers existing articles to avoid duplication.
    """
    existing_str = "\n".join(f"- {t}" for t in existing_titles[:20])
    prompt = f"""You are an SEO content strategist for cadialogue.in, India's premier finance news site.

TOPIC PILLAR: "{pillar_name}"

ALREADY PUBLISHED (do NOT suggest duplicates):
{existing_str or "None yet"}

Generate {n} new article ideas that:
  1. Fill GAPS in coverage of this topic pillar
  2. Target LONG-TAIL keywords with low competition
  3. Are SPECIFIC to Indian readers (mention India, ₹, RBI, SEBI, NSE as relevant)
  4. Mix article types: how-to guides, comparisons, explainers, current-events analysis
  5. Are VALUABLE and INFORMATIVE — not generic or thin
  6. Are 800-2500 word articles (not short posts)

For each article, also suggest:
  - Focus keyword (1 long-tail keyword phrase, 4-8 words)
  - Search intent (informational / comparison / transactional)
  - Priority (high / medium / low) based on estimated search demand

Return ONLY JSON:
{{
  "roadmap": [
    {{
      "title": "article title",
      "focus_keyword": "main keyword phrase",
      "intent": "informational",
      "priority": "high",
      "rationale": "why this gaps exists / who searches for it"
    }}
  ]
}}"""

    try:
        result = gemini_json_call(config, prompt, max_tokens=1500)
        items  = result.get("roadmap", [])
        return [
            {
                "title":         str(item.get("title", ""))[:120],
                "focus_keyword": str(item.get("focus_keyword", ""))[:80],
                "intent":        str(item.get("intent", "informational")),
                "priority":      str(item.get("priority", "medium")),
                "rationale":     str(item.get("rationale", ""))[:200],
                "pillar":        pillar_name,
                "generated_at":  time.time(),
            }
            for item in items
            if item.get("title")
        ][:n]
    except Exception as exc:
        logger.warning(f"Roadmap gen failed for '{pillar_name}': {exc}")
        return []


# ── Coverage scoring ──────────────────────────────────────────────────────────

def _score_pillar_coverage(n_articles: int) -> float:
    """
    Estimate coverage completeness (0.0 → 1.0) based on article count.
    A well-covered pillar needs ~15 articles for full topical authority.
    """
    TARGET = 15
    return min(1.0, n_articles / TARGET)


# ── Main rebuild ──────────────────────────────────────────────────────────────

def rebuild_topic_map(config: Config, all_posts: list[dict]) -> dict:
    """
    Rebuild the full topical authority map from all published WP posts.

    Steps:
      1. For each post, embed and assign to the best pillar
      2. Score coverage per pillar
      3. Generate roadmap gaps for each pillar
      4. Compute overall authority score

    This is a slow operation (~1-2 min for 50 posts) — run once daily or on demand.
    """
    logger.info(f"Rebuilding topic map for {len(all_posts)} posts…")

    # Load existing map to preserve roadmap items
    existing_map   = load_topic_map()
    pillar_buckets : dict[str, list[dict]] = {p: [] for p in CADIALOGUE_PILLARS}

    for post in all_posts:
        title   = post.get("title", {}).get("rendered", "")
        excerpt = post.get("excerpt", {}).get("rendered", "")
        # Strip HTML
        import re
        title   = re.sub(r"<[^>]+>", "", title).strip()
        excerpt = re.sub(r"<[^>]+>", "", excerpt).strip()[:300]

        try:
            pillar, score = _assign_article_to_pillar(
                title, excerpt, CADIALOGUE_PILLARS, config
            )
            pillar_buckets[pillar].append({
                "post_id": post.get("id"),
                "url":     post.get("link", ""),
                "title":   title,
                "score":   score,
            })
        except Exception as exc:
            logger.debug(f"Pillar assign failed for '{title[:40]}': {exc}")

    # Build pillar records
    pillars: list[dict] = []
    total_coverage = 0.0

    for pillar_name in CADIALOGUE_PILLARS:
        articles       = pillar_buckets.get(pillar_name, [])
        coverage_score = _score_pillar_coverage(len(articles))
        total_coverage += coverage_score

        # Sort articles: hub (most links / most comprehensive) first
        articles.sort(key=lambda x: x.get("score", 0), reverse=True)
        hub = articles[0] if articles else None

        # Generate content gaps for under-covered pillars
        gaps_roadmap: list[dict] = []
        if coverage_score < 0.8:
            try:
                existing_titles = [a["title"] for a in articles]
                gaps_roadmap    = _generate_content_roadmap(
                    pillar_name, existing_titles, config, n=6
                )
            except Exception as exc:
                logger.warning(f"Gap gen failed for '{pillar_name}': {exc}")

        pillars.append({
            "pillar_id":      pillar_name.lower().replace(" ", "_").replace("&", "and")[:40],
            "name":           pillar_name,
            "hub_article":    hub,
            "spoke_articles": articles[1:] if hub else articles,
            "article_count":  len(articles),
            "coverage_score": round(coverage_score, 3),
            "roadmap":        gaps_roadmap,
        })

    # Overall authority score: avg coverage × 100
    authority_score = round(total_coverage / len(CADIALOGUE_PILLARS) * 100, 1)

    topic_map = {
        "pillars":         pillars,
        "authority_score": authority_score,
        "last_updated":    time.time(),
        "total_articles":  len(all_posts),
    }
    save_topic_map(topic_map)

    logger.info(f"Topic map rebuilt. Authority score: {authority_score}/100")
    return topic_map


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_top_roadmap_items(max_priority: str = "any", top_n: int = 20) -> list[dict]:
    """Return highest-priority roadmap items across all pillars."""
    topic_map = load_topic_map()
    items: list[dict] = []
    priority_order = {"high": 0, "medium": 1, "low": 2}

    for pillar in topic_map.get("pillars", []):
        for item in pillar.get("roadmap", []):
            items.append(item)

    if max_priority != "any":
        items = [i for i in items if i.get("priority") == max_priority]

    items.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))
    return items[:top_n]


def get_coverage_report() -> dict:
    """Return a concise coverage report for the dashboard."""
    topic_map   = load_topic_map()
    pillars     = topic_map.get("pillars", [])
    total_gaps  = sum(len(p.get("roadmap", [])) for p in pillars)
    weak        = [p for p in pillars if p.get("coverage_score", 0) < 0.4]

    return {
        "authority_score":    topic_map.get("authority_score", 0),
        "total_pillars":      len(pillars),
        "weak_pillars":       len(weak),
        "total_articles":     topic_map.get("total_articles", 0),
        "total_gap_articles": total_gaps,
        "last_updated":       topic_map.get("last_updated", 0),
    }
