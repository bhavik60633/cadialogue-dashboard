"""
JSON-LD schema markup builder.
Generates Article, FAQPage, and BreadcrumbList schemas for WordPress injection.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

from ..utils.logger import get_logger
from .article_generator import SEOMeta

logger = get_logger("schema_builder")

SITE_NAME = "CADialogue"
AUTHOR_NAME = "CADialogue Editorial Team"


def _extract_faq_pairs(article_text: str) -> list[tuple[str, str]]:
    """
    Extracts Q&A pairs from the FAQ section of the article.
    Expects Claude's output pattern:
      ## Frequently Asked Questions
      **Q: Question text?**
      Answer text.
    or numbered list format.
    """
    pairs = []

    # Find FAQ section
    faq_match = re.search(
        r"##\s+Frequently Asked Questions(.*?)(?:##|\Z)",
        article_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not faq_match:
        logger.warning("No FAQ section found in article")
        return pairs

    faq_section = faq_match.group(1)

    # Pattern 1: **Q: ...** \n Answer
    pattern1 = re.findall(
        r"\*\*Q[:.]?\s*(.+?)\*\*\s*\n+([^*\n][^\n]+(?:\n[^*\n#][^\n]+)*)",
        faq_section,
        re.DOTALL,
    )
    if pattern1:
        for q, a in pattern1:
            pairs.append((q.strip(), a.strip()))
        return pairs

    # Pattern 2: numbered — "1. Question?\nAnswer"
    pattern2 = re.findall(
        r"\d+\.\s+(.+?\?)\s*\n+([^0-9\n][^\n]+(?:\n[^0-9\n#][^\n]+)*)",
        faq_section,
    )
    for q, a in pattern2:
        pairs.append((q.strip(), a.strip()))

    return pairs


def build_article_schema(
    article_text: str,
    meta: SEOMeta,
    wp_post_url: str,
    site_url: str,
    image_url: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": meta.title[:110],
        "description": meta.meta_description,
        "author": {
            "@type": "Organization",
            "name": AUTHOR_NAME,
        },
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": site_url,
        },
        "datePublished": now,
        "dateModified": now,
        "url": wp_post_url,
        "wordCount": len(article_text.split()),
        **({"image": {"@type": "ImageObject", "url": image_url}} if image_url else {}),
    }


def build_faq_schema(article_text: str) -> Optional[dict]:
    pairs = _extract_faq_pairs(article_text)
    if not pairs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in pairs
        ],
    }


def build_breadcrumb_schema(
    post_url: str, site_url: str, category: str, post_title: str
) -> dict:
    category_label = category.replace("_", " ").title()
    category_url = f"{site_url}/category/{category.replace('_', '-')}/"
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": site_url},
            {"@type": "ListItem", "position": 2, "name": "Finance", "item": f"{site_url}/finance/"},
            {"@type": "ListItem", "position": 3, "name": category_label, "item": category_url},
            {"@type": "ListItem", "position": 4, "name": post_title, "item": post_url},
        ],
    }


def schemas_to_html(*schemas: dict) -> str:
    """Combine multiple JSON-LD schemas into HTML script tags."""
    parts = []
    for schema in schemas:
        if schema:
            parts.append(
                f'<script type="application/ld+json">\n'
                f'{json.dumps(schema, indent=2, ensure_ascii=False)}\n'
                f'</script>'
            )
    return "\n".join(parts)


def build_all_schemas(
    article_text: str,
    meta: SEOMeta,
    wp_post_url: str = "",
    site_url: str = "",
    category: str = "global_market",
    image_url: Optional[str] = None,
) -> str:
    """Build all schemas and return as combined HTML string."""
    article_schema = build_article_schema(article_text, meta, wp_post_url, site_url, image_url)
    faq_schema = build_faq_schema(article_text)
    breadcrumb_schema = build_breadcrumb_schema(wp_post_url, site_url, category, meta.title)

    schemas = [s for s in [article_schema, faq_schema, breadcrumb_schema] if s]
    logger.info(f"Built {len(schemas)} schema(s): article + {'faq + ' if faq_schema else ''}breadcrumb")
    return schemas_to_html(*schemas)
