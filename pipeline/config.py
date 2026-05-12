import os
from dataclasses import dataclass
from .utils.logger import get_logger

logger = get_logger("config")


@dataclass
class Config:
    # ── OpenAI (primary) ─────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"           # Full articles, humaniser
    openai_fast_model: str = "gpt-4o-mini" # Topic scoring, SEO meta, image ideas

    # ── Google Gemini (fallback when OpenAI unavailable) ──────────────────
    gemini_api_key: str = ""

    # Legacy aliases so old code references don't break
    @property
    def anthropic_api_key(self) -> str:
        return self.openai_api_key

    @property
    def claude_model(self) -> str:
        return self.openai_model

    # ── Provider detection ────────────────────────────────────────────────

    @property
    def has_openai(self) -> bool:
        """True when a real OpenAI key is present (not the placeholder)."""
        k = self.openai_api_key
        return bool(k and k != "not-used" and k.startswith("sk-"))

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    # ── Model names ───────────────────────────────────────────────────────

    @property
    def ai_model(self) -> str:
        """Full-size model: articles, humaniser."""
        if self.has_openai:
            return os.environ.get("OPENAI_MODEL", "gpt-4o")
        return "models/gemini-2.5-flash"

    @property
    def ai_fast_model(self) -> str:
        """Fast model: topic scoring, SEO meta, image ideas."""
        if self.has_openai:
            return os.environ.get("OPENAI_FAST_MODEL", "gpt-4o-mini")
        return "models/gemini-2.5-flash"

    # ── Client factories ──────────────────────────────────────────────────

    def make_ai_client(self):
        """
        Return an OpenAI-SDK-compatible client.
        Uses OpenAI when key is present; falls back to Gemini OpenAI-compat endpoint.
        """
        from openai import OpenAI
        if self.has_openai:
            return OpenAI(api_key=self.openai_api_key)
        if self.has_gemini:
            return OpenAI(
                api_key=self.gemini_api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
        raise RuntimeError("No AI API key configured. Set OPENAI_API_KEY in .env")

    def make_gemini_client(self):
        """
        Return the native Gemini client (google-genai SDK).
        Only used when OpenAI is NOT available — Gemini native avoids truncation.
        Returns None when OpenAI is the active provider.
        """
        if self.has_openai:
            return None   # OpenAI is active — don't use native Gemini
        if not self.has_gemini:
            return None
        from google import genai
        return genai.Client(api_key=self.gemini_api_key)

    # ── Pexels ────────────────────────────────────────────────────────────
    pexels_api_key: str = ""

    # ── NewsAPI ───────────────────────────────────────────────────────────
    newsapi_key: str = ""

    # ── Telegram ──────────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_channel_id: str = ""

    # ── WordPress ─────────────────────────────────────────────────────────
    wp_url: str = ""
    wp_username: str = ""
    wp_app_password: str = ""
    wp_seo_plugin: str = "rankmath"

    # ── Google Indexing / IndexNow / Twitter ──────────────────────────────
    google_service_account_json: str = ""
    indexnow_key: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_secret: str = ""

    # ── Pipeline behaviour ────────────────────────────────────────────────
    topic_selection_timeout_minutes: int = 30
    article_approval_timeout_minutes: int = 120
    target_word_count_min: int = 1500
    target_word_count_max: int = 2000

    # ── Overrides ─────────────────────────────────────────────────────────
    force_topic: str = ""


def load_config() -> Config:
    """Load config from environment variables."""
    cfg = Config(
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        openai_fast_model=os.environ.get("OPENAI_FAST_MODEL", "gpt-4o-mini"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
        newsapi_key=os.environ.get("NEWSAPI_KEY", ""),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        telegram_channel_id=os.environ.get("TELEGRAM_CHANNEL_ID", ""),
        wp_url=os.environ.get("WP_URL", "").rstrip("/"),
        wp_username=os.environ.get("WP_USERNAME", ""),
        wp_app_password=os.environ.get("WP_APP_PASSWORD", ""),
        wp_seo_plugin=os.environ.get("WP_SEO_PLUGIN", "rankmath").lower(),
        google_service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
        indexnow_key=os.environ.get("INDEXNOW_KEY", ""),
        twitter_api_key=os.environ.get("TWITTER_API_KEY", ""),
        twitter_api_secret=os.environ.get("TWITTER_API_SECRET", ""),
        twitter_access_token=os.environ.get("TWITTER_ACCESS_TOKEN", ""),
        twitter_access_secret=os.environ.get("TWITTER_ACCESS_SECRET", ""),
        topic_selection_timeout_minutes=int(
            os.environ.get("TOPIC_SELECTION_TIMEOUT_MINUTES", "30")
        ),
        article_approval_timeout_minutes=int(
            os.environ.get("ARTICLE_APPROVAL_TIMEOUT_MINUTES", "120")
        ),
        force_topic=os.environ.get("FORCE_TOPIC", ""),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if not cfg.has_openai and not cfg.has_gemini:
        raise EnvironmentError(
            "No AI key found. Set OPENAI_API_KEY=sk-... or GEMINI_API_KEY=... in .env"
        )

    required = {
        "WP_URL":          cfg.wp_url,
        "WP_USERNAME":     cfg.wp_username,
        "WP_APP_PASSWORD": cfg.wp_app_password,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required env vars: {', '.join(missing)}"
        )

    provider = "OpenAI (GPT-4o)" if cfg.has_openai else "Google Gemini"
    logger.info(
        f"Config loaded | AI: {provider} | WordPress: {cfg.wp_url} | SEO: {cfg.wp_seo_plugin}"
    )
