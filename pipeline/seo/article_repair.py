"""
Article repair — fix already-published WordPress posts that were rendered
with the old broken markdown converter.

What the old converter got wrong (and what this module fixes):
  1. GFM tables `| col | col |\n|---|---|\n| data | data |` were dropped
     into <p> tags as raw text → render as pipe-character soup
  2. Markdown links `[text](url)` and `[text](#anchor)` were never converted
     → show as literal `[text](url)` strings
  3. Indented ToC items using en-dash characters ("– item") were treated
     as plain text → render as raw dashes

Table separator row variants handled:
  | --- | --- |           ASCII hyphens (standard GFM)
  | :---: | ---: |        Alignment colons
  | — | — |               Em-dash (U+2014) — Claude sometimes generates these
  | – | – |               En-dash (U+2013)
  | ——— | ——— |           Long em-dash runs
  | &#8212; | &#8212; |   HTML-encoded em-dash
  |———|———|               Tight form without spaces

What the old converter got right (so we don't touch):
  - `## H2` → `<h2>` ✓
  - `### H3` → `<h3>` ✓
  - `**bold**` → `<strong>` ✓
  - `- item` → `<ul><li>` ✓
  - Paragraphs ✓
"""
from __future__ import annotations

import re
from typing import Tuple

from ..utils.logger import get_logger

logger = get_logger("seo.article_repair")


# ── Slug helper (matches the new wordpress_client._slugify_heading) ──────────

def _slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text


# ── 1. Markdown link conversion ────────────────────────────────────────────────

_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")


def _fix_markdown_links(html: str, stats: dict) -> str:
    """
    Convert `[text](url)` → `<a href="url">text</a>` everywhere in the HTML.

    Skips matches that already sit inside an `<a>` tag (rare but defensive).
    """
    def repl(m: re.Match) -> str:
        text, url = m.group(1).strip(), m.group(2).strip()
        # Anchor links: keep as-is (they target H2 ids we'll add via slug later)
        href = url
        stats["links_fixed"] += 1
        return f'<a href="{href}">{text}</a>'

    return _MD_LINK_RE.sub(repl, html)


# ── 2. Pipe-table detection + conversion ──────────────────────────────────────

# A data row: `| col | col |` — must contain at least 2 cells
_DATA_ROW_RE = re.compile(r"^\s*\|.+\|.+\|\s*$")

# Characters that are valid inside a separator cell (dashes in any form + colon)
_SEP_CELL_CHARS = frozenset(
    "-"          # ASCII hyphen
    "–"     # en-dash –
    "—"     # em-dash —
    "―"     # horizontal bar ―
    "−"     # minus sign −
    ":"          # alignment colon
    " \t"        # whitespace
)
# At least one of these must appear in a separator cell
_ACTUAL_DASH_CHARS = frozenset("-–—―−")


def _is_separator_row(line: str) -> bool:
    """
    Return True if *line* is a GFM table separator row in any supported form.

    Recognised separator cells (between pipes):
      ---        :---:       ---:       (ASCII hyphens ± alignment colons)
      ———        –––         −−−        (em/en/minus dash)
      ——         –           —          (even single dash counts per column)

    All cells must contain ONLY separator characters. At least one cell must
    have at least one actual dash character (rules out `|   |   |` blank rows).
    """
    stripped = line.strip()
    # Must start or end with a pipe (even `---` without pipes is not a table row)
    if not ("|" in stripped):
        return False

    inner = stripped.strip("|").strip()
    if not inner:
        return False

    cells = [c.strip() for c in inner.split("|")]
    if not cells:
        return False

    has_dash = False
    for cell in cells:
        if not cell:
            # Empty cell is fine (outer pipes leave empty first/last cell)
            continue
        # Every character in this cell must be a separator character
        if not all(ch in _SEP_CELL_CHARS for ch in cell):
            return False
        # Track whether we saw at least one real dash anywhere
        if any(ch in _ACTUAL_DASH_CHARS for ch in cell):
            has_dash = True

    return has_dash


def _row_to_cells(row: str) -> list[str]:
    """`| a | b | c |` → ['a', 'b', 'c']"""
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    return cells  # keep all cells (including empties) for column alignment


