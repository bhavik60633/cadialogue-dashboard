"""
WordPress REST API client.
Publishes articles, uploads media, sets SEO meta.
Uses WordPress Application Passwords (Basic Auth).
"""
import base64
import re
from pathlib import Path
from typing import Optional

import requests

from ..config import Config
from ..research.topic_finder import CATEGORY_MAP
from ..utils.logger import get_logger
from ..utils.retry import with_retry_sync
from ..writer.article_generator import SEOMeta
from .seo_meta import build_wp_meta

logger = get_logger("wordpress_client")


def _auth_header(config: Config) -> dict:
    token = base64.b64encode(
        f"{config.wp_username}:{config.wp_app_password}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


def _markdown_to_html(md: str) -> str:
    """
    Convert Claude's markdown output to WordPress-compatible HTML.

    Uses the python-markdown library with extensions for:
      - tables          → proper <table> with <thead>/<tbody>
      - toc             → auto-injects id="..." on h2/h3 so [text](#anchor) ToC works
      - sane_lists      → mixed ordered/unordered lists render correctly
      - fenced_code     → ```code``` blocks
      - attr_list       → {.classname} attributes
      - md_in_html      → markdown inside HTML blocks (figures, etc.)

    Falls back to the legacy regex converter only if `markdown` import fails
    (should never happen in production since it's pinned in requirements.txt).
    """
    try:
        import markdown as _md
        html = _md.markdown(
            md,
            extensions=[
                "tables",
                "toc",
                "sane_lists",
                "fenced_code",
                "attr_list",
                "md_in_html",
            ],
            extension_configs={
                # Make heading anchor IDs match GitHub-style slugs:
                # "Impact on Gold and Silver Prices" → "impact-on-gold-and-silver-prices"
                "toc": {"slugify": _slugify_heading, "anchorlink": False, "permalink": False},
            },
            output_format="html5",
        )
        # WP-specific class hooks so the theme can style tables
        html = html.replace("<table>", '<table class="cad-article-table">')
        return html
    except ImportError:
        logger.warning("python-markdown not installed — falling back to regex converter")
        return _markdown_to_html_regex(md)


def _slugify_heading(value: str, separator: str = "-") -> str:
    """GitHub-style heading slug for stable ToC anchor links."""
    value = value.lower().strip()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s_]+", separator, value)
    return value


def _markdown_to_html_regex(md: str) -> str:
    """
    Fallback regex-based converter (kept for resilience).
    Does NOT handle tables or markdown links — only headings, bold/italic, lists, paragraphs.
    """
    html = md
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^# .+$", "", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", html)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    def replace_ul(m):
        items = re.findall(r"^[-*] (.+)$", m.group(0), re.MULTILINE)
        return "<ul>\n" + "\n".join(f"<li>{i}</li>" for i in items) + "\n</ul>"

    html = re.sub(r"(?:^[-*] .+\n?)+", replace_ul, html, flags=re.MULTILINE)

    blocks = html.split("\n\n")
    wrapped = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("<"):
            wrapped.append(block)
        else:
            wrapped.append(f"<p>{block}</p>")
    return "\n\n".join(wrapped)


