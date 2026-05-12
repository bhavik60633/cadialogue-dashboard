"""
Telegram Bot — all low-level API interactions.
Uses long-polling (getUpdates) — NOT webhooks.
GitHub Actions runners have no public URL, so webhooks are impossible.

Key design: offset tracking prevents re-processing the same updates.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from ..utils.logger import get_logger

logger = get_logger("telegram_bot")

BASE_URL = "https://api.telegram.org/bot{token}"


@dataclass
class CallbackResult:
    callback_data: str
    from_user_id: int
    message_id: int


async def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: Optional[dict] = None,
    parse_mode: str = "HTML",
) -> int:
    """Send a message and return the message_id."""
    url = f"{BASE_URL.format(token=bot_token)}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram sendMessage failed: {data}")
            return data["result"]["message_id"]


async def send_notification(bot_token: str, chat_id: str, text: str) -> None:
    """Send a plain text notification (no buttons)."""
    await send_message(bot_token, chat_id, text)


async def edit_message_text(
    bot_token: str, chat_id: str, message_id: int, text: str
) -> None:
    """Edit an existing message (e.g., to show selection was made)."""
    url = f"{BASE_URL.format(token=bot_token)}/editMessageText"
    async with aiohttp.ClientSession() as session:
        await session.post(url, json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=aiohttp.ClientTimeout(total=10))


async def answer_callback_query(
    session: aiohttp.ClientSession, bot_token: str, callback_query_id: str
) -> None:
    """Acknowledge a button tap — MUST call within 3 seconds to clear spinner."""
    url = f"{BASE_URL.format(token=bot_token)}/answerCallbackQuery"
    await session.post(
        url,
        json={"callback_query_id": callback_query_id},
        timeout=aiohttp.ClientTimeout(total=5),
    )


async def send_topic_selection(
    bot_token: str,
    chat_id: str,
    topics: list,   # list[ScoredTopic]
    auto_select_minutes: int = 30,
) -> int:
    """
    Send the 3 topic options with inline keyboard buttons.
    Returns message_id to use as filter in poll_for_callback.
    """
    lines = [
        f"<b>Finance Pipeline — Topic Selection</b>",
        f"",
        f"Pick today's article topic, or I'll auto-select #1 in {auto_select_minutes} minutes:",
        f"",
    ]
    for i, topic in enumerate(topics[:3], 1):
        lines.append(f"<b>{i}. {topic.title}</b>")
        lines.append(f"   Score: {topic.score:.0f} | {topic.category.replace('_', ' ').title()}")
        lines.append(f"")

    text = "\n".join(lines)

    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"Option {i+1}", "callback_data": str(i)}
                for i in range(min(len(topics), 3))
            ]
        ]
    }

    msg_id = await send_message(bot_token, chat_id, text, reply_markup=keyboard)
    logger.info(f"Topic selection message sent (msg_id={msg_id})")
    return msg_id


async def send_article_for_approval(
    bot_token: str,
    chat_id: str,
    article: str,
    seo_meta,   # SEOMeta
    word_count: int,
    auto_publish_minutes: int = 120,
) -> int:
    """
    Send article preview + approval buttons.
    Returns the approval message_id.
    """
    # Message 1: article preview
    reading_time = max(1, word_count // 200)
    preview = article[:900].replace("<", "&lt;").replace(">", "&gt;")
    if len(article) > 900:
        preview += "…"

    preview_text = (
        f"<b>Article Draft Ready</b>\n\n"
        f"<b>Title:</b> {seo_meta.title}\n"
        f"<b>Words:</b> {word_count} | <b>Read time:</b> ~{reading_time} min\n"
        f"<b>Focus keyword:</b> {seo_meta.focus_keyword}\n\n"
        f"<b>PREVIEW:</b>\n{preview}\n\n"
        f"<b>Meta description:</b>\n<i>{seo_meta.meta_description}</i>"
    )
    await send_message(bot_token, chat_id, preview_text)

    # Message 2: approval buttons
    approval_text = (
        f"Approve this article for publishing?\n"
        f"(Auto-saves as draft if no response in {auto_publish_minutes // 60}h)"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "APPROVE", "callback_data": "approve"},
            {"text": "REJECT - Regenerate", "callback_data": "reject"},
        ]]
    }
    approval_msg_id = await send_message(bot_token, chat_id, approval_text, reply_markup=keyboard)
    logger.info(f"Article approval message sent (msg_id={approval_msg_id})")
    return approval_msg_id


async def poll_for_callback(
    bot_token: str,
    timeout_seconds: int,
    valid_message_id: int,
) -> Optional[CallbackResult]:
    """
    Long-poll Telegram getUpdates waiting for a callback_query on valid_message_id.
    Returns CallbackResult or None if timeout expires.

    offset tracking: advances past processed updates to prevent re-processing.
    """
    start = time.monotonic()
    offset = 0

    async with aiohttp.ClientSession() as session:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                logger.info(f"Polling timeout after {elapsed:.0f}s")
                return None

            remaining = timeout_seconds - elapsed
            poll_wait = min(30, int(remaining))   # Poll at most 30s at a time

            try:
                url = f"{BASE_URL.format(token=bot_token)}/getUpdates"
                params = {
                    "offset": offset,
                    "timeout": poll_wait,
                    "allowed_updates": ["callback_query"],
                }
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=poll_wait + 10),
                ) as resp:
                    data = await resp.json()

                for update in data.get("result", []):
                    offset = update["update_id"] + 1   # Advance past this update

                    cb = update.get("callback_query")
                    if not cb:
                        continue

                    msg_id = cb["message"]["message_id"]
                    if msg_id != valid_message_id:
                        continue

                    # Acknowledge immediately (clears the loading spinner)
                    await answer_callback_query(session, bot_token, cb["id"])

                    result = CallbackResult(
                        callback_data=cb["data"],
                        from_user_id=cb["from"]["id"],
                        message_id=msg_id,
                    )
                    logger.info(f"Received callback: {cb['data']} from user {cb['from']['id']}")
                    return result

            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.warning(f"Polling error: {exc} — retrying in 5s")
                await asyncio.sleep(5)
