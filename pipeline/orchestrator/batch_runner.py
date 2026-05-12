"""
Morning batch runner — discovers N topics and writes them to the state files.
Called by the FastAPI endpoint POST /batches/today/refresh.
Also callable directly for testing:
    python -m pipeline.orchestrator.batch_runner
"""
import asyncio
from ..config import load_config
from ..research.market_data import fetch_market_snapshot
from ..research.topic_finder import find_topics_batch
from ..state import batch_tracker, run_tracker
from ..utils.logger import get_logger

logger = get_logger("batch_runner")


async def run_morning_batch(n: int = 10) -> dict:
    """
    Discover n topics and write them to the state files.
    On refresh: slots that already have an approved / generating / article_ready /
    images_ready / publishing / published / failed run are PRESERVED unchanged.
    Only pending or rejected slots are replaced with fresh topics.
    Returns {"batch_id": "batch_2026-05-07", "topic_run_ids": [...]}
    """
    config = load_config()
    logger.info(f"Starting morning batch discovery (n={n})…")

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch_id = f"batch_{today}"

    # Statuses that mean a run has real work done — do NOT overwrite on refresh
    PRESERVE = frozenset({
        "approved", "generating", "article_ready",
        "images_ready", "publishing", "published", "failed",
    })

    # ── Step 1: Find already-occupied slots ───────────────────────────────────
    # Scan generously (n + 20) to catch any manually-promoted runs beyond slot n
    preserved: dict[int, str] = {}   # slot_index → run_id
    for slot in range(n + 20):
        run_id = f"{today}-t{slot:02d}"
        existing = run_tracker.load_run(run_id)
        if existing and existing.get("topic_status") in PRESERVE:
            preserved[slot] = run_id

    new_needed = max(0, n - len(preserved))
    logger.info(
        f"Preserved {len(preserved)} existing run(s) — "
        f"fetching {new_needed} new topic(s)"
    )

    # ── Step 2: Market snapshot ───────────────────────────────────────────────
    market = await fetch_market_snapshot()
    logger.info("Market snapshot fetched")

    # ── Step 3: Topic discovery (only as many fresh slots as we need) ─────────
    topics = await find_topics_batch(config, market, n=new_needed) if new_needed > 0 else []
    logger.info(f"Discovered {len(topics)} new topic(s)")

    # ── Step 4: Assign new topics to free slots ───────────────────────────────
    run_ids: list[str] = []
    topic_iter = iter(topics)

    for slot in range(n + 20):
        if len(run_ids) >= n:
            break

        if slot in preserved:
            # Keep the existing run untouched
            run_ids.append(preserved[slot])
            logger.info(
                f"  [{slot+1:02d}] ↺ kept  {preserved[slot]}"
                f"  ({run_tracker.load_run(preserved[slot]).get('topic_status', '?')})"
            )
            continue

        # Free slot — fill with the next new topic
        topic = next(topic_iter, None)
        if topic is None:
            break

        rich_sources = getattr(topic, "rich_sources", None)
        if rich_sources and isinstance(rich_sources[0], dict):
            sources = rich_sources
        else:
            sources = [{"url": s, "publisher": _publisher_from_url(s)} for s in topic.sources]

        topic_meta = {
            "title": topic.title,
            "summary": topic.summary,
            "category": topic.category,
            "sources": sources,
            "score": round(topic.score, 1),
            "added_by": None,
            "keywords": topic.keywords,
        }
        run_id = run_tracker.init_topic_run(batch_id, topic_meta, run_index=slot)
        run_ids.append(run_id)
        logger.info(f"  [{slot+1:02d}] new   {topic.title[:60]} -> {run_id}")

    # ── Step 5: Write batch record ────────────────────────────────────────────
    batch = batch_tracker.create_batch(run_ids)
    logger.info(
        f"Batch {batch['id']} updated: {len(run_ids)} total "
        f"({len(preserved)} preserved, {len(topics)} new)"
    )

    return {"batch_id": batch["id"], "topic_run_ids": run_ids}


def _publisher_from_url(url: str) -> str:
    """Extract a readable publisher name from a URL."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        host = host.removeprefix("www.")
        # Map common domains to display names
        publisher_map = {
            "economictimes.indiatimes.com": "Economic Times",
            "livemint.com": "Mint",
            "moneycontrol.com": "Moneycontrol",
            "business-standard.com": "Business Standard",
            "bloomberg.com": "Bloomberg",
            "reuters.com": "Reuters",
            "rbi.org.in": "RBI",
            "sebi.gov.in": "SEBI",
            "pib.gov.in": "PIB",
            "incometax.gov.in": "Income Tax Dept",
            "ndtv.com": "NDTV",
            "thehindubusinessline.com": "The Hindu",
            "financialexpress.com": "Financial Express",
            "coindesk.com": "CoinDesk",
            "wsj.com": "WSJ",
        }
        return publisher_map.get(host, host.split(".")[0].title())
    except Exception:
        return "Unknown"


if __name__ == "__main__":
    result = asyncio.run(run_morning_batch())
    print(f"Done: {result}")
