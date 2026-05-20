"""
Per-topic article generator and publisher.
Called by FastAPI POST /runs/{id}/generate after the user approves a topic.

Flow (with human review gate):
  approved → generating → article_ready → pending_review →
    (user clicks Approve)  → publishing → published
    (user clicks Reject)   → rejected
    (fact-validator FAIL)  → pending_review with `requires_attention=true`

Articles are pushed to WordPress as DRAFTS during the article_ready step so
the user can preview them at /wp-admin. They only become public ("publish")
when the user explicitly approves via POST /runs/{id}/approve-for-publish.
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

        # ── Stage 3b: Fact-validation safety net ─────────────────────────────
        #     Scans for [UNVERIFIED:...] markers and numbers not traceable to
        #     verified facts / live market data. Result is attached to the run
        #     so the reviewer sees flags in the dashboard.
        from ..writer.fact_validator import validate_article
        validation = validate_article(article, facts, market)
        tracker.update_run(run_id, fact_validation=validation.to_dict())
        tracker.log(
            run_id, "info" if validation.is_clean else "warn",
            "fact_validation", validation.summary
        )

        # ── Auto-save to topic library ────────────────────────────────────────
        try:
            from ..library.topic_library import save_from_run
            updated_run = tracker.load_run(run_id)
            if updated_run:
                save_from_run(updated_run, added_by="pipeline")
        except Exception as lib_exc:
            logger.warning(f"Library auto-save failed (non-fatal): {lib_exc}")

        # ── Stage 4: Save as WordPress DRAFT (not publish) ───────────────────
        #     The article needs human review before going public. We push it
        #     to WordPress as a DRAFT so the user can preview the rendered
        #     post at /wp-admin/post.php?post=ID&action=edit before approving.
        tracker.update_topic_status(run_id, "saving_draft")
        tracker.log(run_id, "info", "draft", "Saving article as WordPress draft for review…")
        await _emit("stage", stage="saving_draft", message="Saving draft for review…")

        from ..publisher.wordpress_client import publish_post
        category = topic_meta.get("category", "global_market")
        wp_post = await publish_post(
            article, seo_meta, schemas, config,
            category=category,
            status="draft",                       # ← DRAFT, not publish
        )
        draft_url   = wp_post.get("link", "")
        preview_url = f"{config.wp_url}/?p={wp_post['id']}&preview=true"
        admin_url   = f"{config.wp_url}/wp-admin/post.php?post={wp_post['id']}&action=edit"

        tracker.update_run(
            run_id,
            wp_post_id=wp_post["id"],
            wp_post_url=draft_url,
            wp_preview_url=preview_url,
            wp_admin_url=admin_url,
        )
        tracker.update_topic_status(run_id, "pending_review")
        tracker.log(run_id, "info", "pending_review",
                    f"Draft saved (post #{wp_post['id']}). Awaiting human approval.")
        await _emit(
            "status",
            topic_status="pending_review",
            wp_post_id=wp_post["id"],
            wp_preview_url=preview_url,
            wp_admin_url=admin_url,
            fact_validation=validation.to_dict(),
            stage="pending_review",
        )
        # STOP HERE — DO NOT auto-publish. Wait for user via approve-for-publish endpoint.

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
