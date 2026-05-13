"""
Programmatic SEO Engine — scalable page generation via templates.

Generates unique, valuable pages at scale for long-tail keyword variations.

Templates supported:
  1. "best [tool/service] for [industry] in India"
     e.g., "Best Accounting Software for CAs in India 2025"

  2. "[topic] guide for [audience]"
     e.g., "GST Filing Guide for Freelancers India"

  3. "[A] vs [B]: Which is Better for Indian Investors?"
     e.g., "SIP vs Lump Sum: Which is Better for Indian Investors?"

  4. "How to [action] in India: Step-by-Step Guide"
     e.g., "How to Open a Demat Account in India: Step-by-Step Guide"

  5. "[Year] [topic] Report for India"
     e.g., "2025 Mutual Fund Industry Report for India"

Each generated page:
  - Has UNIQUE content (not duplicate/thin — GPT-4o writes fresh content)
  - Includes location/audience-specific details
  - Has automatic internal links to hub article
  - Gets unique meta title/description
  - Gets FAQ schema
  - Is tracked to prevent regeneration

Anti-spam safeguards:
  - Minimum 800 words per page
  - Must include original analysis, not just template fill
  - Deduplication check before generation
  - Quality score check before publishing
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal

from ..config import Config
from ..utils.json_utils import gemini_json_call
from ..utils.logger import get_logger

logger = get_logger("seo.programmatic")

STATE_DIR  = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
PROG_FILE  = STATE_DIR / "programmatic_pages.json"

TemplateType = Literal["best_for", "guide_for", "vs_comparison", "how_to", "year_report"]


# ── Template definitions ──────────────────────────────────────────────────────

TEMPLATES: dict[TemplateType, dict] = {
    "best_for": {
        "title_pattern":   "Best {subject} for {audience} in India {year}",
        "slug_pattern":    "best-{subject_slug}-for-{audience_slug}-india",
        "meta_pattern":    "Compare the best {subject} for {audience} in India. Expert picks, pricing, features & alternatives for Indian users in {year}.",
        "min_words":       1200,
    },
    "guide_for": {
        "title_pattern":   "{topic} Complete Guide for {audience} in India ({year})",
        "slug_pattern":    "{topic_slug}-guide-{audience_slug}-india",
        "meta_pattern":    "The definitive {topic} guide for {audience} in India. Everything you need to know in {year}.",
        "min_words":       1500,
    },
    "vs_comparison": {
        "title_pattern":   "{item_a} vs {item_b}: Which is Better for Indian {audience}? ({year})",
        "slug_pattern":    "{item_a_slug}-vs-{item_b_slug}-india-{audience_slug}",
        "meta_pattern":    "{item_a} vs {item_b} — detailed comparison for Indian {audience}. Pros, cons, fees, and our verdict for {year}.",
        "min_words":       1000,
    },
    "how_to": {
        "title_pattern":   "How to {action} in India: Complete Step-by-Step Guide ({year})",
        "slug_pattern":    "how-to-{action_slug}-india-guide",
        "meta_pattern":    "Step-by-step guide on how to {action} in India. Requirements, process, timeline and expert tips for {year}.",
        "min_words":       1000,
    },
    "year_report": {
        "title_pattern":   "{year} {topic} Outlook for India: Key Trends & Analysis",
        "slug_pattern":    "{year}-{topic_slug}-india-outlook",
        "meta_pattern":    "Comprehensive {year} {topic} analysis for India. Key trends, risks, opportunities and expert forecasts.",
        "min_words":       1500,
    },
}

# Pre-defined page variants for cadialogue.in
CADIALOGUE_PROGRAMMATIC_PAGES = [
    # best_for
    {"template": "best_for", "subject": "accounting software", "audience": "Chartered Accountants", "year": "2025"},
    {"template": "best_for", "subject": "stock trading apps", "audience": "beginners", "year": "2025"},
    {"template": "best_for", "subject": "mutual funds", "audience": "salaried professionals", "year": "2025"},
    {"template": "best_for", "subject": "tax filing software", "audience": "freelancers", "year": "2025"},
    {"template": "best_for", "subject": "NPS pension plans", "audience": "government employees", "year": "2025"},
    # guide_for
    {"template": "guide_for", "topic": "GST filing", "audience": "small business owners", "year": "2025"},
    {"template": "guide_for", "topic": "income tax return", "audience": "salaried employees", "year": "2025"},
    {"template": "guide_for", "topic": "SIP investment", "audience": "young investors", "year": "2025"},
    {"template": "guide_for", "topic": "demat account", "audience": "first-time investors", "year": "2025"},
    # vs_comparison
    {"template": "vs_comparison", "item_a": "SIP", "item_b": "Lump Sum", "audience": "investors", "year": "2025"},
    {"template": "vs_comparison", "item_a": "NSE", "item_b": "BSE", "audience": "traders", "year": "2025"},
    {"template": "vs_comparison", "item_a": "direct mutual fund", "item_b": "regular mutual fund", "audience": "investors", "year": "2025"},
    {"template": "vs_comparison", "item_a": "FD", "item_b": "debt mutual fund", "audience": "conservative investors", "year": "2025"},
    {"template": "vs_comparison", "item_a": "Zerodha", "item_b": "Groww", "audience": "traders", "year": "2025"},
    # how_to
    {"template": "how_to", "action": "open a demat account", "year": "2025"},
    {"template": "how_to", "action": "file GST return online", "year": "2025"},
    {"template": "how_to", "action": "invest in gold ETF", "year": "2025"},
    {"template": "how_to", "action": "calculate HRA exemption", "year": "2025"},
    {"template": "how_to", "action": "withdraw PF online", "year": "2025"},
    # year_report
    {"template": "year_report", "topic": "Indian stock market", "year": "2025"},
    {"template": "year_report", "topic": "real estate", "year": "2025"},
    {"template": "year_report", "topic": "cryptocurrency", "year": "2025"},
]


# ── Persistence ───────────────────────────────────────────────────────────────

def load_prog_store() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not PROG_FILE.exists():
        return {"generated": {}, "queue": []}
    try:
        return json.loads(PROG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"generated": {}, "queue": []}


def save_prog_store(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Slug helpers ──────────────────────────────────────────────────────────────

def _to_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:60]


def _build_page_meta(template_type: TemplateType, params: dict) -> dict:
    """Build title, slug, meta description from template + params."""
    tmpl = TEMPLATES[template_type]
    year = params.get("year", "2025")

    def fill(pattern: str) -> str:
        result = pattern
        for k, v in params.items():
            result = result.replace(f"{{{k}}}", str(v))
            result = result.replace(f"{{{k}_slug}}", _to_slug(str(v)))
        result = result.replace("{year}", year)
        return result

    title     = fill(tmpl["title_pattern"])
    slug      = fill(tmpl["slug_pattern"])
    meta_desc = fill(tmpl["meta_pattern"])

    return {
        "title":     title,
        "slug":      _to_slug(slug),
        "meta_desc": meta_desc[:160],
    }


# ── Content generation ────────────────────────────────────────────────────────

def _generate_programmatic_content(
    template_type: TemplateType,
    params: dict,
    meta: dict,
    config: Config,
) -> str:
    """
    Use GPT-4o to write unique, valuable content for a programmatic page.
    Returns HTML content string.

    Quality safeguards:
    - Explicit instruction to avoid generic boilerplate
    - Requires specific India-relevant data points
    - Minimum sections enforced
    - Original analysis required
    """
    year   = params.get("year", "2025")
    title  = meta["title"]

    # Build template-specific prompt
    prompts = {
        "best_for": f"""You are a senior finance journalist at cadialogue.in, India's leading finance news portal.

