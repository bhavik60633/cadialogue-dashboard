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
    Discover n topics, create a MorningBatch and n TopicRun entries.
    Returns {"batch_id": "batch_2026-05-07", "topic_run_ids": [...]}
    """
    config = load_config()
    logger.info(f"Starting morning batch discovery (n={n})…")

    # ── Step 1: Market snapshot ───────────────────────────────────────────────
    market = await fetch_market_snapshot()
    logger.info("Market snapshot fetched")

    # ── Step 2: Topic discovery ───────────────────────────────────────────────
    topics = await find_topics_batch(config, market, n=n)
    logger.info(f"Discovered {len(topics)} topics")

    # ── Step 3: Determine batch date / ID ────────────────────────────────────
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch_id = f"batch_{today}"

    # ── Step 4: Create TopicRun entries ──────────────────────────────────────
    run_ids = []
    for idx, topic in enumerate(topics):
        # Build rich source list
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
        run_id = run_tracker.init_topic_run(batch_id, topic_meta, run_index=idx)
        run_ids.append(run_id)
        logger.info(f"  [{idx+1:02d}] {topic.title[:60]} -> {run_id}")

    # ── Step 5: Create / replace batch record ────────────────────────────────
    batch = batch_tracker.create_batch(run_ids)
    logger.info(f"Batch {batch['id']} created with {len(run_ids)} runs")

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
