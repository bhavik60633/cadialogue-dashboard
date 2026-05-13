"""
Sitemap Manager — ensure Google sees every new page immediately.

Actions after each publish:
  1. Ping Google via Google Search Console Indexing API
  2. Ping IndexNow (Bing + Yandex + other engines simultaneously)
  3. Submit sitemap URL to Google on major content milestones
  4. Track submission history to avoid spam

The mu-plugin / RankMath on WordPress already generates the XML sitemap
at /sitemap_index.xml — we don't need to build one from scratch.

What we DO here:
  - Notify search engines immediately when new content is published
  - Track which URLs have been submitted and when
  - Batch-submit old URLs that were never indexed (catch-up)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from ..config import Config
from ..publisher.indexer import submit_to_google_indexing
from ..utils.logger import get_logger

logger = get_logger("seo.sitemap")

STATE_DIR      = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
INDEX_LOG_FILE = STATE_DIR / "indexing_log.json"

INDEXNOW_API_URL = "https://api.indexnow.org/indexnow"
SITEMAP_URL      = "https://cadialogue.in/sitemap_index.xml"


# ── Persistence ───────────────────────────────────────────────────────────────

def load_index_log() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_LOG_FILE.exists():
        return {"submissions": {}, "last_batch": 0}
    try:
        return json.loads(INDEX_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"submissions": {}, "last_batch": 0}


def save_index_log(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_LOG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── IndexNow ─────────────────────────────────────────────────────────────────

def submit_indexnow(url: str, config: Config) -> bool:
    """
    Submit a single URL to IndexNow API (Bing, Yandex, Naver + others).
    Requires INDEXNOW_KEY in config (stored in .env as INDEXNOW_KEY).

    IndexNow is free and instant — submission takes <1 minute to propagate.
    """
    import os
    key = os.environ.get("INDEXNOW_KEY", "")
    if not key:
        logger.debug("IndexNow key not configured — skipping")
        return False

    domain = "cadialogue.in"
    payload = {
        "host":    domain,
        "key":     key,
        "urlList": [url],
        "keyLocation": f"https://{domain}/{key}.txt",
    }

    try:
        resp = requests.post(
            INDEXNOW_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code in (200, 202):
            logger.info(f"IndexNow: submitted {url} → {resp.status_code}")
            return True
        else:
            logger.warning(f"IndexNow: {resp.status_code} for {url}: {resp.text[:100]}")
            return False
    except Exception as exc:
        logger.warning(f"IndexNow submission failed for {url}: {exc}")
        return False


# ── Google Indexing API ───────────────────────────────────────────────────────

def submit_google(url: str, config: Config) -> bool:
    """
    Submit URL to Google Indexing API (requires service account JSON).
    Delegates to existing pipeline/publisher/indexer.py.
    """
    try:
        result = submit_to_google_indexing(url, config)
        logger.info(f"Google Indexing: submitted {url} → {result}")
        return True
    except Exception as exc:
        logger.warning(f"Google Indexing failed for {url}: {exc}")
        return False


# ── Main entry point ──────────────────────────────────────────────────────────

def notify_search_engines(url: str, config: Config) -> dict:
    """
    Notify all search engines about a newly published/updated URL.
    Called automatically after each WP publish.

    Returns status of each submission.
    """
    log = load_index_log()
    sub = log["submissions"].get(url, {})

    # Rate limit: don't re-submit the same URL more than once per hour
    last = sub.get("last_submitted", 0)
    if time.time() - last < 3600:
        logger.debug(f"Skipping {url} — submitted < 1 hour ago")
        return {"url": url, "skipped": True, "reason": "rate_limited"}

    google_ok   = submit_google(url, config)
    indexnow_ok = submit_indexnow(url, config)

    # Log submission
    log["submissions"][url] = {
        "url":            url,
        "last_submitted": time.time(),
        "google":         google_ok,
        "indexnow":       indexnow_ok,
        "count":          sub.get("count", 0) + 1,
    }
    save_index_log(log)

    return {
        "url":       url,
        "google":    google_ok,
        "indexnow":  indexnow_ok,
        "timestamp": time.time(),
    }


def batch_submit_unindexed(
    all_post_urls: list[str],
    config: Config,
    max_per_run: int = 50,
) -> dict:
    """
    Batch-submit URLs that have never been submitted or last submitted >30 days ago.
    Use this to catch up on old content.
    """
    log     = load_index_log()
    cutoff  = time.time() - (30 * 86400)   # 30 days
    pending = [
        url for url in all_post_urls
        if log["submissions"].get(url, {}).get("last_submitted", 0) < cutoff
    ][:max_per_run]

    submitted = 0
    for url in pending:
        result = notify_search_engines(url, config)
        if not result.get("skipped"):
            submitted += 1
        time.sleep(0.5)   # polite delay

    log["last_batch"] = time.time()
    save_index_log(log)

    return {
        "pending":   len(pending),
        "submitted": submitted,
        "timestamp": log["last_batch"],
    }


def ping_sitemap(config: Config) -> bool:
    """Ping Google to re-fetch the XML sitemap."""
    try:
        resp = requests.get(
            "https://www.google.com/ping",
            params={"sitemap": SITEMAP_URL},
            timeout=15,
        )
        ok = resp.status_code in (200, 204)
        logger.info(f"Sitemap ping → {resp.status_code}")
        return ok
    except Exception as exc:
        logger.warning(f"Sitemap ping failed: {exc}")
        return False
