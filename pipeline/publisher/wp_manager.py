"""
WordPress post management — list, get, update, delete, create posts,
upload media, and fetch categories.

Used by the FastAPI sidecar for the dashboard's Posts Manager feature.
All functions are synchronous (requests-based) — call via asyncio.to_thread
or directly from FastAPI route handlers for this low-traffic dashboard.
"""
from __future__ import annotations

import base64
from typing import Optional

import requests

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("wp_manager")

# ── Auth ───────────────────────────────────────────────────────────────────────

def _auth(config: Config) -> str:
    return base64.b64encode(
        f"{config.wp_username}:{config.wp_app_password}".encode()
    ).decode()


def _json_headers(config: Config) -> dict:
    return {
        "Authorization": f"Basic {_auth(config)}",
        "Content-Type": "application/json",
    }


# ── Posts ──────────────────────────────────────────────────────────────────────

def list_posts(
    config: Config,
    page: int = 1,
    per_page: int = 20,
    status: str = "any",
    search: str = "",
) -> tuple[list[dict], int, int]:
    """
    Return (posts, total_count, total_pages).
    Each post includes embedded category names and featured media via _embed.
    """
    params: dict = {
        "page": page,
        "per_page": min(per_page, 100),
        "orderby": "date",
        "order": "desc",
        "_embed": "wp:term,wp:featuredmedia",
    }
    if status != "any":
        params["status"] = status
    if search:
        params["search"] = search

    resp = requests.get(
        f"{config.wp_url}/wp-json/wp/v2/posts",
        params=params,
        headers=_json_headers(config),
        timeout=25,
    )
    resp.raise_for_status()
    total = int(resp.headers.get("X-WP-Total", 0))
    total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
    return resp.json(), total, total_pages


def get_post(config: Config, post_id: int) -> dict:
    """Get a single post with embedded terms and featured media."""
    resp = requests.get(
        f"{config.wp_url}/wp-json/wp/v2/posts/{post_id}",
        params={"_embed": "wp:term,wp:featuredmedia"},
        headers=_json_headers(config),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def create_post(config: Config, data: dict) -> dict:
    """Create a new WordPress post. Returns the created post dict."""
    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/posts",
        json=data,
        headers=_json_headers(config),
        timeout=30,
    )
    resp.raise_for_status()
    post = resp.json()
    logger.info(f"Created WP post ID={post['id']} status={data.get('status','publish')}")
    return post


def update_post(config: Config, post_id: int, data: dict) -> dict:
    """Update an existing WordPress post. Returns updated post dict."""
    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/posts/{post_id}",
        json=data,
        headers=_json_headers(config),
        timeout=30,
    )
    resp.raise_for_status()
    post = resp.json()
    logger.info(f"Updated WP post ID={post_id}")
    return post


def delete_post(config: Config, post_id: int, force: bool = False) -> dict:
    """
    Trash or permanently delete a WordPress post.
    force=False → moves to Trash (reversible).
    force=True  → permanent delete.
    """
    resp = requests.delete(
        f"{config.wp_url}/wp-json/wp/v2/posts/{post_id}",
        params={"force": "true" if force else "false"},
        headers=_json_headers(config),
        timeout=20,
    )
    resp.raise_for_status()
    logger.info(f"Deleted WP post ID={post_id} force={force}")
    return resp.json()


# ── Media ──────────────────────────────────────────────────────────────────────

def upload_media(
    config: Config,
    image_bytes: bytes,
    filename: str,
    mime_type: str,
    alt_text: str = "",
    title: str = "",
) -> dict:
    """
    Upload raw image bytes to the WordPress media library.
    Returns the full media object (includes id, source_url, link, etc.).
    """
    upload_headers = {
        "Authorization": f"Basic {_auth(config)}",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime_type,
    }
    resp = requests.post(
        f"{config.wp_url}/wp-json/wp/v2/media",
        data=image_bytes,
        headers=upload_headers,
        timeout=90,
    )
    resp.raise_for_status()
    media = resp.json()

    # Set alt text + title in a follow-up call
    if alt_text or title:
        requests.post(
            f"{config.wp_url}/wp-json/wp/v2/media/{media['id']}",
            json={
                "alt_text": alt_text or filename,
                "title": {"raw": title or filename},
            },
            headers=_json_headers(config),
            timeout=15,
        )

    logger.info(f"Uploaded media ID={media['id']} url={media.get('source_url','')}")
    return media


# ── Categories ─────────────────────────────────────────────────────────────────

def get_categories(config: Config) -> list[dict]:
    """Return all WordPress categories (up to 100)."""
    resp = requests.get(
        f"{config.wp_url}/wp-json/wp/v2/categories",
        params={"per_page": 100, "orderby": "name", "order": "asc"},
        headers=_json_headers(config),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()
