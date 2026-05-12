"""
Search engine indexing pings.
Google Indexing API + IndexNow (Bing, Yandex) + sitemap ping.
"""
import json
from urllib.parse import urlparse

import requests

from ..config import Config
from ..utils.logger import get_logger
from ..utils.retry import with_retry_sync

logger = get_logger("indexer")


@with_retry_sync(max_attempts=3, delay_seconds=5)
def _ping_google(post_url: str, service_account_json: str) -> bool:
    """
    Notify Google Indexing API about a new/updated URL.
    Requires a Google service account with Search Console Owner permission.
    """
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleRequest

        sa_info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/indexing"],
        )
        creds.refresh(GoogleRequest())

        resp = requests.post(
            "https://indexing.googleapis.com/v3/urlNotifications:publish",
            json={"url": post_url, "type": "URL_UPDATED"},
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info(f"Google Indexing API: OK ({post_url})")
            return True
        logger.warning(f"Google Indexing API returned {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as exc:
        logger.warning(f"Google Indexing API failed: {exc}")
        return False


def _ping_indexnow(post_url: str, config: Config) -> dict[str, bool]:
    """
    Ping IndexNow for Bing, Yandex.
    Returns {engine: success} dict.
    """
    domain = urlparse(post_url).netloc
    payload = {
        "host": domain,
        "key": config.indexnow_key,
        "keyLocation": f"https://{domain}/{config.indexnow_key}.txt",
        "urlList": [post_url],
    }

    engines = {
        "bing":   "https://www.bing.com/indexnow",
        "yandex": "https://yandex.com/indexnow",
    }

    results = {}
    for name, url in engines.items():
        try:
            resp = requests.post(url, json=payload, timeout=15)
            ok = resp.status_code in (200, 202)
            results[name] = ok
            logger.info(f"IndexNow {name}: {'OK' if ok else f'HTTP {resp.status_code}'}")
        except Exception as exc:
            logger.warning(f"IndexNow {name} failed: {exc}")
            results[name] = False

    return results


def _ping_sitemap(site_url: str) -> bool:
    """Belt-and-suspenders: ping Google sitemap endpoint."""
    sitemap_url = f"{site_url}/sitemap.xml"
    try:
        resp = requests.get(
            "https://www.google.com/ping",
            params={"sitemap": sitemap_url},
            timeout=15,
        )
        ok = resp.status_code == 200
        logger.info(f"Sitemap ping: {'OK' if ok else f'HTTP {resp.status_code}'}")
        return ok
    except Exception as exc:
        logger.warning(f"Sitemap ping failed: {exc}")
        return False


async def ping_all(post_url: str, config: Config) -> dict:
    """Run all indexing pings and return results summary."""
    results: dict = {}

    # Google Indexing API
    if config.google_service_account_json:
        results["google"] = _ping_google(post_url, config.google_service_account_json)
    else:
        logger.warning("GOOGLE_SERVICE_ACCOUNT_JSON not set — skipping Google Indexing API")
        results["google"] = False

    # IndexNow (Bing + Yandex)
    if config.indexnow_key:
        indexnow_results = _ping_indexnow(post_url, config)
        results.update(indexnow_results)
    else:
        logger.warning("INDEXNOW_KEY not set — skipping IndexNow")
        results["bing"] = False
        results["yandex"] = False

    # Sitemap ping
    parsed = urlparse(post_url)
    site_url = f"{parsed.scheme}://{parsed.netloc}"
    results["sitemap"] = _ping_sitemap(site_url)

    successes = sum(1 for v in results.values() if v)
    logger.info(f"Indexing complete: {successes}/{len(results)} pings succeeded")
    return results