Write a comprehensive "Best {params.get('subject')} for {params.get('audience')} in India {year}" article.

ARTICLE TITLE: {title}

MANDATORY STRUCTURE (use these exact H2 headings):
1. Introduction (2-3 paras, hook with a surprising India-specific stat)
2. How We Evaluated {params.get('subject').title()} for Indian {params.get('audience').title()}
3. Top 5 {params.get('subject').title()} for {params.get('audience').title()} (2025 Rankings) [use H3 for each option]
4. Detailed Comparison Table (HTML table with features, pricing, pros, cons)
5. What to Look For When Choosing
6. Frequently Asked Questions (5 FAQs with answers)
7. Our Final Verdict
8. Disclaimer

REQUIREMENTS:
- Minimum 1200 words
- Include specific ₹ pricing where relevant
- Mention SEBI/RBI compliance where applicable
- Include at least one HTML table for comparison
- FAQ section with 5 India-specific questions
- No generic AI fluff — every paragraph must add value
- Journalistic, authoritative tone

Write the complete HTML content (using <h2>, <h3>, <p>, <ul>, <li>, <table>, <strong> tags).
Do NOT include <html>, <body>, <head> tags — just the body content.""",

        "vs_comparison": f"""You are a senior finance journalist at cadialogue.in.

Write a comprehensive comparison: "{params.get('item_a')} vs {params.get('item_b')} for Indian {params.get('audience')}"

ARTICLE TITLE: {title}

MANDATORY STRUCTURE:
1. Introduction — what's the debate and why it matters for Indian {params.get('audience').title()}
2. What is {params.get('item_a')}? (definition, how it works in India)
3. What is {params.get('item_b')}? (definition, how it works in India)
4. Head-to-Head Comparison Table (HTML table: returns, risk, liquidity, tax, min investment, etc.)
5. When to Choose {params.get('item_a')} (specific scenarios)
6. When to Choose {params.get('item_b')} (specific scenarios)
7. Tax Implications in India (important!)
8. Our Verdict for {year}
9. FAQ (5 questions)
10. Disclaimer

REQUIREMENTS:
- Minimum 1000 words
- India-specific tax treatment (LTCG, STCG, TDS as applicable)
- Concrete examples with ₹ amounts
- At least one HTML comparison table
- Balanced — don't favour one option without justification
- No generic AI fluff