@with_retry_sync(max_attempts=3, delay_seconds=5)
def _get_or_create_category(name: str, config: Config) -> int:
    """Return category ID, creating it if it doesn't exist."""
    base = f"{config.wp_url}/wp-json/wp/v2/categories"
    headers = _auth_header(config)

    # Search for existing
    resp = requests.get(base, params={"search": name}, headers=headers, timeout=15)
    resp.raise_for_status()
    results = resp.json()
    if results:
        return results[0]["id"]

    # Create new
    resp = requests.post(base, json={"name": name}, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()["id"]


@with_retry_sync(max_attempts=3, delay_seconds=5)
def _upload_featured_image(image_url: str, alt_text: str, config: Config) -> Optional[int]:
    """Download image from URL and upload to WordPress media library."""
    try:
        img_resp = requests.get(image_url, timeout=20)
        img_resp.raise_for_status()
        content_type = img_resp.headers.get("Content-Type", "image/jpeg")
        filename = image_url.split("/")[-1].split("?")[0] or "featured.jpg"

        headers = {
            **_auth_header(config),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        }
        upload_url = f"{config.wp_url}/wp-json/wp/v2/media"
        resp = requests.post(upload_url, data=img_resp.content, headers=headers, timeout=30)
        resp.raise_for_status()

        media_id = resp.json()["id"]

        # Set alt text
        requests.post(
            f"{upload_url}/{media_id}",
            json={"alt_text": alt_text},
            headers=_auth_header(config),
            timeout=10,
        )
        return media_id
    except Exception as exc:
        logger.warning(f"Featured image upload failed: {exc}")
        return None


def _build_payload(
    article: str,
    seo_meta: SEOMeta,
    schemas_html: str,
    category: str,
    config: Config,
    status: str = "publish",
    featured_media_id: Optional[int] = None,
) -> dict:
    """Assemble the full WordPress REST API post payload."""
    html_content = _markdown_to_html(article)
    # NOTE: schemas are NOT embedded in post content.
    # WordPress strips <script> tags from post bodies, leaving raw JSON visible.
    # The cadialogue-homepage.php mu-plugin already injects correct NewsArticle
    # JSON-LD for every post via wp_head — no duplication needed here.
    full_content = html_content

    category_label = CATEGORY_MAP.get(category, "Finance")
    category_id = _get_or_create_category(category_label, config)

    # Build a clean excerpt: prefer meta_description (145-155 chars, keyword-rich),
    # fall back to first 30 words of stripped HTML content.
    _clean = re.sub(r'<[^>]+>', ' ', html_content)
    _clean = re.sub(r'\s+', ' ', _clean).strip()
    _exc_words = _clean.split()
    _auto_exc = ' '.join(_exc_words[:30]) + ('…' if len(_exc_words) > 30 else '')
    excerpt_text = (seo_meta.meta_description or _auto_exc)[:250]

    payload: dict = {
        "title": seo_meta.title,
        "content": full_content,
        "excerpt": excerpt_text,
        "status": status,
        "slug": seo_meta.slug,
        "categories": [category_id],
        "meta": build_wp_meta(seo_meta, config),
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    return payload


async def publish_post(
    article: str,
    seo_meta: SEOMeta,
    schemas_html: str,
    config: Config,
    category: str = "global_market",
    featured_image_url: Optional[str] = None,
    status: str = "draft",
) -> dict:
    """
    Push article to WordPress. Returns the created post dict.

    `status` defaults to "draft" — the article does NOT go public until a
    reviewer transitions it via `transition_draft_to_publish()`.
    Pass status="publish" explicitly to skip the review gate (legacy / urgent).
    """
    label = "Publishing" if status == "publish" else "Saving as draft"
    logger.info(f"{label}: {seo_meta.title}")

    # Upload featured image if provided
    featured_media_id = None
    if featured_image_url:
        featured_media_id = _upload_featured_image(
            featured_image_url, seo_meta.title, config
        )

    payload = _build_payload(
        article, seo_meta, schemas_html, category, config,
        status=status, featured_media_id=featured_media_id,
    )

    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/posts",
        json=payload,
        headers=_auth_header(config),
        timeout=30,
    )
    resp.raise_for_status()
    post = resp.json()
    logger.info(f"{label} done — post ID={post['id']} status={post.get('status')} URL={post.get('link')}")

    # ── Auto-trigger SEO post-publish pipeline ────────────────────────────────
    # Only fires when the post is actually PUBLIC (status="publish").
    # Drafts skip this — no point indexing or internal-linking content that
    # isn't yet live.
    if post.get("status") == "publish":
        _run_seo_post_publish(post, config)

    return post


def transition_draft_to_publish(post_id: int, config: Config) -> dict:
    """
    Promote an existing WordPress draft to status="publish".

    This is the function the dashboard's "Approve & Publish" button calls
    after a human reviewer has read the draft. After flipping the status,
    we trigger the full SEO post-publish pipeline (embeddings, internal
    linking, Google Indexing API + IndexNow ping).

    Returns the updated WordPress post dict.
    """
    logger.info(f"Approving draft post {post_id} for publication…")
    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/posts/{post_id}",
        json={"status": "publish"},
        headers=_auth_header(config),
        timeout=30,
    )
    resp.raise_for_status()
    post = resp.json()
    logger.info(f"Post {post_id} is now LIVE — {post.get('link')}")

    # Now that it's public, run the SEO pipeline
    _run_seo_post_publish(post, config)
    return post


