"""
Article generation — Claude API, Pass 1: raw expert draft.
Uses prompt caching on the large system prompt to reduce cost.
"""
import json
from dataclasses import dataclass
from typing import Optional

from ..config import Config
from ..research.fact_checker import VerifiedFact
from ..research.market_data import MarketSnapshot
from ..research.topic_finder import ScoredTopic
from ..utils.logger import get_logger

logger = get_logger("article_generator")

# ── Cached system prompt (~500 words — this gets cached after first call) ──────
JOURNALIST_SYSTEM_PROMPT = """You are a senior finance journalist with 15 years of experience writing for Economic Times, Mint, and Bloomberg Quint. You have deep expertise in Indian capital markets, RBI monetary policy, SEBI regulations, global macro economics, and personal finance for Indian investors.

Your writing style:
- Direct and authoritative — state facts confidently, not tentatively
- Active voice, present tense for live data ("Sensex trades at..." not "Sensex is trading at...")
- Varied sentence rhythm — mix short punchy sentences with longer analytical ones
- Never use filler phrases: "In today's fast-paced world", "It's important to note", "Needless to say", "In conclusion", "Delving into", "Navigating the landscape", "It goes without saying"
- Always explain global events in terms of India impact (e.g., Fed rate hikes → FII outflows → rupee pressure)
- Use ₹ for Indian currency, $ for USD
- Include one or two rhetorical questions to engage readers
- Cite specific numbers — never round excessively (write 75,432 not "around 75,000")
- End sections with a clear takeaway, not a summary

Article structure you always follow:
1. Hook opening — 2-3 sentences that grab attention with the most surprising fact
2. Context — what led to this situation (2-3 paragraphs)
3. What's happening now — the core news with specific data (2-3 paragraphs)
4. Why it matters for Indian investors — practical implications (2 paragraphs)
5. What to watch next — forward-looking signals (1 paragraph)
6. FAQ — 5 questions retail investors actually ask, with clear answers

Legal disclaimer always at the end:
"Disclaimer: This article is for informational purposes only and does not constitute investment advice. Please consult a SEBI-registered financial advisor before making investment decisions."
"""


@dataclass
class SEOMeta:
    title: str
    meta_description: str
    focus_keyword: str
    secondary_keywords: list[str]
    slug: str
    og_title: str
    og_description: str


def _format_market_data(market: MarketSnapshot) -> str:
    return (
        f"LIVE MARKET DATA (as of {market.timestamp[:10]}):\n"
        f"- Sensex: {market.sensex:,.2f} ({market.sensex_change_pct:+.2f}% today)\n"
        f"- Nifty 50: {market.nifty:,.2f} ({market.nifty_change_pct:+.2f}% today)\n"
        f"- S&P 500: {market.sp500:,.2f} ({market.sp500_change_pct:+.2f}% today)\n"
        f"- NASDAQ: {market.nasdaq:,.2f} ({market.nasdaq_change_pct:+.2f}% today)\n"
        f"- Bitcoin: ${market.btc_usd:,.2f} (₹{market.btc_inr:,.2f})\n"
        f"- Ethereum: ${market.eth_usd:,.2f}\n"
        f"- USD/INR: ₹{market.usd_inr:.2f}\n"
        f"- RBI Repo Rate: {market.rbi_repo_rate}%"
    )


def _format_verified_facts(facts: list[VerifiedFact]) -> str:
    lines = []
    for f in facts:
        if f.verified:
            line = f"✓ {f.claim} [source: {f.source}]"
            if f.note:
                line += f" — {f.note}"
            lines.append(line)
    return "\n".join(lines) if lines else "No pre-verified facts available."


