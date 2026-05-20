#!/usr/bin/env python3
"""
Comprehensive fact-check corrections for cadialogue.in articles.

Fixes:
  1. RBI repo rate: 6.5% → 5.25% (global, all affected articles)
  2. Strip raw ```markdown / ``` artifacts visible in published posts
  3. Cochin Shipyard (2495)   — fabricated Q4 FY26 financials
  4. Texmaco Rail (2444)      — fabricated Q4 FY26 financials
  5. Ather/Ola/JBM (2428)     — fabricated stock prices and % gains
  6. Rupee Crash (2485)       — wrong trade deficit figure
  7. Gold Tariffs (2442)      — wrong "previous rate" (7.5% → 6%)
  8. US-Iran Oil (2490)       — outdated Brent price ($106 → $109.69)

All real financial figures sourced from BSE/NSE Q4 FY26 filings,
Economic Times, Business Standard, NDTV Profit, official RBI press releases.
"""
import os
import re
import sys
import json
import base64
import requests
from typing import Dict, List, Tuple

WP_URL  = "https://cadialogue.in"
WP_USER = "renuka.malik99@gmail.com"
WP_PASS = "BbaZ j5Za FELD 6wfg mUtb 517z"

_creds = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
HEADERS = {
    "Authorization": f"Basic {_creds}",
    "Content-Type":  "application/json; charset=utf-8",
}

# ── Articles needing correction ──────────────────────────────────────────────
AFFECTED_POSTS = {
    2495: "Cochin Shipyard",
    2494: "Nifty Drop",
    2493: "Pharma Stocks",
    2492: "India Economic Growth",
    2490: "US-Iran Oil",
    2485: "Rupee Crash",
    2444: "Texmaco Rail",
    2443: "Nifty Futures",
    2442: "Gold Tariffs",
    2438: "Gen Z Investors",
    2428: "Ather/Ola Electric",
    2495: "Cochin Shipyard",
}

# Posts with the ```markdown artifact (need stripping)
MARKDOWN_BUG_POSTS = [2493, 2438]


# ── Fix 1: Strip raw markdown code-fence artifacts ───────────────────────────
def strip_markdown_artifacts(html: str) -> Tuple[str, int]:
    """Remove visible ```markdown / ``` fence markers leaked into HTML."""
    n = 0
    # Pattern 1: <p>```markdown</p> or similar wrapping
    new = re.sub(r"<p>\s*`{3,}\s*markdown\s*</p>", "", html, flags=re.IGNORECASE)
    n += html.count("```markdown") + html.count("``` markdown")
    # Pattern 2: raw ``` on its own line/paragraph
    new = re.sub(r"<p>\s*`{3,}\s*</p>", "", new)
    # Pattern 3: bare ```markdown text (no wrapping)
    new = re.sub(r"`{3,}\s*markdown", "", new, flags=re.IGNORECASE)
    new = re.sub(r"^\s*`{3,}\s*$", "", new, flags=re.MULTILINE)
    # Pattern 4: backticks at start of content
    new = re.sub(r"^\s*`+\s*(?=\w)", "", new)
    return new, n


# ── Fix 2: RBI repo rate (6.5% → 5.25%) ──────────────────────────────────────
RBI_RATE_PATTERNS = [
    # Common phrasings
    (r"\brepo\s+rate\s+(?:at|of|is|to|currently\s+at|stands?\s+at)?\s*6\.50?%", lambda m: m.group(0).replace("6.5%", "5.25%").replace("6.50%", "5.25%")),
    (r"\brepo\s+rate\s+(?:at|of)?\s*6\.50?\s*per\s*cent", lambda m: m.group(0).replace("6.5", "5.25").replace("6.50", "5.25")),
    (r"\bRBI[^.<]{0,40}6\.50?\s*%", lambda m: m.group(0).replace("6.5%", "5.25%").replace("6.50%", "5.25%")),
    # Specific repo rate references
    (r"\b6\.50?%\s+repo\s+rate", "5.25% repo rate"),
    (r"\brepo\s+rate\s+stands\s+at\s+6\.50?%", "repo rate stands at 5.25%"),
    (r"\bcurrent\s+repo\s+rate\s+of\s+6\.50?%", "current repo rate of 5.25%"),
    (r"\bbenchmark\s+repo\s+rate\s+(?:of\s+|at\s+)?6\.50?%", "benchmark repo rate of 5.25%"),
]

