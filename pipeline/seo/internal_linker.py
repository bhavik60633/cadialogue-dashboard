"""
Internal Linking Engine — the most critical SEO component.

For every newly published article:
  1.  Embed the new article.
  2.  Find the 20 most semantically similar existing articles.
  3.  For each similar article, GPT-4o-mini generates natural anchor text
      options that EXIST verbatim in the new article HTML.
  4.  Inject those anchor text phrases as <a href="..."> links.
  5.  Target: 30+ outgoing internal links per article.
  6.  Update 5-8 existing articles to add a backlink to the new one.
  7.  Persist a full bidirectional link graph.

Why 30+ links per article matters:
  - Distributes PageRank throughout the site
  - Strengthens topical clusters (hub ↔ spoke)
  - Reduces crawl depth for every linked page
  - Signals topical authority to Google
  - Keeps users on-site longer (UX signal)

Anchor text strategy:
  - Never copy exact page title (exact-match spam)
  - Use partial phrases, LSI variants, natural journalism style
  - Vary across the article (no duplicate anchors)
  - 2-6 words per anchor
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import Config
from ..utils.json_utils import gemini_json_call
from ..utils.logger import get_logger
from .embeddings_store import (
    embed_text,
    get_similar_articles,
    load_embeddings,
)

logger = get_logger("seo.internal_linker")

STATE_DIR      = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
LINK_GRAPH_FILE = STATE_DIR / "link_graph.json"

# ── Tuning constants ─────────────────────────────────────────────────────────
MIN_SIMILARITY       = 0.40   # Minimum cosine sim to qualify as a link candidate
TARGET_OUTGOING      = 30     # Target outgoing links per new article
MAX_BACKLINK_UPDATES = 7      # Max existing articles to update with a backlink
MAX_LINKS_PER_PARA   = 2      # Never put >2 links in one paragraph
ANCHOR_VARIANTS      = 4      # Anchor text options to generate per target


# ── Link graph persistence ────────────────────────────────────────────────────

def load_link_graph() -> dict:
    """
    Load the sitewide link graph.

    Schema:
    {
      "outgoing":  { "post_id": [target_id, ...] },
      "incoming":  { "post_id": [source_id, ...] },
      "pair_meta": { "src-dst": { "anchors": [...], "injected_at": float } },
      "stats":     { "total_links": int, "last_rebuilt": float }
    }
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not LINK_GRAPH_FILE.exists():
        return {"outgoing": {}, "incoming": {}, "pair_meta": {}, "stats": {}}
    try:
        return json.loads(LINK_GRAPH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"outgoing": {}, "incoming": {}, "pair_meta": {}, "stats": {}}


