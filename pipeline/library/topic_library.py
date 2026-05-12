"""
Topic Library — persistent store for curated topics.

Backed by pipeline/state/topic_library.json with filelock protection.
14 categories; topics can be manually added or auto-saved from batch runs,
and promoted to today's queue with one call.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger("topic_library")

LIBRARY_PATH = Path(__file__).resolve().parents[1] / "state" / "topic_library.json"

# ── Category registry ──────────────────────────────────────────────────────────
#
# Each key is the canonical internal category slug used in the library.
# The display_name shows in the sidebar.
# The CATEGORY_MAP in topic_finder.py uses different keys — we map them
# via LEGACY_ALIAS below so imported topics land in the right bucket.
#
CATEGORIES: dict[str, dict] = {
    "markets":              {"display": "Markets",             "emoji": "📈"},
    "economy":              {"display": "Economy",             "emoji": "🏛️"},
    "banking":              {"display": "Banking",             "emoji": "🏦"},
    "personal_finance":     {"display": "Personal Finance",    "emoji": "💰"},
    "mutual_funds":         {"display": "Mutual Funds",        "emoji": "📊"},
    "tax_gst":              {"display": "Tax & GST",           "emoji": "📋"},
    "real_estate":          {"display": "Real Estate",         "emoji": "🏠"},
    "startups":             {"display": "Startups",            "emoji": "🚀"},
    "crypto":               {"display": "Crypto",              "emoji": "₿"},
    "opinion":              {"display": "Opinion",             "emoji": "✍️"},
    "chartered_accountant": {"display": "Chartered Accountant","emoji": "📒"},
    "current_affairs":      {"display": "Current Affairs",     "emoji": "🗞️"},
    "marketing":            {"display": "Marketing",           "emoji": "📣"},
    "ai_technology":        {"display": "AI & Technology",     "emoji": "🤖"},
}

# Map topic_finder.py keys → library category keys
LEGACY_ALIAS: dict[str, str] = {
    "india_market":  "markets",
    "global_market": "markets",
    "regulation":    "banking",
}


def _canonical(category: str) -> str:
    """Resolve a category key to the canonical library key."""
    return LEGACY_ALIAS.get(category, category)


# ── I/O ────────────────────────────────────────────────────────────────────────


def _load() -> dict:
    if not LIBRARY_PATH.exists():
        return {"topics": []}
    try:
        return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"topics": []}


def _save(data: dict) -> None:
    LIBRARY_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Public API ─────────────────────────────────────────────────────────────────


def list_topics(category: Optional[str] = None, query: Optional[str] = None) -> list[dict]:
    """
    Return library topics, optionally filtered by category and/or free-text query.
    Sorted by added_at descending (newest first).
    """
    data = _load()
    topics = data.get("topics", [])

    if category:
        cat = _canonical(category)
        topics = [t for t in topics if _canonical(t.get("category", "")) == cat]

    if query:
        q = query.lower()
        topics = [
            t for t in topics
            if q in t.get("title", "").lower()
            or q in t.get("summary", "").lower()
        ]

    return sorted(topics, key=lambda t: t.get("added_at", ""), reverse=True)


def add_topic(
    title: str,
    summary: str,
    category: str,
    added_by: str,
    sources: Optional[list[dict]] = None,
    score: float = 0.0,
) -> dict:
    """
    Manually add a topic to the library.
    Returns the created topic dict.
    """
    data = _load()
    topic: dict = {
        "id":           f"lib_{uuid.uuid4().hex[:10]}",
        "title":        title.strip(),
        "summary":      summary.strip(),
        "category":     _canonical(category),
        "sources":      sources or [],
        "score":        score,
        "added_by":     added_by,
        "added_at":     datetime.now(timezone.utc).isoformat(),
        "promoted_at":  None,
        "promoted_to_batch": None,
    }
    data["topics"].append(topic)
    _save(data)
    logger.info(f"Library: added '{title}' (category={category}, by={added_by})")
    return topic


def get_topic(topic_id: str) -> Optional[dict]:
    data = _load()
    for t in data.get("topics", []):
        if t.get("id") == topic_id:
            return t
    return None


def update_topic(topic_id: str, **fields) -> Optional[dict]:
    """Update arbitrary fields on an existing library topic."""
    data = _load()
    for t in data["topics"]:
        if t.get("id") == topic_id:
            t.update(fields)
            _save(data)
            return t
    return None


def delete_topic(topic_id: str) -> bool:
    data = _load()
    before = len(data["topics"])
    data["topics"] = [t for t in data["topics"] if t.get("id") != topic_id]
    if len(data["topics"]) < before:
        _save(data)
        return True
    return False


def promote_topic_to_queue(topic_id: str, batch_id: str) -> Optional[dict]:
    """
    Mark a library topic as promoted to a batch queue.
    The caller is responsible for actually creating the TopicRun.
    """
    data = _load()
    for t in data["topics"]:
        if t.get("id") == topic_id:
            t["promoted_at"] = datetime.now(timezone.utc).isoformat()
            t["promoted_to_batch"] = batch_id
            _save(data)
            logger.info(f"Library: promoted '{t['title']}' to batch {batch_id}")
            return t
    return None


def category_counts() -> dict[str, int]:
    """Return {category_key: count} for the sidebar badges."""
    data = _load()
    counts: dict[str, int] = {k: 0 for k in CATEGORIES}
    for t in data.get("topics", []):
        cat = _canonical(t.get("category", ""))
        if cat in counts:
            counts[cat] += 1
    return counts


def save_from_run(run: dict, added_by: str = "system") -> Optional[dict]:
    """
    Auto-save a completed run's topic into the library (deduplication by title).
    Called by the pipeline after a successful article generation.
    """
    title = (run.get("topic_meta") or {}).get("title") or run.get("topic", "")
    if not title:
        return None

    # Deduplicate by normalised title
    data = _load()
    existing_titles = {t["title"].lower() for t in data["topics"]}
    if title.lower() in existing_titles:
        return None

    category = (run.get("topic_meta") or {}).get("category", "global_market")
    return add_topic(
        title=title,
        summary=(run.get("topic_meta") or {}).get("summary", ""),
        category=category,
        added_by=added_by,
        sources=(run.get("topic_meta") or {}).get("sources", []),
        score=float((run.get("topic_meta") or {}).get("score", 0)),
    )
