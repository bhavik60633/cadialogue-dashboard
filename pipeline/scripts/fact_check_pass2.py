#!/usr/bin/env python3
"""
Second-pass fact-check corrections — handle cases the first pass missed.

What pass-1 missed and this pass fixes:
  1. Markdown artifact format: `"`markdown<br />` (curly-quote + single backtick + markdown)
  2. Gold tariff table: <td>7.5</td> for previous rate cell (no % sign in cell)
  3. Repo rate variants: "steady at 6.5%", "held at 6.5%", table cells "Repo Rate | 6.5%"
"""
import re
import json
import base64
import requests
from typing import Tuple, Dict, List

WP_URL  = "https://cadialogue.in"
WP_USER = "renuka.malik99@gmail.com"
WP_PASS = "BbaZ j5Za FELD 6wfg mUtb 517z"

_creds = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
HEADERS = {
    "Authorization": f"Basic {_creds}",
    "Content-Type":  "application/json; charset=utf-8",
}


# ── Pass-2 fix: markdown artifact (curly quote + single backtick) ────────────
def strip_markdown_v2(html: str) -> Tuple[str, int]:
    n = 0
    # Pattern: <p>&#8220;`markdown<br /> ... — strip the prefix
    pattern1 = re.compile(r'<p>(?:&#8220;|"|&ldquo;)?`+\s*markdown\s*(?:<br\s*/?>)?\s*', re.IGNORECASE)
    matches = pattern1.findall(html)
    new = pattern1.sub('<p>', html)
    n += len(matches)
    # Closing fence: trailing `</p> or ` only — strip them
    pattern2 = re.compile(r'(?:&#8221;|"|&rdquo;)?`+\s*</p>', re.IGNORECASE)
    # Only strip closing fence at the very end of content
    if new.rstrip().endswith('`</p>') or new.rstrip().endswith('```</p>'):
        new = re.sub(r'`+\s*</p>\s*$', '</p>', new.rstrip())
        n += 1
    return new, n


# ── Pass-2 fix: stricter, broader repo rate match ─────────────────────────────
def fix_repo_rate_v2(html: str) -> Tuple[str, int]:
    """
    Replace 6.5% references in repo-rate context using a wider net.
    Replaces 6.5% with 5.25% if it appears within ~80 chars of "repo rate" or "RBI ... repo".
    """
    n = 0
    # 1. "repo rate <any words 0-30 chars> 6.5%" (catches steady/held/maintained/kept at)
    pattern1 = re.compile(
        r'(repo\s+rate\b[^.<]{0,40}?)6\.50?\s*%',
        re.IGNORECASE
    )
    new, c1 = pattern1.subn(r'\g<1>5.25%', html)
    n += c1

    # 2. Table-cell pattern: <td>Repo Rate</td><td>6.5%</td>
    pattern2 = re.compile(
        r'(<t[dh][^>]*>\s*(?:RBI\s+)?(?:Benchmark\s+)?Repo\s+Rate\s*</t[dh]>\s*<td[^>]*>\s*)6\.50?\s*%(\s*</td>)',
        re.IGNORECASE
    )
    new, c2 = pattern2.subn(r'\g<1>5.25%\g<2>', new)
    n += c2

    # 3. Generic "RBI ... 6.5%" within proximity
    pattern3 = re.compile(
        r'(\bRBI\b[^.<]{0,60}?)6\.50?\s*%',
        re.IGNORECASE
    )
    new, c3 = pattern3.subn(r'\g<1>5.25%', new)
    n += c3
    return new, n


# ── Pass-2 fix: Gold Tariff table cells (no % sign in cell value) ─────────────
GOLD_TARIFF_TABLE_FIXES = [
    # Table cells for Gold Import Tariff: previous rate "7.5" → "6"
    (r'(<td>Gold Import Tariff</td>\s*<td>)7\.5(</td>)',   r'\g<1>6\g<2>'),
    (r'(<td>Silver Import Tariff</td>\s*<td>)7\.5(</td>)', r'\g<1>6\g<2>'),
]


def fix_gold_tariff_v2(html: str) -> Tuple[str, int]:
    n = 0
    for pat, repl in GOLD_TARIFF_TABLE_FIXES:
        html, c = re.subn(pat, repl, html, flags=re.IGNORECASE)
        n += c
    return html, n


def correct_post(post_id: int, label: str) -> Dict:
    print(f"\n--- Post {post_id}: {label} ---")
    r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                     headers={"Authorization": HEADERS["Authorization"]},
                     timeout=20)
    if r.status_code != 200:
        print(f"  fetch failed: HTTP {r.status_code}")
        return {"id": post_id, "ok": False}
    post = r.json()
    original = post["content"]["rendered"]
    new = original
    changes = {}

    if post_id in (2493, 2438):
        new, n = strip_markdown_v2(new)
        if n: changes["markdown_v2"] = n; print(f"  markdown artifact stripped: {n}")

    if post_id == 2442:
        new, n = fix_gold_tariff_v2(new)
        if n: changes["gold_table"] = n; print(f"  gold tariff table cells fixed: {n}")

    new, n = fix_repo_rate_v2(new)
    if n: changes["repo_rate_v2"] = n; print(f"  repo rate fixes: {n}")

    if new == original:
        print(f"  no changes")
        return {"id": post_id, "ok": True, "updated": False}

    r2 = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        data=json.dumps({"content": new}, ensure_ascii=False).encode("utf-8"),
        timeout=30,
    )
    if r2.status_code in (200, 201):
        print(f"  updated  ({len(new) - len(original):+d} chars)")
        return {"id": post_id, "ok": True, "updated": True, "changes": changes}
    print(f"  update failed: HTTP {r2.status_code}")
    return {"id": post_id, "ok": False}


def main():
    posts = {
        2493: "Pharma Stocks (markdown bug)",
        2438: "Gen Z (markdown bug)",
        2442: "Gold Tariffs (table 7.5→6)",
        2492: "India Economic Growth (repo rate)",
        2494: "Nifty Drop (repo rate)",
        # also retry the rest to catch any "steady at" / "held at" variants
        2444: "Texmaco (repo rate variants)",
        2495: "Cochin (repo rate variants)",
        2428: "Ather/Ola (repo rate variants)",
        2485: "Rupee (repo rate variants)",
        2490: "US-Iran Oil (repo rate variants)",
    }
    for pid, label in posts.items():
        try:
            correct_post(pid, label)
        except Exception as e:
            print(f"  EXCEPTION on {pid}: {e}")


if __name__ == "__main__":
    main()