def save_link_graph(graph: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LINK_GRAPH_FILE.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _update_graph(graph: dict, src_id: int, dst_id: int, anchors: list[str]) -> None:
    """Register src→dst link in the graph (idempotent)."""
    s, d = str(src_id), str(dst_id)
    out = graph["outgoing"].setdefault(s, [])
    if d not in out:
        out.append(d)
    inc = graph["incoming"].setdefault(d, [])
    if s not in inc:
        inc.append(s)
    graph["pair_meta"][f"{s}-{d}"] = {
        "anchors":     anchors,
        "injected_at": time.time(),
    }


# ── Anchor text generation ────────────────────────────────────────────────────

def _generate_anchors_for_pair(
    src_title: str,
    dst_title: str,
    dst_excerpt: str,
    config: Config,
) -> list[str]:
    """
    GPT-4o-mini generates ANCHOR_VARIANTS natural anchor phrases
    for linking from source to destination.

    These are journalistic phrases — partial match, contextual, varied.
    They do NOT have to appear in the article yet; that comes next.
    """
    prompt = f"""You are an SEO editor at an Indian finance news site (cadialogue.in).

SOURCE ARTICLE: "{src_title}"
TARGET ARTICLE: "{dst_title}"
TARGET SUMMARY: {dst_excerpt[:200]}

Generate {ANCHOR_VARIANTS} SHORT anchor text phrases (2-6 words each) that would naturally
link from a finance article to the target article.

Rules:
  - Do NOT copy the exact target title
  - Use partial phrases, LSI keywords, contextual finance language
  - Natural journalism style — reads as editorial, not SEO
  - Each phrase must be DIFFERENT
  - Specific to Indian finance readers (use ₹, RBI, SEBI, NSE, BSE if relevant)
  - No "click here", "read more", "this article", "learn more"

Return ONLY JSON: {{"anchors": ["phrase1", "phrase2", "phrase3", "phrase4"]}}"""

    try:
        result = gemini_json_call(config, prompt, max_tokens=200)
        raw = result.get("anchors", [])
        return [str(a).strip() for a in raw if a and 2 < len(str(a)) < 80][:ANCHOR_VARIANTS]
    except Exception as exc:
        logger.warning(f"Anchor gen failed for '{dst_title[:40]}': {exc}")
        # Graceful fallback: take first 4 words of destination title
        words = dst_title.split()
        return [" ".join(words[:4]), " ".join(words[:5])]


def _find_verbatim_phrases(
    article_html: str,
    dst_title: str,
    dst_excerpt: str,
    config: Config,
) -> list[str]:
    """
    Ask GPT-4o-mini to identify SHORT PHRASES that ALREADY EXIST verbatim in
    the article text AND are relevant to the destination article.
    These become anchor texts we can find with a simple regex.
    """
    # Plain text for the LLM (strip HTML to save tokens)
    text = re.sub(r"<[^>]+>", " ", article_html)
    text = re.sub(r"\s+", " ", text).strip()[:4000]

    prompt = f"""You are an SEO editor. Given this ARTICLE TEXT and a TARGET TOPIC,
find 3-5 short phrases (2-6 words) that:
  1. Appear VERBATIM in the article text
  2. Are relevant to the target topic
  3. Would make natural anchor text for a contextual link

ARTICLE TEXT (partial):
{text}

TARGET TOPIC: "{dst_title}"
TARGET ABOUT: {dst_excerpt[:150]}

Rules:
  - Phrases must be copied EXACTLY from the article text (case-insensitive)
  - 2-6 words each
  - If no good match, return empty list — do NOT invent phrases
  - Avoid phrases already inside an <a> tag
  - Prefer phrases in body sentences, not headings

Return ONLY JSON: {{"phrases": ["exact phrase", ...]}}"""

    try:
        result = gemini_json_call(config, prompt, max_tokens=200)
        raw = result.get("phrases", [])
        return [str(p).strip() for p in raw if p and 2 < len(str(p)) < 80]
    except Exception as exc:
        logger.warning(f"Phrase find failed for '{dst_title[:40]}': {exc}")
        return []


# ── Link injection into HTML ──────────────────────────────────────────────────

def _inject_links(
    html: str,
    opportunities: list[dict],
    max_links: int = TARGET_OUTGOING,
) -> tuple[str, int]:
    """
    Inject <a href="..."> links into the article HTML.

    Strategy:
      - Only inject inside <p>...</p> blocks (never in headings)
      - Count existing links in each paragraph; skip if at limit
      - Match anchor phrase case-insensitively; preserve original casing
      - Never link the same URL twice
      - Skip if phrase already inside an <a> tag

    Returns (modified_html, count_injected)
    """
    injected   = 0
    used_urls  : set[str] = set()
    result_html = html

    # Pre-collect URLs already in the HTML to avoid duplicates
    already = set(re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE))
    used_urls.update(already)

    for opp in opportunities:
        if injected >= max_links:
            break

        url    = opp.get("url", "")
        title  = opp.get("title", "")
        phrases = opp.get("phrases", [])

        if not url or not phrases or url in used_urls:
            continue

        for phrase in phrases:
            if injected >= max_links:
                break
            if not phrase:
                continue

            # Build a case-insensitive regex that matches the phrase ONLY
            # inside a <p> tag and NOT already inside an <a> tag.
            # We use a negative lookbehind for <a  to avoid double-wrapping.
            esc = re.escape(phrase)
            pattern = re.compile(
                r"(?<!</?a[^>]*>)(?<!['\"])(" + esc + r")(?!['\"])",
                re.IGNORECASE,
            )

            # Find first match inside a <p> block
            p_pattern = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)

            new_html_parts: list[str] = []
            pos = 0
            link_placed = False

            for p_match in p_pattern.finditer(result_html):
                p_start, p_end  = p_match.span()
                p_inner          = p_match.group(1)

                new_html_parts.append(result_html[pos:p_start])

                if (
                    not link_placed
                    and url not in used_urls
                    and p_inner.lower().count(phrase.lower()) > 0
                    # Don't inject if paragraph already links this URL
                    and url not in p_inner
                    # Respect per-paragraph link density
                    and p_inner.count("<a ") < MAX_LINKS_PER_PARA
                ):
                    # Replace FIRST occurrence only in this paragraph
                    new_inner, n = pattern.subn(
                        f'<a href="{url}" title="{title}">\\1</a>',
                        p_inner,
                        count=1,
                    )
                    if n > 0:
                        new_html_parts.append(
                            result_html[p_start : p_match.start(1)] + new_inner
                            if False  # keep full tag
                            else f"<p>{new_inner}</p>"
                        )
                        used_urls.add(url)
                        injected += 1
                        link_placed = True
                        logger.debug(f"Injected '{phrase}' → {url}")
                    else:
                        new_html_parts.append(p_match.group(0))
                else:
                    new_html_parts.append(p_match.group(0))

                pos = p_end

            if link_placed:
                new_html_parts.append(result_html[pos:])
                result_html = "".join(new_html_parts)
                break  # one URL per opp block; move to next

    return result_html, injected