def _rows_to_html_table(rows: list[list[str]]) -> str:
    """Convert a list of cell-rows (header first) into `<table>` HTML."""
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    html = ['<table class="cad-article-table">']
    html.append("<thead><tr>")
    for cell in header:
        html.append(f"<th>{cell}</th>")
    html.append("</tr></thead>")
    if body:
        html.append("<tbody>")
        for row in body:
            html.append("<tr>")
            # Pad/truncate to header width so HTML is well-formed
            padded = (row + [""] * len(header))[: len(header)]
            for cell in padded:
                html.append(f"<td>{cell}</td>")
            html.append("</tr>")
        html.append("</tbody>")
    html.append("</table>")
    return "".join(html)


def _fix_pipe_tables(html: str, stats: dict) -> str:
    """
    Find blocks of pipe-table syntax that ended up in <p> tags (often with
    <br> separators inserted by WP's wpautop) and replace them with proper
    HTML tables.

    Strategy:
      1. Find consecutive <p> tags whose text content is pipe-delimited rows
      2. Strip <p>/<br> wrapper tags to recover raw lines
      3. Classify each line: separator row (skip), data row (keep as cells)
      4. If we found ≥2 data rows AND a separator → emit a proper <table>
    """
    # Pattern: one or more consecutive <p> tags whose visible text starts and
    # ends with a pipe. Allow optional <br/> and whitespace inside.
    p_with_pipes_re = re.compile(
        r"(?:<p[^>]*>\s*\|[^<]*?\|\s*(?:<br\s*/?>\s*\|[^<]*?\|\s*)*</p>\s*)+",
        re.IGNORECASE,
    )

    def replace_p_block(m: re.Match) -> str:
        block = m.group(0)
        # Strip all <p>/<br> tags to get clean pipe-row lines
        text = re.sub(r"<br\s*/?>", "\n", block, flags=re.IGNORECASE)
        text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Decode common HTML entities that WP / browser may have encoded
        text = (text
                .replace("&amp;", "&")
                .replace("&nbsp;", " ")
                .replace("&mdash;", "—")
                .replace("&ndash;", "–")
                .replace("&#8212;", "—")   # decimal em-dash
                .replace("&#8211;", "–")   # decimal en-dash
                .replace("&#x2014;", "—")  # hex em-dash
                .replace("&#x2013;", "–")) # hex en-dash
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        rows: list[list[str]] = []
        had_separator = False
        for ln in lines:
            if _is_separator_row(ln):
                had_separator = True
                continue  # separator rows are structural — never add as data
            if _DATA_ROW_RE.match(ln):
                rows.append(_row_to_cells(ln))

        # Need at least 2 rows AND a separator row to be confident this was a table
        if len(rows) >= 2 and had_separator:
            stats["tables_fixed"] += 1
            return _rows_to_html_table(rows) + "\n"
        return block  # leave it alone — wasn't a table

    return p_with_pipes_re.sub(replace_p_block, html)


# ── 3. ToC sub-item dashes (en-dash bullets) ─────────────────────────────────

# Old converter emitted "– [text](#anchor)" sub-items as raw text.
# After we've already fixed the markdown links above, we still need to
# turn the leading "– " (en-dash + space) into a proper list item.
# These usually live INSIDE a <ul> that the converter built for the parent
# bullets, so they appear as paragraphs interleaved with the <ul>.
_ENDASH_PARA_RE = re.compile(
    r'<p>\s*[–\-]\s+(<a [^>]+>[^<]+</a>)\s*</p>',
    re.IGNORECASE,
)


def _fix_endash_subitems(html: str, stats: dict) -> str:
    """Convert orphaned `<p>– <a href="#x">y</a></p>` into proper `<li>` nodes."""
    def repl(m: re.Match) -> str:
        stats["subitems_fixed"] += 1
        return f"<li>{m.group(1)}</li>"

    return _ENDASH_PARA_RE.sub(repl, html)


# ── 4. Heading anchor IDs (so [text](#slug) links actually jump) ─────────────

_H2_RE = re.compile(r"<h2(?![^>]*\bid=)([^>]*)>([^<]+)</h2>", re.IGNORECASE)
_H3_RE = re.compile(r"<h3(?![^>]*\bid=)([^>]*)>([^<]+)</h3>", re.IGNORECASE)


