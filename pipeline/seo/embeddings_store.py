"""
Article Embeddings Store — semantic similarity backbone for the entire SEO engine.

Uses OpenAI text-embedding-3-small (1536-dim, ~$0.0001/1K tokens).
Stores embeddings in pipeline/state/seo/article_embeddings.json.

Every published WP post gets an embedding of:
  "{title}. {excerpt_clean}. Categories: {cats}. Slug: {slug}"

This powers:
  - Internal linking (find semantically related articles)
  - Topic clustering (group articles by semantic proximity)
  - Content gap detection (find under-covered topics)
  - Duplicate content prevention
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("seo.embeddings")

STATE_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
EMBEDDINGS_FILE = STATE_DIR / "article_embeddings.json"
EMBEDDING_MODEL  = "text-embedding-3-small"   # 1536-dim, low cost
EMBEDDING_DIM    = 1536


# ── Utilities ─────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot-product cosine similarity — avoids numpy dependency."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Persistence ───────────────────────────────────────────────────────────────

def load_embeddings() -> dict:
    """Load all stored embeddings as {str(post_id): record_dict}."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not EMBEDDINGS_FILE.exists():
        return {}
    try:
        return json.loads(EMBEDDINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_embeddings(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Text builder ──────────────────────────────────────────────────────────────

def build_article_text(post: dict) -> str:
    """
    Build a compact text representation of a WP post for embedding.
    Keeps the most semantically dense fields; strips HTML.
    """
    title    = _strip_html(post.get("title", {}).get("rendered", ""))
    excerpt  = _strip_html(post.get("excerpt", {}).get("rendered", ""))[:400]
    slug     = post.get("slug", "")

    # Category names from _embedded
    cats: list[str] = []
    for term_group in post.get("_embedded", {}).get("wp:term", []):
        for term in term_group:
            if term.get("taxonomy") == "category":
                cats.append(term.get("name", ""))

    # Focus keyword from RankMath meta (if available)
    fk = (post.get("meta") or {}).get("rank_math_focus_keyword", "")

    parts = [title, excerpt]
    if cats:
        parts.append(f"Categories: {', '.join(cats)}")
    if fk:
        parts.append(f"Keyword: {fk}")
    parts.append(f"Slug: {slug}")

    return ". ".join(filter(None, parts))


# ── Core API ──────────────────────────────────────────────────────────────────

def embed_text(text: str, config: Config) -> list[float]:
    """
    Generate embedding vector for arbitrary text.
    Requires OpenAI API key.  Cost: ~$0.00002 per call.
    """
    if not config.has_openai:
        raise ValueError("OpenAI API key required for embeddings (text-embedding-3-small)")

    client = config.make_ai_client()
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000],          # ~6 K tokens max; article text fits easily
    )
    return resp.data[0].embedding


def upsert_article_embedding(post: dict, config: Config) -> dict:
    """
    Generate (or refresh) the embedding for a single WP post and persist it.
    Returns the full embedding record.

    Record schema:
    {
      "post_id": int,
      "title": str,
      "url": str,
      "slug": str,
      "excerpt": str,         # plain text, max 300 chars
      "embedding": [float×1536],
      "updated_at": float,    # unix timestamp
    }
    """
    text    = build_article_text(post)
    vector  = embed_text(text, config)

    record  = {
        "post_id":    post["id"],
        "title":      _strip_html(post.get("title", {}).get("rendered", "")),
        "url":        post.get("link", ""),
        "slug":       post.get("slug", ""),
        "excerpt":    _strip_html(post.get("excerpt", {}).get("rendered", ""))[:300],
        "embedding":  vector,
        "updated_at": time.time(),
    }

    data = load_embeddings()
    data[str(post["id"])] = record
    save_embeddings(data)

    logger.debug(f"Embedded post {post['id']}: {record['title'][:60]}")
    return record


def get_similar_articles(
    query_embedding: list[float],
    all_embeddings: dict,
    exclude_ids: list[int] | None = None,
    top_k: int = 20,
    min_score: float = 0.35,
) -> list[dict]:
    """
    Return top-k most semantically similar articles, sorted desc by similarity.

    Each result: {post_id, title, url, slug, excerpt, score}
    """
    exclude = set(exclude_ids or [])
    scored: list[dict] = []

    for pid_str, rec in all_embeddings.items():
        pid = int(pid_str)
        if pid in exclude:
            continue
        emb = rec.get("embedding", [])
        if len(emb) != EMBEDDING_DIM:
            continue
        score = _cosine_similarity(query_embedding, emb)
        if score < min_score:
            continue
        scored.append({
            "post_id": pid,
            "title":   rec.get("title", ""),
            "url":     rec.get("url", ""),
            "slug":    rec.get("slug", ""),
            "excerpt": rec.get("excerpt", ""),
            "score":   round(score, 4),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def rebuild_all_embeddings(config: Config, all_posts: list[dict]) -> int:
    """
    Rebuild embeddings for ALL posts.
    Typically called once from /seo/embeddings/rebuild endpoint.
    Returns number of posts embedded.
    """
    count = 0
    for post in all_posts:
        try:
            upsert_article_embedding(post, config)
            count += 1
        except Exception as exc:
            logger.warning(f"Embed failed for post {post.get('id')}: {exc}")
    logger.info(f"Rebuilt {count}/{len(all_posts)} article embeddings")
    return count
