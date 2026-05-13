"""
SEO Scorer — per-article quality score (0-100).

Evaluates:
  1.  Word count                  (20 pts)  — 2500+ words target
  2.  Heading structure           (10 pts)  — H1, H2/H3 presence
  3.  Keyword density             (10 pts)  — 0.5-2% focus keyword
  4.  Internal links              (15 pts)  — target 5+ links
  5.  FAQ section                 (10 pts)  — boosts rich snippet chances
  6.  Meta description            (10 pts)  — 120-160 chars
  7.  Readability                 (10 pts)  — avg sentence length
  8.  Schema markup               ( 5 pts)  — structured data present
  9.  Image alt text              ( 5 pts)  — at least 1 image with alt
  10. Content freshness           ( 5 pts)  — published/updated recency

Each article gets a score 0-100 and a grade:
  90-100: A+  (exceptional)
  80-89:  A   (strong)
  70-79:  B+  (good)
  60-69:  B   (acceptable)
  50-59:  C   (needs work)
  <50:    D   (critical issues)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger("seo.scorer")

STATE_DIR       = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
SCORES_FILE     = STATE_DIR / "seo_scores.json"


# ── Persistence ───────────────────────────────────────────────────────────────

def load_scores() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not SCORES_FILE.exists():
        return {}
    try:
        return json.loads(SCORES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_scores(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SCORES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Individual checks ─────────────────────────────────────────────────────────

def _score_word_count(html: str) -> tuple[int, dict]:
    """Max 20 pts. Target 2500+ words."""
    text  = re.sub(r"<[^>]+>", " ", html)
    count = len(text.split())
    if count >= 3000:   pts, note = 20, "excellent"
    elif count >= 2500: pts, note = 17, "good"
    elif count >= 1500: pts, note = 12, "acceptable"
    elif count >= 800:  pts, note = 7,  "short"
    else:               pts, note = 2,  "very short"
    return pts, {"word_count": count, "note": note, "max": 20}


def _score_headings(html: str) -> tuple[int, dict]:
    """Max 10 pts."""
    h1s = re.findall(r"<h1[^>]*>", html, re.IGNORECASE)
    h2s = re.findall(r"<h2[^>]*>", html, re.IGNORECASE)
    h3s = re.findall(r"<h3[^>]*>", html, re.IGNORECASE)
    pts = 0
    # H2/H3 structure (most important)
    if len(h2s) >= 5:   pts += 6
    elif len(h2s) >= 3: pts += 4
    elif len(h2s) >= 1: pts += 2
    if len(h3s) >= 3:   pts += 2
    elif len(h3s) >= 1: pts += 1
    if len(h1s) == 0:   pts += 2  # No H1 in body (good — title is H1)
    return pts, {"h1": len(h1s), "h2": len(h2s), "h3": len(h3s), "max": 10}


def _score_keyword_density(html: str, focus_keyword: str) -> tuple[int, dict]:
    """Max 10 pts. Target 0.5-2% density."""
    if not focus_keyword:
        return 5, {"density_pct": 0, "note": "no_focus_kw", "max": 10}

    text   = re.sub(r"<[^>]+>", " ", html).lower()
    words  = text.split()
    n_words = len(words)
    if n_words == 0:
        return 0, {"density_pct": 0, "note": "empty", "max": 10}

    pattern = re.compile(re.escape(focus_keyword.lower()))
    count   = len(pattern.findall(text))
    density = (count / n_words) * 100

    if 0.5 <= density <= 2.0:   pts, note = 10, "optimal"
    elif 0.3 <= density < 0.5:  pts, note = 7,  "slightly_low"
    elif 2.0 < density <= 3.0:  pts, note = 6,  "slightly_high"
    elif density > 3.0:          pts, note = 2,  "keyword_stuffing"
    else:                        pts, note = 3,  "too_low"

    return pts, {"density_pct": round(density, 2), "count": count, "note": note, "max": 10}


def _score_internal_links(html: str, site_domain: str = "cadialogue.in") -> tuple[int, dict]:
    """Max 15 pts. Target 5+ internal links."""
    links = re.findall(
        rf'href=["\']https?://{re.escape(site_domain)}[^\s"\']*["\']',
        html, re.IGNORECASE
    )
    # Also count relative links
    rel_links = re.findall(r'href=["\'](?!http|#|mailto)[^\s"\']+["\']', html)
    total = len(links) + len(rel_links)

    if total >= 30:   pts, note = 15, "excellent"
    elif total >= 15: pts, note = 12, "good"
    elif total >= 8:  pts, note = 8,  "acceptable"
    elif total >= 3:  pts, note = 4,  "low"
    else:             pts, note = 1,  "very_low"

    return pts, {"count": total, "note": note, "max": 15}


def _score_faq(html: str) -> tuple[int, dict]:
    """Max 10 pts. FAQ section boosts rich snippets."""
    has_faq_heading = bool(re.search(r"<h[23][^>]*>[^<]*(?:faq|frequently asked|questions)[^<]*</h[23]>", html, re.IGNORECASE))
    has_faq_schema  = bool(re.search(r'"@type"\s*:\s*"FAQPage"', html, re.IGNORECASE))
    q_count         = len(re.findall(r"<h[34][^>]*>[^<]*\?</h[34]>", html))  # headings ending with ?

    pts = 0
    if has_faq_heading or q_count >= 3: pts += 5
    if has_faq_schema:                  pts += 3
    if q_count >= 5:                    pts += 2
    elif q_count >= 3:                  pts += 1

    return pts, {"has_faq": has_faq_heading, "has_schema": has_faq_schema, "q_count": q_count, "max": 10}


def _score_meta_description(meta_desc: str) -> tuple[int, dict]:
    """Max 10 pts. Target 120-160 chars."""
    if not meta_desc:
        return 0, {"length": 0, "note": "missing", "max": 10}
    length = len(meta_desc)
    if 120 <= length <= 160:  pts, note = 10, "optimal"
    elif 100 <= length < 120: pts, note = 7,  "slightly_short"
    elif 160 < length <= 180: pts, note = 7,  "slightly_long"
    elif length >= 50:         pts, note = 4,  "needs_work"
    else:                      pts, note = 1,  "too_short"
    return pts, {"length": length, "note": note, "max": 10}


def _score_readability(html: str) -> tuple[int, dict]:
    """Max 10 pts. Based on average sentence length."""
    text = re.sub(r"<[^>]+>", " ", html)
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip().split()) > 2]
    if not sentences:
        return 5, {"avg_sentence_len": 0, "max": 10}

    avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
    if 12 <= avg_len <= 20:  pts, note = 10, "optimal"
    elif 8 <= avg_len < 12:  pts, note = 8,  "concise"
    elif 20 < avg_len <= 28: pts, note = 7,  "long"
    elif avg_len > 28:        pts, note = 4,  "very_long"
    else:                     pts, note = 6,  "too_short"
    return pts, {"avg_sentence_len": round(avg_len, 1), "note": note, "max": 10}


def _score_schema(html: str) -> tuple[int, dict]:
    """Max 5 pts."""
    has_article  = bool(re.search(r'"@type"\s*:\s*"(?:Article|NewsArticle)"', html, re.IGNORECASE))
    has_faqpage  = bool(re.search(r'"@type"\s*:\s*"FAQPage"', html, re.IGNORECASE))
    has_breadcrumb = bool(re.search(r'"@type"\s*:\s*"BreadcrumbList"', html, re.IGNORECASE))
    pts = 0
    if has_article:   pts += 2
    if has_faqpage:   pts += 2
    if has_breadcrumb: pts += 1
    return pts, {"article": has_article, "faq": has_faqpage, "breadcrumb": has_breadcrumb, "max": 5}


def _score_images(html: str) -> tuple[int, dict]:
    """Max 5 pts. At least 1 image with alt text."""
    all_imgs  = re.findall(r"<img[^>]+>", html, re.IGNORECASE)
    alt_imgs  = [img for img in all_imgs if re.search(r'alt=["\'][^"\']+["\']', img)]
    pts = 0
    if len(alt_imgs) >= 3:  pts = 5
    elif len(alt_imgs) >= 1: pts = 3
    elif len(all_imgs) > 0:  pts = 1
    return pts, {"total_images": len(all_imgs), "images_with_alt": len(alt_imgs), "max": 5}


def _score_freshness(published_at: str | None, updated_at: str | None) -> tuple[int, dict]:
    """Max 5 pts. Recently updated content ranks better."""
    import dateutil.parser
    pts    = 3   # default: moderate
    note   = "unknown"
    age_days = None

    check_date = updated_at or published_at
    if check_date:
        try:
            dt       = dateutil.parser.parse(check_date)
            now      = time.time()
            age_secs = now - dt.timestamp()
            age_days = int(age_secs / 86400)

            if age_days <= 30:   pts, note = 5, "fresh"
            elif age_days <= 90: pts, note = 4, "recent"
            elif age_days <= 180: pts, note = 3, "moderate"
            elif age_days <= 365: pts, note = 2, "aging"
            else:                pts, note = 1, "stale"
        except Exception:
            pass

    return pts, {"age_days": age_days, "note": note, "max": 5}


# ── Main scoring ──────────────────────────────────────────────────────────────

def score_article(
    post: dict,
    focus_keyword: str = "",
    site_domain: str = "cadialogue.in",
) -> dict:
    """
    Score a single WordPress post and return full breakdown.

    post: WP REST API post dict (needs 'content.rendered', 'excerpt.rendered', 'date', 'modified')

    Returns:
    {
      "post_id": int,
      "title": str,
      "total_score": int,
      "grade": str,
      "checks": { check_name: {pts, ...details} },
      "issues": [str],         # actionable improvement hints
      "scored_at": float,
    }
    """
    html         = post.get("content", {}).get("rendered", "")
    meta         = post.get("meta") or {}
    meta_desc    = (
        meta.get("rank_math_description")
        or meta.get("_yoast_wpseo_metadesc")
        or post.get("excerpt", {}).get("rendered", "")
    )
    meta_desc    = re.sub(r"<[^>]+>", "", meta_desc)[:200]
    fk           = focus_keyword or meta.get("rank_math_focus_keyword", "")

    # Run all checks
    wc_pts,  wc_det    = _score_word_count(html)
    h_pts,   h_det     = _score_headings(html)
    kd_pts,  kd_det    = _score_keyword_density(html, fk)
    il_pts,  il_det    = _score_internal_links(html, site_domain)
    fq_pts,  fq_det    = _score_faq(html)
    md_pts,  md_det    = _score_meta_description(meta_desc)
    rb_pts,  rb_det    = _score_readability(html)
    sc_pts,  sc_det    = _score_schema(html)
    img_pts, img_det   = _score_images(html)
    fr_pts,  fr_det    = _score_freshness(post.get("date"), post.get("modified"))

    total = wc_pts + h_pts + kd_pts + il_pts + fq_pts + md_pts + rb_pts + sc_pts + img_pts + fr_pts

    # Grade
    if total >= 90:   grade = "A+"
    elif total >= 80: grade = "A"
    elif total >= 70: grade = "B+"
    elif total >= 60: grade = "B"
    elif total >= 50: grade = "C"
    else:             grade = "D"

    # Actionable issues
    issues: list[str] = []
    if wc_det["word_count"] < 1500:
        issues.append(f"Article too short ({wc_det['word_count']} words) — target 2500+")
    if il_det["count"] < 5:
        issues.append(f"Only {il_det['count']} internal links — run linking engine")
    if not fq_det["has_faq"]:
        issues.append("Add FAQ section with 5+ questions for rich snippets")
    if md_det["length"] == 0:
        issues.append("Missing meta description — set in RankMath")
    if h_det["h2"] < 3:
        issues.append(f"Only {h_det['h2']} H2 headings — add more structure")
    if kd_det.get("note") == "keyword_stuffing":
        issues.append("Keyword density too high — risk of over-optimisation penalty")
    if img_det["images_with_alt"] == 0 and img_det["total_images"] > 0:
        issues.append("Images missing alt text — add descriptive alt attributes")
    if fr_det["note"] in ("aging", "stale"):
        issues.append(f"Article is {fr_det['age_days']} days old — consider refreshing")

    record = {
        "post_id":     post.get("id"),
        "title":       re.sub(r"<[^>]+>", "", post.get("title", {}).get("rendered", "")),
        "url":         post.get("link", ""),
        "total_score": total,
        "grade":       grade,
        "checks": {
            "word_count":       {**wc_det,  "pts": wc_pts},
            "headings":         {**h_det,   "pts": h_pts},
            "keyword_density":  {**kd_det,  "pts": kd_pts},
            "internal_links":   {**il_det,  "pts": il_pts},
            "faq_section":      {**fq_det,  "pts": fq_pts},
            "meta_description": {**md_det,  "pts": md_pts},
            "readability":      {**rb_det,  "pts": rb_pts},
            "schema_markup":    {**sc_det,  "pts": sc_pts},
            "image_alt_text":   {**img_det, "pts": img_pts},
            "content_freshness":{**fr_det,  "pts": fr_pts},
        },
        "issues":      issues,
        "scored_at":   time.time(),
    }

    # Persist
    scores = load_scores()
    scores[str(post.get("id", "0"))] = record
    save_scores(scores)

    return record


def score_all_articles(all_posts: list[dict], site_domain: str = "cadialogue.in") -> dict:
    """Score every article and return aggregate stats."""
    results  = [score_article(p, site_domain=site_domain) for p in all_posts]
    scores   = [r["total_score"] for r in results]
    avg      = round(sum(scores) / len(scores), 1) if scores else 0

    return {
        "articles_scored": len(results),
        "average_score":   avg,
        "grade_dist":      {
            "A+": sum(1 for r in results if r["grade"] == "A+"),
            "A":  sum(1 for r in results if r["grade"] == "A"),
            "B+": sum(1 for r in results if r["grade"] == "B+"),
            "B":  sum(1 for r in results if r["grade"] == "B"),
            "C":  sum(1 for r in results if r["grade"] == "C"),
            "D":  sum(1 for r in results if r["grade"] == "D"),
        },
        "needs_update":    [r for r in results if r["total_score"] < 60],
        "top_articles":    sorted(results, key=lambda x: x["total_score"], reverse=True)[:5],
    }