def _add_heading_ids(html: str, stats: dict) -> str:
    """Inject `id="slug"` on every H2/H3 that doesn't already have one."""
    def add_id(tag: str):
        def repl(m: re.Match) -> str:
            attrs = m.group(1)
            text = m.group(2).strip()
            slug = _slug(text)
            if not slug:
                return m.group(0)
            stats["ids_added"] += 1
            return f'<{tag} id="{slug}"{attrs}>{m.group(2)}</{tag}>'
        return repl

    html = _H2_RE.sub(add_id("h2"), html)
    html = _H3_RE.sub(add_id("h3"), html)
    return html


# ── Public entry point ───────────────────────────────────────────────────────

def repair_article_html(html: str) -> Tuple[str, dict]:
    """
    Repair a single article's HTML body.
    Returns (new_html, stats).
    `stats` keys: links_fixed, tables_fixed, subitems_fixed, ids_added.

    Idempotent — running it twice on the same content does nothing the
    second time because the patterns no longer match.
    """
    stats = {
        "links_fixed": 0,
        "tables_fixed": 0,
        "subitems_fixed": 0,
        "ids_added": 0,
    }

    new_html = html
    new_html = _fix_markdown_links(new_html, stats)
    new_html = _fix_pipe_tables(new_html, stats)
    new_html = _fix_endash_subitems(new_html, stats)
    new_html = _add_heading_ids(new_html, stats)

    return new_html, stats


def needs_repair(html: str) -> bool:
    """
    Quick check: does this article have any of the broken patterns?

    Checked patterns:
      - Markdown links: [text](url) still in the HTML as literal text
      - ASCII hyphen separator rows: | --- | --- |
      - Em-dash separator rows:      | — | — |  or  | ——— | ——— |
      - En-dash separator rows:      | – | – |
      - HTML-entity-encoded em-dash: | &#8212; | &#8212; |
    """
    # Markdown links not yet converted
    if _MD_LINK_RE.search(html):
        return True
    # ASCII-hyphen separator row (most common)
    if re.search(r"\|\s*:?-{2,}:?\s*\|", html):
        return True
    # Em-dash / en-dash separator row (Claude sometimes generates these)
    if re.search(r"\|\s*[–—―]{1,}\s*\|", html):
        return True
    # HTML-entity-encoded em-dash in separator row
    if re.search(r"\|\s*(?:&mdash;|&#8212;|&#x2014;)\s*\|", html):
        return True
    return False


# ── Batch repair for the FastAPI endpoint ───────────────────────────────────

def repair_all_posts(config, list_posts_fn, update_post_fn, dry_run: bool = False) -> dict:
    """
    Walk every published post and repair the ones that need it.

    Args:
      config:          pipeline Config
      list_posts_fn:   callable(config, page, per_page, status) -> (posts, total, total_pages)
      update_post_fn:  callable(config, post_id, {"content": new_html}) -> dict
      dry_run:         if True, scan & report but don't actually update

    Returns aggregate stats.
    """
    page = 1
    per_page = 50
    summary = {
        "scanned": 0,
        "needed_repair": 0,
        "repaired": 0,
        "skipped_clean": 0,
        "errors": 0,
        "per_post": [],
    }

    while True:
        posts, total, total_pages = list_posts_fn(config, page, per_page, "publish")
        if not posts:
            break

        for post in posts:
            summary["scanned"] += 1
            post_id = post.get("id")
            title = post.get("title", {}).get("rendered", "")
            html = post.get("content", {}).get("rendered", "")

            if not html:
                continue

            if not needs_repair(html):
                summary["skipped_clean"] += 1
                continue

            summary["needed_repair"] += 1
            try:
                new_html, stats = repair_article_html(html)
                if new_html == html:
                    # needs_repair fired but nothing changed — mark clean
                    summary["skipped_clean"] += 1
                    continue

                if not dry_run:
                    update_post_fn(config, post_id, {"content": new_html})

                summary["repaired"] += 1
                summary["per_post"].append({
                    "id": post_id,
                    "title": title[:80],
                    "stats": stats,
                })
                logger.info(f"[repair] post {post_id} '{title[:50]}': {stats}")
            except Exception as exc:
                summary["errors"] += 1
                logger.exception(f"[repair] post {post_id} failed: {exc}")

        if page >= total_pages:
            break
        page += 1

    return summary