def fix_repo_rate(html: str) -> Tuple[str, int]:
    """Replace 6.5% RBI repo rate references with the correct 5.25%."""
    n = 0
    for pat, repl in RBI_RATE_PATTERNS:
        if callable(repl):
            html, count = re.subn(pat, repl, html, flags=re.IGNORECASE)
        else:
            html, count = re.subn(pat, repl, html, flags=re.IGNORECASE)
        n += count
    return html, n


# ── Fix 3: Article-specific financial corrections ────────────────────────────
ARTICLE_FIXES: Dict[int, List[Tuple[str, str]]] = {
    # ── Cochin Shipyard (2495) — real Q4 FY26 figures from BSE filing ────
    2495: [
        # Net profit corrections — all variations
        ("12.8% to ₹45.2 crore",        "3.7% to ₹276.48 crore"),
        ("12.8% to Rs 45.2 crore",      "3.7% to Rs 276.48 crore"),
        ("12.8% to &#8377;45.2 crore",  "3.7% to &#8377;276.48 crore"),
        ("₹45.2 crore from ₹51.8 crore",       "₹276.48 crore from ₹287.19 crore"),
        ("Rs 45.2 crore from Rs 51.8 crore",   "Rs 276.48 crore from Rs 287.19 crore"),
        ("&#8377;45.2 crore from &#8377;51.8 crore", "&#8377;276.48 crore from &#8377;287.19 crore"),
        ("₹45.2 crore",         "₹276.48 crore"),
        ("Rs 45.2 crore",       "Rs 276.48 crore"),
        ("&#8377;45.2 crore",   "&#8377;276.48 crore"),
        ("₹51.8 crore",         "₹287.19 crore"),
        ("Rs 51.8 crore",       "Rs 287.19 crore"),
        ("&#8377;51.8 crore",   "&#8377;287.19 crore"),
        # Revenue corrections
        ("9.6% to ₹642.7 crore",        "15.6% to ₹1,484 crore"),
        ("9.6% to Rs 642.7 crore",      "15.6% to Rs 1,484 crore"),
        ("9.6% to &#8377;642.7 crore",  "15.6% to &#8377;1,484 crore"),
        ("₹642.7 crore from ₹710.9 crore",     "₹1,484 crore from ₹1,757.7 crore"),
        ("Rs 642.7 crore from Rs 710.9 crore", "Rs 1,484 crore from Rs 1,757.7 crore"),
        ("&#8377;642.7 crore from &#8377;710.9 crore", "&#8377;1,484 crore from &#8377;1,757.7 crore"),
        ("₹642.7 crore",        "₹1,484 crore"),
        ("Rs 642.7 crore",      "Rs 1,484 crore"),
        ("&#8377;642.7 crore",  "&#8377;1,484 crore"),
        ("₹710.9 crore",        "₹1,757.7 crore"),
        ("Rs 710.9 crore",      "Rs 1,757.7 crore"),
        ("&#8377;710.9 crore",  "&#8377;1,757.7 crore"),
        # Margin corrections
        ("18.5% from 15.2%",   "20.9% from 15.1%"),
        ("margin increased to 18.5%",   "margin increased to 20.9%"),
        ("margin to 18.5%",             "margin to 20.9%"),
        ("Operational Margin: 18.5%",   "EBITDA Margin: 20.9%"),
    ],

    # ── Texmaco Rail (2444) — real Q4 FY26 figures from BSE filing ────────
    2444: [
        # Revenue (article wrongly says UP 18%, actually DOWN 13%)
        ("up 18% from ₹2,372 crore to ₹2,800 crore",      "down 13% from ₹1,346 crore to ₹1,167 crore"),
        ("up 18% from Rs 2,372 crore to Rs 2,800 crore",  "down 13% from Rs 1,346 crore to Rs 1,167 crore"),
        ("₹2,800 crore (up 18%",      "₹1,167 crore (down 13%"),
        ("Rs 2,800 crore (up 18%",    "Rs 1,167 crore (down 13%"),
        ("₹2,800 crore",      "₹1,167 crore"),
        ("Rs 2,800 crore",    "Rs 1,167 crore"),
        ("&#8377;2,800 crore","&#8377;1,167 crore"),
        ("₹2,372 crore",      "₹1,346 crore"),
        ("Rs 2,372 crore",    "Rs 1,346 crore"),
        ("&#8377;2,372 crore","&#8377;1,346 crore"),
        # Net profit
        ("up 18.23% from ₹203 crore to ₹240 crore",        "up 45% from ₹39.8 crore to ₹57.68 crore"),
        ("up 18.23% from Rs 203 crore to Rs 240 crore",    "up 45% from Rs 39.8 crore to Rs 57.68 crore"),
        ("₹240 crore (up 18.23%",     "₹57.68 crore (up 45%"),
        ("Rs 240 crore (up 18.23%",   "Rs 57.68 crore (up 45%"),
        ("18.23%",            "45%"),
        ("₹240 crore",        "₹57.68 crore"),
        ("Rs 240 crore",      "Rs 57.68 crore"),
        ("&#8377;240 crore",  "&#8377;57.68 crore"),
        ("₹203 crore",        "₹39.8 crore"),
        ("Rs 203 crore",      "Rs 39.8 crore"),
        ("&#8377;203 crore",  "&#8377;39.8 crore"),
        # EBITDA Margin
        ("EBITDA Margin: 22%",      "EBITDA Margin: 10.0%"),
        ("EBITDA margin of 22%",    "EBITDA margin of 10.0%"),
        ("EBITDA margin at 22%",    "EBITDA margin at 10.0%"),
        ("margin expanded to 22%",  "margin expanded to 10.0% (from 8.8%)"),
        ("22% EBITDA margin",       "10.0% EBITDA margin"),
    ],

    # ── Ather/Ola/JBM (2428) — real stock prices from NSE on PM Modi push day ─
    2428: [
        # Ather (real: rose 6-8% to ~₹963-989, not 12% to ₹486)
        ("climbed 12% to reach ₹486",      "climbed 8.1% to reach ₹989"),
        ("climbed 12% to reach Rs 486",    "climbed 8.1% to reach Rs 989"),
        ("Ather Energy climbed 12%",       "Ather Energy climbed 8.1%"),
        ("Ather Energy rose 12%",          "Ather Energy rose 8.1%"),
        ("₹486",   "₹989"),
        ("Rs 486", "Rs 989"),
        ("&#8377;486", "&#8377;989"),
        # Ola Electric (real: rose ~2.72-3.02% to ~₹37, not 10.5% to ₹410)
        ("rose 10.5% to ₹410",       "rose 3.02% to ₹37.05"),
        ("rose 10.5% to Rs 410",     "rose 3.02% to Rs 37.05"),
        ("Ola Electric rose 10.5%",  "Ola Electric rose 3.02%"),
        ("Ola Electric climbed 10.5%","Ola Electric climbed 3.02%"),
        ("10.5%", "3.02%"),
        ("₹410",  "₹37.05"),
        ("Rs 410","Rs 37.05"),
        ("&#8377;410", "&#8377;37.05"),
        # JBM Auto (real: rose 4.45-5.25% to ~₹678-684, not 9.3% to ₹842)
        ("rose 9.3% to ₹842",       "rose 5.25% to ₹684"),
        ("rose 9.3% to Rs 842",     "rose 5.25% to Rs 684"),
        ("JBM Auto rose 9.3%",      "JBM Auto rose 5.25%"),
        ("JBM Auto climbed 9.3%",   "JBM Auto climbed 5.25%"),
        ("9.3%", "5.25%"),
        ("₹842",  "₹684"),
        ("Rs 842","Rs 684"),
        ("&#8377;842", "&#8377;684"),
    ],

    # ── Rupee Crash (2485) — corrected trade deficit ──────────────────────────
    2485: [
        ("Trade Deficit: $212 billion",      "Trade Deficit: $333.19 billion (FY26 merchandise)"),
        ("trade deficit of $212 billion",    "merchandise trade deficit of $333.19 billion"),
        ("trade deficit of USD 212 billion", "merchandise trade deficit of USD 333.19 billion"),
        ("$212 billion",                     "$333.19 billion"),
        ("USD 212 billion",                  "USD 333.19 billion"),
        # Oil import volume (4.5 → 4.25 mb/d)
        ("4.5 million barrels/day",   "4.25 million barrels/day"),
        ("4.5 million barrels per day","4.25 million barrels per day"),
        ("4.5 mb/d",                  "4.25 mb/d"),
    ],

    # ── Gold Tariffs (2442) — corrected previous rate (7.5% → 6%) ──────────
    2442: [
        ("Previous Rate: 7.5%",       "Previous Rate: 6%"),
        ("previous rate of 7.5%",     "previous rate of 6%"),
        ("previous tariff of 7.5%",   "previous tariff of 6%"),
        ("earlier rate of 7.5%",      "earlier rate of 6%"),
        ("from 7.5% to 15%",          "from 6% (5% BCD + 1% AIDC) to 15%"),
        ("up from 7.5%",              "up from 6%"),
        ("hiked from 7.5%",           "hiked from 6%"),
        ("doubled from 7.5%",         "more than doubled from 6%"),
    ],

    # ── US-Iran Oil (2490) — updated Brent price ──────────────────────────────
    2490: [
        ("Brent Crude currently at ~$106",  "Brent Crude currently at ~$109.69"),
        ("Brent Crude at ~$106",            "Brent Crude at ~$109.69"),
        ("Brent at ~$106",                  "Brent at ~$109.69"),
        ("$106/barrel",                     "$109.69/barrel"),
        ("$106 per barrel",                 "$109.69 per barrel"),
        ("$106 a barrel",                   "$109.69 a barrel"),
    ],
}


