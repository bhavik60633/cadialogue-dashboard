"""Post published article to a Telegram channel."""
from ..approval.telegram_bot import send_message
from ..config import Config
from ..utils.logger import get_logger
from ..writer.article_generator import SEOMeta

logger = get_logger("telegram_channel")


async def post_to_channel(post_url: str, seo_meta: SEOMeta, config: Config) -> None:
    if not config.telegram_channel_id:
        return

    text = (
        f"<b>{seo_meta.og_title}</b>\n\n"
        f"{seo_meta.og_description}\n\n"
        f"<a href='{post_url}'>Read the full article →</a>"
    )

    try:
        await send_message(config.telegram_bot_token, config.telegram_channel_id, text)
        logger.info(f"Posted to Telegram channel: {config.telegram_channel_id}")
    except Exception as exc:
        logger.warning(f"Telegram channel post failed (non-fatal): {exc}")