async def generate_draft(
    topic: ScoredTopic,
    market: MarketSnapshot,
    facts: list[VerifiedFact],
    config: Config,
) -> str:
    """Generate the first-pass article draft using Claude with prompt caching."""
    logger.info(f"Generating draft for: {topic.title}")

    client = config.make_ai_client()

    user_prompt = f"""Write a comprehensive finance article on the following topic.

TOPIC: {topic.title}

RESEARCH BRIEF:
{topic.summary}

{_format_market_data(market)}

VERIFIED FACTS (use these numbers — they are confirmed accurate):
{_format_verified_facts(facts)}

TARGET KEYWORDS (include naturally in headings and body):
Primary: {topic.keywords[0] if topic.keywords else topic.title}
Secondary: {', '.join(topic.keywords[1:]) if len(topic.keywords) > 1 else 'N/A'}

REQUIREMENTS:
- Word count: {config.target_word_count_min}–{config.target_word_count_max} words
- Include 4–6 H2 section headings
- Include H3 sub-headings where appropriate
- Include a 5-question FAQ section (use H2 for "Frequently Asked Questions")
- Write for Indian retail investors as the primary audience
- Explain global events in terms of India-specific impact
- Include the legal disclaimer at the very end

OUTPUT FORMAT: Plain markdown with # for H1, ## for H2, ### for H3, **bold** for emphasis."""

    response = client.chat.completions.create(
        model=config.ai_model,
        max_tokens=5000,
        messages=[
            {"role": "system", "content": JOURNALIST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    draft = response.choices[0].message.content.strip()
    word_count = len(draft.split())
    logger.info(f"Draft generated: {word_count} words")
    return draft


async def generate_seo_meta(
    article: str, topic: ScoredTopic, config: Config
) -> SEOMeta:
    """Generate SEO metadata. Always returns a valid SEOMeta — never raises."""
    import asyncio
    import re as _re
    logger.info("Generating SEO meta…")

    def _make_slug(text: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]

    def _build_default() -> SEOMeta:
        """Fallback when AI call fails — generate from topic title."""
        title = topic.title[:60]
        return SEOMeta(
            title=title,
            meta_description=f"{topic.title}. Expert analysis and latest updates on CADialogue.",
            focus_keyword=(topic.keywords[0] if topic.keywords else topic.title[:40]),
            secondary_keywords=topic.keywords[1:5],
            slug=_make_slug(topic.title),
            og_title=title,
            og_description=f"{topic.title}. Read the full analysis on CADialogue.",
        )

    excerpt = article[:500].replace("\n", " ")
    prompt = f"""Generate SEO metadata for this finance article. Return ONLY a JSON object with these EXACT keys:

{{
  "title": "SEO title under 60 chars",
  "meta_description": "Description 145-155 chars with keyword",
  "focus_keyword": "2-4 word keyword phrase",
  "secondary_keywords": ["kw2", "kw3", "kw4"],
  "slug": "url-slug-with-hyphens",
  "og_title": "Social title under 70 chars",
  "og_description": "Social description under 200 chars"
}}

Topic: {topic.title}
Primary keyword: {topic.keywords[0] if topic.keywords else topic.title[:40]}
Excerpt: {excerpt}"""

    # Run blocking API call in thread pool — never block uvicorn's event loop
    def _call_sync() -> dict:
        from ..utils.json_utils import gemini_json_call
        try:
            return gemini_json_call(config, prompt, max_tokens=800)
        except Exception as e:
            logger.warning(f"SEO meta API call failed ({e}) — using defaults")
            return {}

    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _call_sync),
            timeout=30.0
        )
    except Exception as e:
        logger.warning(f"SEO meta generation failed ({e}) — using defaults")
        data = {}

    if not isinstance(data, dict):
        data = {}

    def _get(data: dict, *keys: str, default: str = "") -> str:
        for k in keys:
            v = data.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return default

    try:
        return SEOMeta(
            title       = _get(data, "title", "seo_title", "headline",
                               default=topic.title[:60]),
            meta_description = _get(data, "meta_description", "description",
                                    "metaDescription", "meta_desc",
                                    default=f"{topic.title}. Expert analysis on CADialogue."),
            focus_keyword    = _get(data, "focus_keyword", "focusKeyword",
                                    "keyword", "primary_keyword",
                                    default=(topic.keywords[0] if topic.keywords else topic.title[:40])),
            secondary_keywords = list(
                data.get("secondary_keywords") or
                data.get("keywords") or
                topic.keywords[1:5] or []
            ),
            slug        = _get(data, "slug", "url_slug",
                               default=_make_slug(topic.title)),
            og_title    = _get(data, "og_title", "ogTitle",
                               default=topic.title[:70]),
            og_description = _get(data, "og_description", "ogDescription",
                                  default=f"{topic.title}. Read on CADialogue."),
        )
    except Exception as e:
        logger.warning(f"SEO meta build failed ({e}) — returning defaults")
        return _build_default()
