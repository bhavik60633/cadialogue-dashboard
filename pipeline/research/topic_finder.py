"""
Topic research engine.
Pulls headlines from NewsAPI, scores them with Claude, returns top 3 topics.
Also fetches Google Trends data to weight topics by search demand.
"""
import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

from ..config import Config
from ..utils.logger import get_logger
from ..utils.retry import with_retry_sync
from .market_data import MarketSnapshot

logger = get_logger("topic_finder")


def _safe_json_parse(raw: str) -> dict:
    """Parse JSON from LLM response - delegates to shared utility."""
    from ..utils.json_utils import safe_json_parse
    # Save raw for debugging
    try:
        from pathlib import Path
        Path(__file__).resolve().parents[2].joinpath(
            "pipeline", "state", "gemini_last_raw.txt"
        ).write_text(raw or "", encoding="utf-8", errors="replace")
    except Exception:
        pass
    return safe_json_parse(raw)


# India + Global finance keyword groups for NewsAPI
INDIA_KEYWORDS = "Sensex OR Nifty OR RBI OR SEBI OR NSE OR BSE OR rupee OR \"Indian market\""
GLOBAL_KEYWORDS = "\"Federal Reserve\" OR \"S&P 500\" OR Bitcoin OR \"interest rate\" OR inflation OR \"stock market\""

CATEGORY_MAP = {
    # ── Original 5 ───────────────────────────────────────────────────────────
    "india_market":        "Markets",
    "global_market":       "Markets",
    "crypto":              "Crypto",
    "regulation":          "Banking",
    "personal_finance":    "Personal Finance",
    # ── Expanded 9 ──────────────────────────────────────────────────────────
    "economy":             "Economy",
    "banking":             "Banking",
    "mutual_funds":        "Mutual Funds",
    "tax_gst":             "Tax & GST",
    "real_estate":         "Real Estate",
    "startups":            "Startups",
    # ── New 3 for dashboard library ──────────────────────────────────────────
    "chartered_accountant": "Chartered Accountant",
    "current_affairs":      "Current Affairs",
    "marketing":            "Marketing",
    "ai_technology":        "AI & Technology",
}

CATEGORY_DISPLAY = {k: v for k, v in CATEGORY_MAP.items()}


@dataclass
class ScoredTopic:
    title: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    score: float = 0.0
    category: str = "global_market"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "keywords": self.keywords,
            "sources": self.sources,
            "score": self.score,
            "category": self.category,
        }


@with_retry_sync(max_attempts=2, delay_seconds=2, backoff=1.5)
def _fetch_newsapi(api_key: str, query: str, page_size: int = 10) -> list[dict]:
    """Fetch articles from NewsAPI matching the query."""
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "apiKey": api_key,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("articles", [])


def _fetch_google_trends(keywords: list[str]) -> dict[str, int]:
    """
    Fetch Google Trends interest scores for keywords.
    Returns {keyword: score} where score is 0-100.
    Falls back to empty dict if pytrends is unavailable or rate-limited.
    """
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-IN", tz=330)  # IST timezone
        pytrends.build_payload(keywords[:5], timeframe="now 1-d", geo="IN")
        df = pytrends.interest_over_time()
        if df.empty:
            return {}
        return {kw: int(df[kw].mean()) for kw in keywords[:5] if kw in df.columns}
    except Exception as exc:
        logger.warning(f"Google Trends fetch failed: {exc}")
        return {}


