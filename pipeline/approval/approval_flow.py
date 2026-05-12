"""
Approval flow state machines.
Checkpoint 1: Topic selection (30 min window)
Checkpoint 2: Article approval (2 hour window)
"""
from dataclasses import dataclass
from typing import Optional

from ..config import Config
from ..research.topic_finder import ScoredTopic
from ..utils.logger import get_logger
from ..writer.article_generator import SEOMeta
from . import telegram_bot as bot

logger = get_logger("approval_flow")


@dataclass
class ApprovalResult:
    approved: Optional[bool]   # True=approved, False=rejected(regenerate), None=timeout
    article: str
    seo_meta: SEOMeta
    save_as_draft: bool = False


async def run_topic_selection(topics: list[ScoredTopic], config: Config) -> ScoredTopic:
    """
    Checkpoint 1: Send top 3 topics to Telegram.
    Wait up to topic_selection_timeout_minutes for user to pick.
    Auto-selects topics[0] on timeout.
    """
    timeout_sec = config.topic_selection_timeout_minutes * 60
    logger.info(f"Sending topic selection. Timeout: {config.topic_selection_timeout_minutes} min")

    msg_id = await bot.send_topic_selection(
        config.telegram_bot_token,
        config.telegram_chat_id,
        topics,
        auto_select_minutes=config.topic_selection_timeout_minutes,
    )

    result = await bot.poll_for_callback(
        bot_token=config.telegram_bot_token,
        timeout_seconds=timeout_sec,
        valid_message_id=msg_id,
    )

    if result is None:
        # Timeout — auto-select #1
        selected = topics[0]
        logger.info(f"Topic selection timed out. Auto-selected: {selected.title}")
        await bot.edit_message_text(
            config.telegram_bot_token,
            config.telegram_chat_id,
            msg_id,
            f"Auto-selected (no response): <b>{selected.title}</b>",
        )
    else:
        # User picked 1, 2, or 3 — callback_data is "1", "2", "3"
        try:
            idx = int(result.callback_data) - 1
            selected = topics[idx] if 0 <= idx < len(topics) else topics[0]
        except (ValueError, IndexError):
            selected = topics[0]

        logger.info(f"User selected topic {result.callback_data}: {selected.title}")
        await bot.edit_message_text(
            config.telegram_bot_token,
            config.telegram_chat_id,
            msg_id,
            f"Selected: <b>{selected.title}</b>",
        )

    return selected


async def run_article_approval(
    article: str,
    seo_meta: SEOMeta,
    config: Config,
    attempt: int = 1,
    max_regenerations: int = 2,
) -> ApprovalResult:
    """
    Checkpoint 2: Send article to Telegram for approval.
    - APPROVE → returns ApprovalResult(approved=True)
    - REJECT → regenerates and loops (max max_regenerations times)
    - Timeout → returns ApprovalResult(save_as_draft=True)
    """
    timeout_sec = config.article_approval_timeout_minutes * 60
    word_count = len(article.split())

    logger.info(
        f"Sending article for approval (attempt {attempt}/{max_regenerations}). "
        f"Timeout: {config.article_approval_timeout_minutes} min"
    )

    approval_msg_id = await bot.send_article_for_approval(
        config.telegram_bot_token,
        config.telegram_chat_id,
        article,
        seo_meta,
        word_count,
        auto_publish_minutes=config.article_approval_timeout_minutes,
    )

    result = await bot.poll_for_callback(
        bot_token=config.telegram_bot_token,
        timeout_seconds=timeout_sec,
        valid_message_id=approval_msg_id,
    )

    # ── Timeout ──────────────────────────────────────────────────────────
    if result is None:
        logger.warning("Article approval timed out — will save as WordPress draft")
        await bot.edit_message_text(
            config.telegram_bot_token,
            config.telegram_chat_id,
            approval_msg_id,
            "No response — saving as <b>WordPress draft</b> (not published)",
        )
        return ApprovalResult(
            approved=None,
            article=article,
            seo_meta=seo_meta,
            save_as_draft=True,
        )

    # ── Approved ──────────────────────────────────────────────────────────
    if result.callback_data == "approve":
        logger.info("Article APPROVED by user")
        await bot.edit_message_text(
            config.telegram_bot_token,
            config.telegram_chat_id,
            approval_msg_id,
            "APPROVED — publishing to WordPress…",
        )
        return ApprovalResult(approved=True, article=article, seo_meta=seo_meta)

    # ── Rejected — regenerate ─────────────────────────────────────────────
    if result.callback_data == "reject":
        logger.info(f"Article REJECTED. Attempt {attempt}/{max_regenerations}")

        if attempt >= max_regenerations:
            # Max retries hit — save as draft
            logger.warning("Max regenerations reached — saving as draft")
            await bot.send_notification(
                config.telegram_bot_token,
                config.telegram_chat_id,
                "Max regenerations reached. Saving as <b>WordPress draft</b> for manual review.",
            )
            return ApprovalResult(
                approved=False,
                article=article,
                seo_meta=seo_meta,
                save_as_draft=True,
            )

        await bot.edit_message_text(
            config.telegram_bot_token,
            config.telegram_chat_id,
            approval_msg_id,
            f"Rejected — regenerating article (attempt {attempt + 1}/{max_regenerations})…",
        )

        # Regenerate: re-run humanize pass on the same draft
        from ..writer.humanizer import humanize_article

        new_article = await humanize_article(article, config)

        # Recurse with incremented attempt counter
        return await run_article_approval(
            new_article, seo_meta, config, attempt=attempt + 1, max_regenerations=max_regenerations
        )

    # Unknown callback — treat as approval
    logger.warning(f"Unknown callback_data: {result.callback_data} — treating as approve")
    return ApprovalResult(approved=True, article=article, seo_meta=seo_meta)
