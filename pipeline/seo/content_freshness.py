"""
Content Freshness Engine — detect stale content, schedule updates.

Finance content decays fast:
  - RBI rate decisions → 90 days
  - Stock market analysis → 60 days
  - Tax guides → 365 days (annual filing)
  - Crypto → 30 days
  - General economy → 180 days

When content is stale, this engine:
  1. Identifies the most-visited stale articles (by WP comment count proxy)
  2. Uses GPT-4o to suggest specific update sections
  3. Optionally auto-generates update paragraphs
  4. Updates the article's "Last Updated" date in WP

This prevents "content decay" — the gradual ranking loss as information ages.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal

from ..config import Config
from ..utils.json_utils import gemini_json_call
from ..utils.logger import get_logger

logger = get_logger("seo.freshness")

STATE_DIR      = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
FRESHNESS_FILE = STATE_DIR / "freshness.json"

# Category → max age in days before we flag as stale
CATEGORY_MAX_AGE: dict[str, int] = {
    "Crypto":           30,
    "Markets":          60,
    "Banking":          90,
    "Economy":          90,
    "Startups":         120,
    "Real Estate":      150,
    "Mutual Funds":     120,
    "Personal Finance": 240,
    "Tax & GST":        365,
    "Chartered Accountant": 365,
    "Current Affairs":  45,
    "AI & Technology":  60,
    "Marketing":        180,
    "Opinion":          180,
    "default":          120,
}


# ── Persistence ───────────────────────────────────────────────────────────────

def load_freshness() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not FRESHNESS_FILE.exists():
        return {"articles": {}, "last_scan": 0}
    try:
        return json.loads(FRESHNESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"articles": {}, "last_scan": 0}


def save_freshness(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FRESHNESS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Decay detection ───────────────────────────────────────────────────────────

def _get_post_categories(post: dict) -> list[str]:
    cats: list[str] = []
    for term_group in post.get("_embedded", {}).get("wp:term", []):
        for term in term_group:
            if term.get("taxonomy") == "category":
                cats.append(term.get("name", ""))
    return cats


def _max_age_for_post(post: dict) -> int:
    cats    = _get_post_categories(post)
    max_age = CATEGORY_MAX_AGE["default"]
    for cat in cats:
        if cat in CATEGORY_MAX_AGE:
            # Use the strictest (shortest) max age if multiple categories match
            max_age = min(max_age, CATEGORY_MAX_AGE[cat])
    return max_age


def _age_days(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        import dateutil.parser
        dt       = dateutil.parser.parse(date_str)
        age_secs = time.time() - dt.timestamp()
        return max(0, int(age_secs / 86400))
    except Exception:
        return None


def scan_stale_articles(all_posts: list[dict]) -> dict:
    """
    Scan all published posts for content staleness.
    Returns dict with stale/fresh lists and overall stats.

    Staleness is determined by:
      - Days since last modified vs category-specific max age
      - Articles are flagged "critical", "warning", or "ok"
    """
    data    = load_freshness()
    stale   : list[dict] = []
    warning : list[dict] = []
    fresh   : list[dict] = []

    for post in all_posts:
        pid        = post.get("id")
        title      = re.sub(r"<[^>]+>", "", post.get("title", {}).get("rendered", ""))
        modified   = post.get("modified") or post.get("date")
        categories = _get_post_categories(post)
        max_age    = _max_age_for_post(post)
        age        = _age_days(modified)

        if age is None:
            continue

        pct_used = (age / max_age) * 100

        record = {
            "post_id":   pid,
            "title":     title,
            "url":       post.get("link", ""),
            "age_days":  age,
            "max_age":   max_age,
            "pct_stale": round(pct_used, 1),
            "categories": categories,
            "modified":  modified,
        }

        if pct_used >= 100:
            record["status"] = "critical"
            stale.append(record)
        elif pct_used >= 75:
            record["status"] = "warning"
            warning.append(record)
        else:
            record["status"] = "ok"
            fresh.append(record)

        data["articles"][str(pid)] = record

    # Sort by staleness
    stale.sort(key=lambda x: x["pct_stale"], reverse=True)
    warning.sort(key=lambda x: x["pct_stale"], reverse=True)

    data["last_scan"]   = time.time()
    data["stale_count"] = len(stale)
    data["warning_count"] = len(warning)
    save_freshness(data)

    return {
        "stale":   stale,
        "warning": warning,
        "fresh":   fresh,
        "stats":   {
            "total":    len(all_posts),
            "stale":    len(stale),
            "warning":  len(warning),
            "fresh":    len(fresh),
        },
    }


# ── Update suggestion ─────────────────────────────────────────────────────────

def suggest_updates_for_article(
    post: dict,
    config: Config,
) -> dict:
    """
    Use GPT-4o to analyse a stale article and suggest specific update actions.
    Returns structured update plan.
    """
    title    = re.sub(r"<[^>]+>", "", post.get("title", {}).get("rendered", ""))
    content  = re.sub(r"<[^>]+>", " ", post.get("content", {}).get("rendered", ""))
    content  = re.sub(r"\s+", " ", content).strip()[:3000]
    modified = post.get("modified") or post.get("date", "")
    cats     = _get_post_categories(post)

    prompt = f"""You are a senior finance content editor at cadialogue.in (Indian finance news).

ARTICLE TITLE: "{title}"
CATEGORIES: {', '.join(cats)}
LAST UPDATED: {modified[:10] if modified else "unknown"}

ARTICLE CONTENT (partial):
{content}

This article is flagged as STALE. Identify:

1. Specific OUTDATED SECTIONS that need fresh data (e.g., "The section on RBI repo rate shows 6.5% — current rate is X%")
2. NEW DEVELOPMENTS since publication that should be added
3. STATISTICS or figures that likely need updating
4. Any BROKEN ARGUMENTS that no longer hold given market changes

Return ONLY JSON:
{{
  "update_priority": "critical|high|medium",
  "outdated_sections": ["section heading or first few words of the section"],
  "new_developments_to_add": ["brief description of what to add"],
  "stale_data_points": ["what specific data is likely outdated"],
  "suggested_additions": ["new paragraph or section idea"],
  "estimated_update_time": "15 min|30 min|1 hour"
}}"""

    try:
        result = gemini_json_call(config, prompt, max_tokens=600)
        result["post_id"]    = post.get("id")
        result["title"]      = title
        result["analysed_at"] = time.time()
        return result
    except Exception as exc:
        logger.warning(f"Update suggestion failed for post {post.get('id')}: {exc}")
        return {"post_id": post.get("id"), "error": str(exc)}


def get_freshness_report() -> dict:
    """Return concise freshness stats for the SEO dashboard."""
    data = load_freshness()
    return {
        "stale_count":   data.get("stale_count", 0),
        "warning_count": data.get("warning_count", 0),
        "last_scan":     data.get("last_scan", 0),
        "top_stale":     sorted(
            [v for v in data.get("articles", {}).values() if v.get("status") == "critical"],
            key=lambda x: x.get("pct_stale", 0),
            reverse=True,
        )[:5],
    }