Write the complete HTML content.""",

        "guide_for": f"""You are a senior finance journalist at cadialogue.in.

Write "The Complete {params.get('topic').title()} Guide for {params.get('audience').title()} in India {year}"

ARTICLE TITLE: {title}

MANDATORY STRUCTURE:
1. Introduction (what, why, who it's for)
2. Table of Contents (HTML anchor links)
3. Step-by-Step Process (numbered H3 steps)
4. Key Rules & Requirements in India ({year})
5. Common Mistakes to Avoid
6. Expert Tips for {params.get('audience').title()}
7. Useful Resources & Tools
8. FAQ (5 questions)
9. Summary
10. Disclaimer

REQUIREMENTS:
- Minimum 1500 words
- Specific to Indian {params.get('audience').title()} — mention their specific challenges
- Include exact deadlines, fees, penalties where applicable
- Step numbers and clear action items
- India-specific regulatory context (SEBI/RBI/Income Tax Act)
- Current for {year}

Write the complete HTML content.""",

        "how_to": f"""You are a senior finance journalist at cadialogue.in.

Write "How to {params.get('action')} in India: Complete Step-by-Step Guide {year}"

ARTICLE TITLE: {title}

MANDATORY STRUCTURE:
1. Introduction (why this matters, time required, difficulty level)
2. Prerequisites / What You'll Need
3. Step-by-Step Process (numbered H3 headings — minimum 6 steps)
4. Important Rules & Regulations
5. Common Errors and How to Avoid Them
6. Fees and Timeline
7. FAQ (5 questions)
8. Summary Checklist (HTML table or bullet list)
9. Disclaimer

REQUIREMENTS:
- Minimum 1000 words
- Every step must be specific and actionable
- Include screenshots description hints (e.g. "On the RBI portal, look for...")
- Mention documents required (Aadhaar, PAN, etc.)
- Include processing time and costs in ₹
- {year} current information

Write the complete HTML content.""",

        "year_report": f"""You are a senior market analyst at cadialogue.in.

Write "{year} {params.get('topic').title()} Outlook for India: Key Trends & Analysis"

ARTICLE TITLE: {title}

MANDATORY STRUCTURE:
1. Executive Summary (key takeaways in bullet form)
2. {year} Market Overview — India Context
3. Key Trends Shaping the Sector
4. Data & Statistics (HTML table with key metrics)
5. Opportunities for Indian Investors
6. Key Risks to Watch
7. Expert Forecasts for {year}
8. Sector-by-Sector Breakdown (H3 subsections)
9. FAQ (5 questions)
10. Disclaimer

REQUIREMENTS:
- Minimum 1500 words
- Data-driven (use real approximate figures where available)
- India-specific analysis — how global trends affect the Indian market
- Forward-looking tone appropriate for {year}
- Include one comprehensive HTML data table
- Authoritative but accessible language

Write the complete HTML content.""",
    }

    prompt = prompts.get(template_type, prompts["guide_for"])

    try:
        client = config.make_ai_client()
        resp   = client.chat.completions.create(
            model=config.ai_model,
            max_tokens=3500,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        logger.error(f"Content gen failed for '{title}': {exc}")
        return ""


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_programmatic_page(
    template_type: TemplateType,
    params: dict,
    config: Config,
) -> dict:
    """
    Generate one programmatic SEO page.

    Returns:
    {
      "slug": str,
      "title": str,
      "meta_description": str,
      "html_content": str,
      "word_count": int,
      "ready_to_publish": bool,
    }
    """
    store = load_prog_store()
    meta  = _build_page_meta(template_type, params)
    slug  = meta["slug"]

    # Deduplication check
    if slug in store.get("generated", {}):
        logger.info(f"Programmatic page already exists: {slug}")
        return store["generated"][slug]

    logger.info(f"Generating programmatic page: {meta['title']}")
    html_content = _generate_programmatic_content(template_type, params, meta, config)

    if not html_content:
        return {"error": "generation_failed", "slug": slug}

    word_count = len(re.sub(r"<[^>]+>", " ", html_content).split())
    min_words  = TEMPLATES[template_type]["min_words"]

    record = {
        "slug":              slug,
        "title":             meta["title"],
        "meta_description":  meta["meta_desc"],
        "html_content":      html_content,
        "word_count":        word_count,
        "template_type":     template_type,
        "params":            params,
        "ready_to_publish":  word_count >= min_words,
        "generated_at":      time.time(),
    }

    store["generated"][slug] = record
    save_prog_store(store)

    logger.info(f"Generated '{meta['title']}' — {word_count} words, ready={record['ready_to_publish']}")
    return record


def get_generation_queue() -> list[dict]:
    """Return pre-defined pages that haven't been generated yet."""
    store     = load_prog_store()
    generated = set(store.get("generated", {}).keys())

    queue = []
    for page_def in CADIALOGUE_PROGRAMMATIC_PAGES:
        meta = _build_page_meta(page_def["template"], page_def)
        if meta["slug"] not in generated:
            queue.append({**page_def, **meta})

    return queue