async def _score_topics_with_claude(
    articles: list[dict], market: MarketSnapshot, config: Config
) -> list[ScoredTopic]:
    """Score and filter raw articles into top 3 topics via Gemini/OpenAI."""

    headlines = [
        {
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "source": a.get("source", {}).get("name", ""),
            "url": a.get("url", ""),
            "publishedAt": a.get("publishedAt", ""),
        }
        for a in articles[:25]
        if a.get("title") and "[Removed]" not in a.get("title", "")
    ]

    market_context = (
        f"Sensex: {market.sensex:,.0f} ({market.sensex_change_pct:+.2f}%) | "
        f"Nifty: {market.nifty:,.0f} ({market.nifty_change_pct:+.2f}%) | "
        f"S&P 500: {market.sp500:,.0f} ({market.sp500_change_pct:+.2f}%) | "
        f"BTC: ${market.btc_usd:,.0f} | RBI Repo: {market.rbi_repo_rate}%"
    )

    prompt = f"""You are a finance content strategist for a blog targeting Indian retail investors.

Today's market data: {market_context}

Below are {len(headlines)} recent finance news headlines. Select the TOP 3 topics that would make the best blog articles.

Scoring criteria:
- Recency and timeliness (published < 24 hours ago gets priority)
- High search potential for terms Indian investors would Google
- Explains something complex in a way retail investors need help with
- NOT already a cliché or overdone angle

For each of the top 3, return:
- title: A punchy article headline (not the raw news headline)
- summary: 2-3 sentence research brief for the writer
- keywords: 3-5 SEO keywords (exact phrases people search)
- category: one of [india_market, global_market, crypto, regulation, personal_finance]
- score: 0-100 representing how strong this topic is for the blog
- sources: list of source URLs from the articles

Return ONLY valid JSON in this exact format:
{{
  "topics": [
    {{
      "title": "...",
      "summary": "...",
      "keywords": ["keyword 1", "keyword 2", "keyword 3"],
      "category": "india_market",
      "score": 87.5,
      "sources": ["https://..."]
    }}
  ]
}}

Headlines: {json.dumps(headlines, indent=2)}"""

    client = config.make_ai_client()
    response = client.chat.completions.create(
        model=config.ai_fast_model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    data = _safe_json_parse(raw)
    topics = []
    for t in data.get("topics", [])[:3]:
        topics.append(ScoredTopic(
            title=t["title"],
            summary=t["summary"],
            keywords=t.get("keywords", []),
            sources=t.get("sources", []),
            score=float(t.get("score", 50)),
            category=t.get("category", "global_market"),
        ))

    return sorted(topics, key=lambda x: x.score, reverse=True)


async def find_top_topics(config: Config, market: MarketSnapshot) -> list[ScoredTopic]:
    """
    Main entry point: fetch news, score topics, return top 3.
    If FORCE_TOPIC is set, returns a single synthetic topic.
    """
    if config.force_topic:
        logger.info(f"FORCE_TOPIC set: {config.force_topic}")
        return [ScoredTopic(
            title=config.force_topic,
            summary=f"Forced topic: {config.force_topic}",
            keywords=config.force_topic.lower().split()[:3],
            score=100.0,
            category="global_market",
        )]

    logger.info("Fetching news from NewsAPI…")
    loop = asyncio.get_event_loop()

    india_articles, global_articles = await asyncio.gather(
        loop.run_in_executor(None, _fetch_newsapi, config.newsapi_key, INDIA_KEYWORDS, 12),
        loop.run_in_executor(None, _fetch_newsapi, config.newsapi_key, GLOBAL_KEYWORDS, 12),
    )

    all_articles = india_articles + global_articles
    logger.info(f"Fetched {len(all_articles)} articles total")

    if not all_articles:
        # Fallback to a generic market topic if NewsAPI returns nothing
        logger.warning("NewsAPI returned no articles. Using fallback topic.")
        return [ScoredTopic(
            title="Indian Markets Midweek Wrap: What's Moving Sensex and Nifty Today",
            summary="General market wrap article covering key movers and macro factors.",
            keywords=["sensex today", "nifty 50 analysis", "indian stock market"],
            score=60.0,
            category="india_market",
        )]

    topics = await _score_topics_with_claude(all_articles, market, config)
    logger.info(f"Top topic: {topics[0].title} (score: {topics[0].score})")
    return topics


# ── Batch discovery (dashboard) ───────────────────────────────────────────────


async def _score_topics_batch(
    articles: list[dict], market: MarketSnapshot, config: Config, n: int = 10
) -> list[ScoredTopic]:
    """Return n topics with publisher-level source metadata via Gemini/OpenAI.
    The API call runs in a thread executor so it never blocks uvicorn's event loop.
    """
    headlines = [
        {
            "title":       a.get("title", ""),
            "description": a.get("description", ""),
            "source":      a.get("source", {}).get("name", ""),
            "url":         a.get("url", ""),
            "publishedAt": a.get("publishedAt", ""),
        }
        for a in articles[:40]          # 40 headlines keeps prompt under 3k tokens
        if a.get("title") and "[Removed]" not in a.get("title", "")
    ]

    market_ctx = (
        f"Sensex: {market.sensex:,.0f} ({market.sensex_change_pct:+.2f}%) | "
        f"Nifty: {market.nifty:,.0f} | RBI Repo: {market.rbi_repo_rate}% | "
        f"BTC: ${market.btc_usd:,.0f} | USD/INR: {market.usd_inr:.2f}"
    )

    categories = ", ".join(CATEGORY_MAP.keys())

    prompt = f"""You are a finance content strategist for CADialogue, an Indian finance news blog.
Today's market: {market_ctx}

Below are {len(headlines)} recent headlines. Return the TOP {n} article topics.

For each topic return EXACTLY these fields:
- title: Punchy article headline
- summary: 2-3 sentence brief (keep under 80 words)
- keywords: array of 3-4 strings
- category: one of [{categories}]
- score: integer 0-100
- sources: array of objects with "url" and "publisher" keys

Return ONLY a JSON object with a "topics" array. No markdown, no commentary.

Headlines:
{json.dumps(headlines, indent=2)}"""

    def _call_api() -> str:
        # OpenAI (GPT-4o-mini) — primary, reliable JSON mode
        if config.has_openai:
            client = config.make_ai_client()
            resp = client.chat.completions.create(
                model=config.ai_fast_model,
                max_tokens=6000,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""

        # Gemini native SDK — fallback (never truncates)
        gemini = config.make_gemini_client()
        if gemini:
            from google.genai import types
            resp = gemini.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            return resp.text or ""

        raise RuntimeError("No AI provider available. Set OPENAI_API_KEY or GEMINI_API_KEY in .env")

    # Run in thread pool — never blocks uvicorn's event loop
    loop = asyncio.get_event_loop()
    try:
        raw = await asyncio.wait_for(
            loop.run_in_executor(None, _call_api),
            timeout=90.0
        )
    except asyncio.TimeoutError:
        raise RuntimeError("AI API timed out after 90 seconds")

    data = _safe_json_parse(raw)
    topics = []
    for t in data.get("topics", [])[:n]:
        topics.append(ScoredTopic(
            title=t["title"],
            summary=t["summary"],
            keywords=t.get("keywords", []),
            sources=[s if isinstance(s, str) else s.get("url", "") for s in t.get("sources", [])],
            score=float(t.get("score", 50)),
            category=t.get("category", "global_market"),
        ))
        # Attach rich source data as extra attribute
        topics[-1].__dict__["rich_sources"] = t.get("sources", [])

    return sorted(topics, key=lambda x: x.score, reverse=True)


async def find_topics_batch(
    config: Config, market: MarketSnapshot, n: int = 10
) -> list[ScoredTopic]:
    """
    Batch version of find_top_topics: returns n ranked topics.
    Fetches more articles from NewsAPI to give Claude enough variety.
    """
    if config.force_topic:
        logger.info(f"FORCE_TOPIC: {config.force_topic}")
        return [ScoredTopic(
            title=config.force_topic,
            summary=f"Forced topic: {config.force_topic}",
            keywords=config.force_topic.lower().split()[:3],
            score=100.0,
            category="global_market",
        )]

    logger.info(f"Batch topic discovery: fetching articles for {n} topics…")

    # Skip NewsAPI if key is missing — go straight to fallback
    if not config.newsapi_key:
        logger.warning("NEWSAPI_KEY not set — using built-in fallback topics")
        return _fallback_topics(n)

    loop = asyncio.get_event_loop()

    try:
        india_articles, global_articles, economy_articles = await asyncio.gather(
            loop.run_in_executor(None, _fetch_newsapi, config.newsapi_key, INDIA_KEYWORDS, 20),
            loop.run_in_executor(None, _fetch_newsapi, config.newsapi_key, GLOBAL_KEYWORDS, 20),
            loop.run_in_executor(
                None, _fetch_newsapi, config.newsapi_key,
                "GST OR \"income tax\" OR \"mutual fund\" OR \"real estate\" OR \"startup India\"", 15
            ),
        )
    except Exception as exc:
        logger.warning(f"NewsAPI fetch failed ({exc}) — using fallback topics")
        return _fallback_topics(n)

    all_articles = india_articles + global_articles + economy_articles
    logger.info(f"Fetched {len(all_articles)} articles for batch scoring")

    if not all_articles:
        logger.warning("NewsAPI returned no articles — using fallback topics")
        return _fallback_topics(n)

    try:
        topics = await _score_topics_batch(all_articles, market, config, n=n)
        if not topics:
            raise ValueError("Gemini returned 0 topics")
        logger.info(f"Batch: {len(topics)} topics scored. Best: {topics[0].title}")
        return topics
    except Exception as exc:
        logger.warning(f"AI scoring failed ({exc}) — serving today's NewsAPI headlines as topics")
        return _topics_from_articles(all_articles, n)


def _topics_from_articles(articles: list[dict], n: int = 10) -> list[ScoredTopic]:
    """
    Convert raw NewsAPI articles to ScoredTopics without AI scoring.
    Used as fallback when Gemini is unavailable.
    """
    seen: set[str] = set()
    topics: list[ScoredTopic] = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title or "[Removed]" in title or title in seen:
            continue
        seen.add(title)
        url   = a.get("url", "")
        src   = a.get("source", {}).get("name", "")
        desc  = (a.get("description") or "")[:300]
        # Simple keyword extraction: first 4 words of title
        kws   = [w.lower() for w in title.split()[:4] if len(w) > 3]
        topics.append(ScoredTopic(
            title=title,
            summary=desc or title,
            keywords=kws,
            sources=[url],
            score=60.0,
            category="india_market",
        ))
        topics[-1].__dict__["rich_sources"] = [{"url": url, "publisher": src}]
        if len(topics) >= n:
            break
    return topics


def _fallback_topics(n: int = 10) -> list[ScoredTopic]:
    """Emergency fallback when NewsAPI is unavailable."""
    base = [
        ScoredTopic("Indian Markets Midweek Wrap: Key Movers and Macro Signals", "General market wrap.", ["sensex today", "nifty analysis"], ["https://economictimes.com"], 65.0, "india_market"),
        ScoredTopic("RBI Monetary Policy: What the Latest Decision Means for Borrowers", "RBI rate policy analysis.", ["rbi repo rate", "home loan rates india"], ["https://rbi.org.in"], 70.0, "regulation"),
        ScoredTopic("Gold Prices Today: MCX Rally and What's Driving It", "Gold market analysis.", ["gold price india today", "mcx gold"], ["https://livemint.com"], 72.0, "india_market"),
        ScoredTopic("SIP vs Lump Sum: Which Works Better in Current Market?", "MF investment strategy.", ["sip investment", "mutual fund sip"], ["https://valueresearchonline.com"], 68.0, "mutual_funds"),
        ScoredTopic("US Fed Rate Decision: Impact on Indian Stock Market", "Fed policy India impact.", ["federal reserve rate", "fii flows india"], ["https://bloomberg.com"], 74.0, "global_market"),
        ScoredTopic("Income Tax Filing 2026: New Regime vs Old Regime Explained", "Tax planning guide.", ["itr filing 2026", "new tax regime"], ["https://incometax.gov.in"], 80.0, "tax_gst"),
        ScoredTopic("Bitcoin Surges Past $100K: Is This the Bull Run?", "Crypto market analysis.", ["bitcoin price today", "crypto market india"], ["https://coindesk.com"], 71.0, "crypto"),
        ScoredTopic("Sensex at Record High: Top Sectors Driving the Rally", "Market rally analysis.", ["sensex record high", "bse sensex"], ["https://moneycontrol.com"], 76.0, "india_market"),
        ScoredTopic("SEBI New Regulations: What Retail Investors Must Know", "SEBI regulatory update.", ["sebi regulations 2026", "sebi circular"], ["https://sebi.gov.in"], 69.0, "regulation"),
        ScoredTopic("Home Loan Rates 2026: Best Banks to Refinance Your Mortgage", "Home loan comparison.", ["home loan interest rate 2026", "housing loan refinance"], ["https://bankbazaar.com"], 67.0, "real_estate"),
    ]
    return sorted(base[:n], key=lambda x: x.score, reverse=True)