def _run_seo_post_publish(post: dict, config: Config) -> None:
    """
    Fire-and-forget SEO actions after a post is published.
    Errors are logged but never raised (must not break the publish flow).

    Actions:
      1. Upsert article embedding (enables future similarity search)
      2. Run internal linking engine (30+ links in + backlinks out)
      3. Submit URL to Google Indexing API + IndexNow
    """
    import threading

    def _bg():
        try:
            # 1. Embed article
            from ..seo.embeddings_store import upsert_article_embedding
            upsert_article_embedding(post, config)
            logger.info(f"[SEO] Embedded post {post['id']}")
        except Exception as exc:
            logger.warning(f"[SEO] Embedding failed for post {post['id']}: {exc}")

        try:
            # 2. Internal linking
            from ..seo.internal_linker import link_article
            from .wp_manager import get_post as _get_post, update_post as _update_post

            html = post.get("content", {}).get("rendered", "")
            link_article(
                new_post_id=post["id"],
                new_post_html=html,
                new_post_title=post.get("title", {}).get("rendered", ""),
                new_post_url=post.get("link", ""),
                config=config,
                update_post_fn=lambda pid, content: _update_post(config, pid, {"content": content}),
                get_post_fn=lambda pid: _get_post(config, pid),
            )
            logger.info(f"[SEO] Internal linking complete for post {post['id']}")
        except Exception as exc:
            logger.warning(f"[SEO] Internal linking failed for post {post['id']}: {exc}")

        try:
            # 3. Notify search engines
            from ..seo.sitemap_manager import notify_search_engines
            notify_search_engines(post.get("link", ""), config)
            logger.info(f"[SEO] Indexed URL: {post.get('link', '')}")
        except Exception as exc:
            logger.warning(f"[SEO] Index notification failed: {exc}")

    # Run in background thread — doesn't block the API response
    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def upload_local_image(file_path: Path, alt_text: str, title: str, config: Config) -> tuple[int, str]:
    """
    Upload a local PNG/JPEG to WordPress media library.
    Returns (media_id, source_url).
    """
    with open(file_path, "rb") as fh:
        img_data = fh.read()

    ext = file_path.suffix.lower()
    content_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

    headers = {
        **_auth_header(config),
        "Content-Disposition": f'attachment; filename="{file_path.name}"',
        "Content-Type": content_type,
    }
    upload_url = f"{config.wp_url}/wp-json/wp/v2/media"
    resp = requests.post(upload_url, data=img_data, headers=headers, timeout=60)
    resp.raise_for_status()
    media = resp.json()
    media_id  = media["id"]
    media_url = media["source_url"]

    # Set alt text + title on the uploaded media
    requests.post(
        f"{upload_url}/{media_id}",
        json={"alt_text": alt_text, "title": {"raw": title}},
        headers=_auth_header(config),
        timeout=15,
    )
    logger.info(f"Uploaded image → WP media ID={media_id}  url={media_url}")
    return media_id, media_url


def _split_markdown_sections(markdown: str) -> list[tuple[str, str]]:
    """
    Split markdown into (heading_line, body_text) tuples.
    First block has heading="" if content appears before the first H2.
    """
    parts = re.split(r'(?=^#{1,2} )', markdown, flags=re.MULTILINE)
    sections = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.split("\n")
        heading = lines[0] if re.match(r'^#{1,2} ', lines[0]) else ""
        sections.append((heading, part))
    return sections


def build_html_with_images(
    markdown: str,
    images: list[dict],
    wp_image_map: dict[str, str],     # section_id → wp_media_url
    skip_sections: Optional[set] = None,  # section_ids to skip (used as featured image)
) -> str:
    """
    Convert article markdown to HTML, inserting uploaded WP images after
    each section that has one. Returns the final HTML string.
    Sections in `skip_sections` are not embedded inline (they are used as featured/hero).
    """
    sections = _split_markdown_sections(markdown)
    skip_sections = skip_sections or set()

    # Build section_id → image data
    img_lookup = {img["section_id"]: img for img in (images or [])}

    html_blocks: list[str] = []
    for idx, (heading_line, section_text) in enumerate(sections):
        section_id = f"s{idx}"
        html_blocks.append(_markdown_to_html(section_text))

        if section_id in skip_sections:
            continue  # Don't embed inline — shown as featured image at top

        if section_id in img_lookup and section_id in wp_image_map:
            img_data  = img_lookup[section_id]
            img_url   = wp_image_map[section_id]
            alt_text  = img_data.get("alt_text", "")
            photographer = img_data.get("photographer", "")
            source       = img_data.get("source", "ai")
            ratio_css    = {
                "16:9": "aspect-ratio:16/9",
                "1:1":  "aspect-ratio:1/1",
                "4:3":  "aspect-ratio:4/3",
            }.get(img_data.get("selected_ratio", "16:9"), "")

            caption = f"Photo by {photographer} / Pexels" if source == "pexels" and photographer else ""
            fig_html = (
                f'<figure class="wp-block-image size-large">'
                f'<img src="{img_url}" alt="{alt_text}" '
                f'style="width:100%;{ratio_css};object-fit:cover;" />'
            )
            if caption:
                fig_html += f'<figcaption class="wp-element-caption">{caption}</figcaption>'
            fig_html += '</figure>'
            html_blocks.append(fig_html)

    return "\n\n".join(html_blocks)


