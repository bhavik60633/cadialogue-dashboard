"""
Finance Blog Pipeline — Daily Orchestrator
==========================================
Runs at 7:00 AM IST via GitHub Actions (cron: 30 1 * * *).
Can also be triggered manually via workflow_dispatch or locally.

Stages:
  1. Research   — find trending finance topics (India + Global)
  2. Approval 1 — Telegram: pick topic (30 min window, auto-selects #1)
  3. Fact-check — verify data points against official sources
  4. Write      — Claude API 2-pass: draft → humanize
  5. Approval 2 — Telegram: approve/reject article (2 hr window)
  6. Publish    — WordPress REST API + SEO meta
  7. Index      — Google Indexing API + IndexNow
  8. Distribute — Telegram channel + Twitter (optional)
"""
import asyncio
import traceback

from .config import load_config
from .state import run_tracker as tracker
from .utils.logger import get_logger

logger = get_logger("main")


async def run_pipeline() -> None:
    config = load_config()
    run_id = tracker.init_run()

    try:
        # ── Stage 1: Research ─────────────────────────────────────────────
        tracker.log(run_id, "info", "research", "Starting topic research…")
        from .research.topic_finder import find_top_topics
        from .research.market_data import fetch_market_snapshot

        market = await fetch_market_snapshot()
        topics = await find_top_topics(config, market)
        tracker.log(run_id, "info", "research", f"Found {len(topics)} topics. Top: {topics[0].title}")
        tracker.update_run(run_id, status="pending_approval")

        # ── Stage 2: Topic selection (Checkpoint 1 — HUMAN OPTIONAL) ─────
        tracker.log(run_id, "info", "topic_selection", "Sending topics to Telegram…")
        from .approval.approval_flow import run_topic_selection

        selected_topic = await run_topic_selection(topics, config)
        tracker.log(run_id, "info", "topic_selection", f"Selected: {selected_topic.title}")
        tracker.update_run(run_id, topic=selected_topic.title)

        # ── Stage 3: Fact-check ───────────────────────────────────────────
        tracker.log(run_id, "info", "fact_check", "Verifying data points…")
        from .research.fact_checker import fact_check_topic

        verified_facts = await fact_check_topic(selected_topic, market)
        tracker.log(run_id, "info", "fact_check", f"Verified {len(verified_facts)} facts")

        # ── Stage 4: Write ────────────────────────────────────────────────
        tracker.log(run_id, "info", "writing", "Generating article draft…")
        from .writer.article_generator import generate_draft, generate_seo_meta
        from .writer.humanizer import humanize_article
        from .writer.schema_builder import build_all_schemas

        draft = await generate_draft(selected_topic, market, verified_facts, config)
        tracker.log(run_id, "info", "writing", "Draft complete. Humanizing…")

        article = await humanize_article(draft, config)
        seo_meta = await generate_seo_meta(article, selected_topic, config)
        schemas = build_all_schemas(article, seo_meta)

        word_count = len(article.split())
        tracker.log(run_id, "info", "writing", f"Article ready: {word_count} words")
        tracker.update_run(run_id, article_word_count=word_count)

        # ── Stage 5: Article approval (Checkpoint 2 — HUMAN RECOMMENDED) ─
        tracker.log(run_id, "info", "article_approval", "Sending draft for approval…")
        from .approval.approval_flow import run_article_approval

        approval = await run_article_approval(article, seo_meta, config)

        if approval.save_as_draft:
            # Timed out — save as WP draft, do not publish
            tracker.log(run_id, "warning", "article_approval", "Approval timed out — saving as WP draft")
            from .publisher.wordpress_client import save_as_draft
            wp_post = await save_as_draft(approval.article, seo_meta, schemas, config)
            tracker.update_run(
                run_id,
                wp_post_id=wp_post["id"],
                wp_post_url=wp_post["link"],
                approval_status="draft_saved",
                status="completed",
            )
            tracker.log(run_id, "info", "done", f"Saved as WP draft: {wp_post['link']}")
            return

        tracker.update_run(run_id, approval_status="approved")

        # ── Stage 6: Publish ──────────────────────────────────────────────
        tracker.log(run_id, "info", "publish", "Publishing to WordPress…")
        from .publisher.wordpress_client import publish_post

        wp_post = await publish_post(approval.article, seo_meta, schemas, config)
        post_url = wp_post["link"]
        tracker.log(run_id, "info", "publish", f"Published: {post_url}")
        tracker.update_run(run_id, wp_post_id=wp_post["id"], wp_post_url=post_url)

        # ── Stage 7: Index ────────────────────────────────────────────────
        tracker.log(run_id, "info", "index", "Pinging search engines…")
        from .publisher.indexer import ping_all

        index_results = await ping_all(post_url, config)
        tracker.log(run_id, "info", "index", f"Indexing results: {index_results}")

        # ── Stage 8: Distribute ───────────────────────────────────────────
        tracker.log(run_id, "info", "distribute", "Distributing to social channels…")
        from .social.telegram_channel import post_to_channel
        from .social.twitter_poster import post_tweet

        if config.telegram_channel_id:
            await post_to_channel(post_url, seo_meta, config)

        if config.twitter_api_key:
            await post_tweet(post_url, seo_meta, config)

        # ── Checkpoint 3: Completion notification (informational) ─────────
        from .approval.telegram_bot import send_notification

        msg = (
            f"Published Successfully!\n\n"
            f"Title: {seo_meta.title}\n"
            f"URL: {post_url}\n"
            f"Words: {word_count}\n\n"
            f"Indexing: Google ✓ | Bing ✓ | Yandex ✓"
        )
        await send_notification(config.telegram_bot_token, config.telegram_chat_id, msg)

        tracker.complete_run(run_id, post_url)
        logger.info(f"Pipeline run {run_id} completed successfully.")

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(f"Pipeline run {run_id} FAILED:\n{tb}")
        tracker.fail_run(run_id, str(exc))

        # Try to notify via Telegram even on failure
        try:
            from .approval.telegram_bot import send_notification
            cfg = load_config()
            await send_notification(
                cfg.telegram_bot_token,
                cfg.telegram_chat_id,
                f"Pipeline FAILED (run {run_id}):\n{exc}",
            )
        except Exception:
            pass

        raise


if __name__ == "__main__":
    asyncio.run(run_pipeline())
