"""
Per-topic article generator and publisher.
Called by FastAPI POST /runs/{id}/generate after the user approves a topic.

Flow (Phase 1 — no images):
  approved → generating → article_ready → publishing → published
"""
import asyncio
import traceback

from ..config import load_config
from ..research.topic_finder import ScoredTopic, CATEGORY_MAP
from ..state import run_tracker as tracker
from ..utils.logger import get_logger

logger = get_logger("topic_runner")


async def run_topic(run_id: str) -> None:
    """
    Full generation + publishing pipeline for a single approved topic.
    Updates topic_status and publishes SSE events at each stage.
    Should be called as an asyncio background task.
    """
    from ..service.jobs import sse_publisher

    async def _emit(event_type: str, **data):
        await sse_publisher.publish(run_id, {"type": event_type, "run_id": run_id, **data})

    run = tracker.load_run(run_id)
    if not run:
        logger.error(f"run_topic: run {run_id} not found")
        return

    topic_meta = run.get("topic_meta") or {}

    config = load_config()

    try:
        # ── Mark as generating ────────────────────────────────────────────────
        tracker.update_topic_status(run_id, "generating")
        tracker.log(run_id, "info", "generating", "Starting article generation…")
        await _emit("status", topic_status="generating", stage="generating")

        # ── Stage 1: Market snapshot ──────────────────────────────────────────
        from ..research.market_data import fetch_market_snapshot
        market = await fetch_market_snapshot()
        tracker.log(run_id, "info", "market", "Market snapshot fetched")

        # ── Stage 2: Fact-check ───────────────────────────────────────────────
        tracker.log(run_id, "info", "fact_check", "Verifying data points…")
        await _emit("stage", stage="fact_check", message="Verifying facts…")
        from ..research.fact_checker import fact_check_topic

        # sources may be [{url, publisher}] dicts (batch flow) or plain URL strings (legacy)
        raw_sources = topic_meta.get("sources", topic_meta.get("sources_urls", []))
        sources_list = [s["url"] if isinstance(s, dict) else s for s in raw_sources]

        topic = ScoredTopic(
            title=topic_meta.get("title", "Finance Update"),
            summary=topic_meta.get("summary", ""),
            keywords=topic_meta.get("keywords", []),
            sources=sources_list,
            score=float(topic_meta.get("score", 50)),
            category=topic_meta.get("category", "global_market"),
        )

        facts = await fact_check_topic(topic, market)
        tracker.log(run_id, "info", "fact_check", f"Verified {len(facts)} facts")

        # ── Stage 3: Write ────────────────────────────────────────────────────
        tracker.log(run_id, "info", "writing", "Generating article draft…")
        await _emit("stage", stage="writing", message="Generating draft…")
        from ..writer.article_generator import generate_draft, generate_seo_meta
        from ..writer.humanizer import humanize_article
        from ..writer.schema_builder import build_all_schemas

        draft = await generate_draft(topic, market, facts, config)
        tracker.log(run_id, "info", "writing", "Draft complete. Humanizing…")
        await _emit("stage", stage="humanizing", message="Humanizing article…")

        article = await humanize_article(draft, config)
        seo_meta = await generate_seo_meta(article, topic, config)
        schemas = build_all_schemas(article, seo_meta)

        word_count = len(article.split())
        tracker.update_run(
            run_id,
            topic=topic_meta.get("title"),
            article_word_count=word_count,
        )
        # Store the generated article text and seo_meta for later use
        tracker.update_run(run_id, _article_draft=article, _seo_slug=seo_meta.slug)
        tracker.update_topic_status(run_id, "article_ready")
        tracker.log(run_id, "info", "writing", f"Article ready: {word_count} words")
        await _emit(
            "status",
            topic_status="article_ready",
            word_count=word_count,
            stage="article_ready",
        )

        # ── Auto-save to topic library ────────────────────────────────────────
        try:
            from ..library.topic_library import save_from_run
            updated_run = tracker.load_run(run_id)
            if updated_run:
                save_from_run(updated_run, added_by="pipeline")
        except Exception as lib_exc:
            logger.warning(f"Library auto-save failed (non-fatal): {lib_exc}")

        # ── Stage 4: Publish ──────────────────────────────────────────────────
        tracker.update_topic_status(run_id, "publishing")
        tracker.log(run_id, "info", "publish", "Publishing to WordPress…")
        await _emit("stage", stage="publishing", message="Publishing to WordPress…")

        from ..publisher.wordpress_client import publish_post
        category = topic_meta.get("category", "global_market")
        wp_post = await publish_post(article, seo_meta, schemas, config, category=category)
        post_url = wp_post["link"]
        tracker.log(run_id, "info", "publish", f"Published: {post_url}")
        tracker.update_run(run_id, wp_post_id=wp_post["id"], wp_post_url=post_url)

        # ── Stage 5: Index ────────────────────────────────────────────────────
        tracker.log(run_id, "info", "index", "Pinging search engines…")
        try:
            from ..publisher.indexer import ping_all
            await ping_all(post_url, config)
        except Exception as ie:
            logger.warning(f"Indexing failed (non-fatal): {ie}")

        # ── Completion ────────────────────────────────────────────────────────
        tracker.complete_run(run_id, post_url)
        tracker.update_topic_status(run_id, "published")
        tracker.log(run_id, "info", "done", f"Published: {post_url}")
        await _emit(
            "status",
            topic_status="published",
            wp_post_url=post_url,
            wp_post_id=wp_post["id"],
            stage="done",
        )

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(f"topic_runner: run {run_id} FAILED:\n{tb}")
        # Write full traceback to file so we can diagnose without terminal access
        try:
            from pathlib import Path
            Path(__file__).resolve().parents[2].joinpath(
                "pipeline", "state", "last_generation_error.txt"
            ).write_text(f"Run: {run_id}\nError: {exc}\n\n{tb}", encoding="utf-8")
        except Exception:
            pass
        tracker.fail_run(run_id, str(exc))
        tracker.update_topic_status(run_id, "failed")
        await _emit("error", message=str(exc), stage="failed", topic_status="failed")

    finally:
        await sse_publisher.close(run_id)