# ── Related articles section ──────────────────────────────────────────────────

def _build_related_section(similar: list[dict], max_items: int = 5) -> str:
    """
    Build an HTML "Related Articles" block to append to the end of an article.
    This gives guaranteed outgoing links even when phrase injection is sparse.
    """
    if not similar:
        return ""

    items = similar[:max_items]
    list_items = "\n".join(
        f'<li><a href="{a["url"]}" title="{a["title"]}">{a["title"]}</a></li>'
        for a in items
    )
    return (
        f'\n\n<div class="related-articles" style="margin:2em 0;padding:1.2em;'
        f'border-left:3px solid #C0392B;background:#fafafa">\n'
        f"<h3>Related Articles</h3>\n"
        f"<ul>\n{list_items}\n</ul>\n"
        f"</div>\n"
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def link_article(
    new_post_id: int,
    new_post_html: str,
    new_post_title: str,
    new_post_url: str,
    config: Config,
    update_post_fn,            # Callable(post_id, html) → None  (sync WP REST call)
    get_post_fn=None,          # Callable(post_id) → dict        (optional, for backlinks)
) -> dict:
    """
    Full internal linking pass for a newly published article.

    Args:
        new_post_id       — WordPress post ID
        new_post_html     — Raw HTML content of the new article
        new_post_title    — Article title (plain text)
        new_post_url      — Canonical permalink
        config            — Pipeline config (needs OpenAI key)
        update_post_fn    — Function to PATCH WP post content (post_id, html)
        get_post_fn       — Function to GET WP post content (post_id) → dict

    Returns stats dict with link counts.
    """
    logger.info(f"[linker] Starting for post {new_post_id}: {new_post_title[:60]}")
    t0 = time.time()

    all_embeddings = load_embeddings()
    graph          = load_link_graph()

    if not all_embeddings:
        logger.warning("[linker] No article embeddings found — run /seo/embeddings/rebuild first")
        return {"error": "no_embeddings", "outgoing": 0, "backlinks": 0}

    # ── Step 1: embed new article ────────────────────────────────────────────
    raw_text   = re.sub(r"<[^>]+>", " ", new_post_html)
    embed_src  = f"{new_post_title}. {raw_text[:2000]}"
    new_vector = embed_text(embed_src, config)

    # ── Step 2: find similar articles ────────────────────────────────────────
    similar = get_similar_articles(
        new_vector,
        all_embeddings,
        exclude_ids=[new_post_id],
        top_k=25,
        min_score=MIN_SIMILARITY,
    )
    logger.info(f"[linker] {len(similar)} candidates (score >= {MIN_SIMILARITY})")

    # ── Step 3: build link opportunities ─────────────────────────────────────
    opportunities: list[dict] = []
    for cand in similar[:20]:
        # Try to find verbatim phrases in the new article first
        phrases = _find_verbatim_phrases(
            new_post_html, cand["title"], cand["excerpt"], config
        )
        if not phrases:
            # Fall back to GPT anchor generation (won't be verbatim, skip injection)
            phrases = _generate_anchors_for_pair(
                new_post_title, cand["title"], cand["excerpt"], config
            )

        opportunities.append({**cand, "phrases": phrases})

    # ── Step 4: inject outgoing links into new article ────────────────────────
    modified_html, n_out = _inject_links(
        new_post_html, opportunities, max_links=TARGET_OUTGOING
    )

    # ── Step 5: always append "Related Articles" section ─────────────────────
    if similar[:6]:
        modified_html += _build_related_section(similar[:6])
        # These count as outgoing links too
        n_out += min(len(similar), 6)

    logger.info(f"[linker] Injected {n_out} outgoing links")

    # ── Step 6: update new article in WordPress ───────────────────────────────
    try:
        update_post_fn(new_post_id, modified_html)
        logger.info(f"[linker] Updated post {new_post_id} content")
    except Exception as exc:
        logger.error(f"[linker] WP update failed for {new_post_id}: {exc}")

    # Update link graph for outgoing links
    for opp in opportunities[:n_out]:
        _update_graph(graph, new_post_id, opp["post_id"], opp.get("phrases", []))

    # ── Step 7: backlink injection into existing articles ─────────────────────
    n_back = 0
    if get_post_fn:
        for cand in similar[:MAX_BACKLINK_UPDATES]:
            if n_back >= MAX_BACKLINK_UPDATES:
                break
            try:
                existing = get_post_fn(cand["post_id"])
                existing_html = existing.get("content", {}).get("rendered", "")
                if not existing_html:
                    continue

                # Check if backlink already exists
                if new_post_url in existing_html:
                    continue

                back_anchors = _generate_anchors_for_pair(
                    cand["title"], cand["excerpt"],
                    new_post_title,
                    re.sub(r"<[^>]+>", " ", new_post_html)[:300],
                    config,
                )

                back_opps = [{
                    "url":     new_post_url,
                    "title":   new_post_title,
                    "phrases": back_anchors,
                    "score":   cand["score"],
                }]

                updated_html, n = _inject_links(existing_html, back_opps, max_links=2)
                if n > 0:
                    update_post_fn(cand["post_id"], updated_html)
                    _update_graph(graph, cand["post_id"], new_post_id, back_anchors)
                    n_back += 1
                    logger.info(f"[linker] Backlink added: post {cand['post_id']} → {new_post_id}")

            except Exception as exc:
                logger.warning(f"[linker] Backlink failed for post {cand['post_id']}: {exc}")

    # ── Persist graph + return stats ──────────────────────────────────────────
    graph["stats"]["total_links"] = sum(len(v) for v in graph["outgoing"].values())
    graph["stats"]["last_rebuilt"] = time.time()
    save_link_graph(graph)

    elapsed = round(time.time() - t0, 1)
    result  = {
        "post_id":   new_post_id,
        "outgoing":  n_out,
        "backlinks": n_back,
        "candidates": len(similar),
        "elapsed_s": elapsed,
    }
    logger.info(f"[linker] Done in {elapsed}s — {n_out} outgoing, {n_back} backlinks")
    return result


# ── Orphan detection ──────────────────────────────────────────────────────────

def find_orphan_posts(all_post_ids: list[int]) -> list[int]:
    """
    Return IDs of posts with zero incoming links — true orphan pages.
    Orphans are invisible to Google's link-graph crawler.
    """
    graph    = load_link_graph()
    incoming = graph.get("incoming", {})
    orphans  = [pid for pid in all_post_ids if str(pid) not in incoming]
    return orphans


# ── Link graph stats ──────────────────────────────────────────────────────────

def get_link_stats() -> dict:
    """Return high-level stats from the link graph for the SEO dashboard."""
    graph     = load_link_graph()
    outgoing  = graph.get("outgoing", {})
    incoming  = graph.get("incoming", {})

    all_ids   = set(outgoing) | set(incoming)
    total_links = sum(len(v) for v in outgoing.values())
    orphans     = [pid for pid in all_ids if pid not in incoming]

    avg_out  = total_links / max(len(outgoing), 1)
    avg_in   = total_links / max(len(incoming), 1)

    return {
        "total_links":    total_links,
        "total_pages":    len(all_ids),
        "orphan_pages":   len(orphans),
        "avg_outgoing":   round(avg_out, 1),
        "avg_incoming":   round(avg_in, 1),
        "last_rebuilt":   graph.get("stats", {}).get("last_rebuilt", 0),
    }