# ── Master correction routine ────────────────────────────────────────────────
def correct_post(post_id: int, label: str) -> Dict:
    """Fetch a post, apply all relevant corrections, push back if changed."""
    print(f"\n┌─── Post {post_id}: {label} ────────────────────")
    r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                     headers={"Authorization": HEADERS["Authorization"]},
                     timeout=20)
    if r.status_code != 200:
        print(f"│ ✗ Fetch failed: HTTP {r.status_code}")
        return {"id": post_id, "ok": False, "error": "fetch_failed"}
    post = r.json()
    original = post["content"]["rendered"]
    new = original
    stats = {"id": post_id, "label": label, "changes": {}}

    # 1. Strip markdown artifacts (only on posts that have them)
    if post_id in MARKDOWN_BUG_POSTS or "```markdown" in new or "``` markdown" in new:
        new, n_md = strip_markdown_artifacts(new)
        stats["changes"]["markdown_artifacts"] = n_md
        print(f"│ ✎ Stripped markdown artifacts: {n_md}")

    # 2. Fix RBI repo rate
    new, n_rate = fix_repo_rate(new)
    if n_rate > 0:
        stats["changes"]["repo_rate"] = n_rate
        print(f"│ ✎ Repo rate fixes (6.5% → 5.25%): {n_rate}")

    # 3. Apply article-specific fixes
    fixes = ARTICLE_FIXES.get(post_id, [])
    if fixes:
        total_specific = 0
        for old, repl in fixes:
            cnt = new.count(old)
            if cnt > 0:
                new = new.replace(old, repl)
                total_specific += cnt
        if total_specific > 0:
            stats["changes"]["specific"] = total_specific
            print(f"│ ✎ Article-specific data fixes: {total_specific}")

    # 4. Diff check
    if new == original:
        print(f"│ • No changes needed")
        stats["ok"] = True
        stats["updated"] = False
        return stats

    # 5. Push back to WordPress
    payload = {"content": new}
    r2 = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=30,
    )
    if r2.status_code in (200, 201):
        diff_chars = len(new) - len(original)
        print(f"│ ✓ Updated  ({diff_chars:+d} chars)")
        stats["ok"] = True
        stats["updated"] = True
        stats["link"] = r2.json().get("link", "")
    else:
        print(f"│ ✗ Update failed: HTTP {r2.status_code} — {r2.text[:200]}")
        stats["ok"] = False
        stats["error"] = f"http_{r2.status_code}"
    return stats


def main():
    print("=" * 68)
    print("  CADialogue Fact-Check Correction Run")
    print(f"  Target: {len(AFFECTED_POSTS)} posts")
    print("=" * 68)

    results = []
    # Always include the full list of affected post IDs
    for post_id in sorted(set(AFFECTED_POSTS.keys())):
        label = AFFECTED_POSTS[post_id]
        try:
            results.append(correct_post(post_id, label))
        except Exception as e:
            print(f"│ ✗ EXCEPTION: {e}")
            results.append({"id": post_id, "ok": False, "error": str(e)})

    print("\n" + "=" * 68)
    print("  SUMMARY")
    print("=" * 68)
    updated  = [r for r in results if r.get("updated")]
    skipped  = [r for r in results if r.get("ok") and not r.get("updated")]
    failed   = [r for r in results if not r.get("ok")]
    print(f"  Updated:  {len(updated)}")
    print(f"  No-op:    {len(skipped)}")
    print(f"  Failed:   {len(failed)}")
    if failed:
        for f in failed:
            print(f"    - {f['id']}: {f.get('error')}")
    print(f"\n  Detailed log: {len(results)} posts processed")


if __name__ == "__main__":
    main()