async def update_post_with_images(
    wp_post_id: int,
    article_markdown: str,
    images: list[dict],           # run["images"]
    config: Config,
    images_dir: Path,             # pipeline/state/images/{run_id}/
) -> dict:
    """
    Upload each selected image to WP, embed them in the article HTML,
    update the existing post. Returns the updated post dict.
    """
    from pipeline.state.image_store import IMAGES_DIR as IMG_ROOT

    # ── 1. Upload each image that has a selected ratio ─────────────────────
    wp_image_map: dict[str, str] = {}     # section_id → wp_url
    featured_media_id: Optional[int] = None
    first_uploaded_media_id: Optional[int] = None  # fallback hero if none marked
    first_uploaded_section_id: Optional[str] = None

    # If no image is explicitly marked as featured, auto-promote the first one
    any_user_marked_featured = any(img.get("is_featured") for img in (images or []))

    for img in (images or []):
        section_id     = img.get("section_id", "")
        selected_ratio = img.get("selected_ratio", "16:9")
        ratios         = img.get("ratios", {})
        api_path       = ratios.get(selected_ratio)     # "/api/images/{run_id}/filename.png"
        alt_text       = img.get("alt_text", "")
        is_featured    = img.get("is_featured", False)  # user-designated hero image

        if not api_path:
            continue

        # Resolve API path → local filesystem path
        parts      = api_path.lstrip("/").split("/")   # ["api", "images", run_id, filename]
        local_path = IMG_ROOT / parts[2] / parts[3]

        if not local_path.exists():
            logger.warning(f"Image file not found: {local_path}")
            continue

        try:
            media_id, media_url = upload_local_image(
                local_path, alt_text, f"CADialogue image – {section_id}", config
            )
            wp_image_map[section_id] = media_url
            if is_featured:
                featured_media_id = media_id
            # Track first successful upload as fallback hero
            if first_uploaded_media_id is None:
                first_uploaded_media_id = media_id
                first_uploaded_section_id = section_id
        except Exception as exc:
            logger.error(f"Failed to upload image for {section_id}: {exc}")

    # Fallback: if user didn't explicitly mark any image as hero,
    # promote the first uploaded image so the post always has a featured image
    if not featured_media_id and first_uploaded_media_id:
        featured_media_id = first_uploaded_media_id
        logger.info(f"Auto-promoting first image (section {first_uploaded_section_id}) as featured")

    # ── 2. Build HTML with embedded images ───────────────────────────────────
    featured_sections = {img["section_id"] for img in (images or []) if img.get("is_featured")}
    # If we auto-promoted, also skip that section from inline embedding
    if not any_user_marked_featured and first_uploaded_section_id:
        featured_sections.add(first_uploaded_section_id)
    content_html = build_html_with_images(
        article_markdown, images, wp_image_map,
        skip_sections=featured_sections,
    )

    # ── 3. Update WordPress post ──────────────────────────────────────────────
    payload: dict = {"content": content_html}
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/posts/{wp_post_id}",
        json=payload,
        headers=_auth_header(config),
        timeout=45,
    )
    resp.raise_for_status()
    post = resp.json()
    logger.info(f"Updated WP post {wp_post_id} with {len(wp_image_map)} image(s)")
    return post


async def save_as_draft(
    article: str,
    seo_meta: SEOMeta,
    schemas_html: str,
    config: Config,
    category: str = "global_market",
) -> dict:
    """Save article as WordPress draft (not published)."""
    logger.info(f"Saving draft: {seo_meta.title}")

    payload = _build_payload(
        article, seo_meta, schemas_html, category, config, status="draft"
    )

    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/posts",
        json=payload,
        headers=_auth_header(config),
        timeout=30,
    )
    resp.raise_for_status()
    post = resp.json()
    logger.info(f"Saved draft ID={post['id']} URL={post['link']}")
    return post
