"""Post published article to Twitter/X (optional)."""
from ..config import Config
from ..utils.logger import get_logger
from ..writer.article_generator import SEOMeta

logger = get_logger("twitter_poster")


async def post_tweet(post_url: str, seo_meta: SEOMeta, config: Config) -> None:
    if not all([
        config.twitter_api_key,
        config.twitter_api_secret,
        config.twitter_access_token,
        config.twitter_access_secret,
    ]):
        logger.info("Twitter credentials not set — skipping tweet")
        return

    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=config.twitter_api_key,
            consumer_secret=config.twitter_api_secret,
            access_token=config.twitter_access_token,
            access_token_secret=config.twitter_access_secret,
        )

        # Build hashtags from secondary keywords
        hashtags = []
        for kw in (seo_meta.secondary_keywords or [])[:3]:
            tag = "#" + kw.replace(" ", "").replace("-", "")[:20]
            hashtags.append(tag)

        tweet_text = f"{seo_meta.og_title}\n\n{post_url}\n\n{' '.join(hashtags)}"
        # Twitter character limit: 280
        if len(tweet_text) > 280:
            tweet_text = f"{seo_meta.og_title[:200]}\n\n{post_url}"

        client.create_tweet(text=tweet_text)
        logger.info(f"Tweet posted: {tweet_text[:80]}…")
    except ImportError:
        logger.warning("tweepy not installed — skipping Twitter post. Run: pip install tweepy")
    except Exception as exc:
        logger.warning(f"Twitter post failed (non-fatal): {exc}")
