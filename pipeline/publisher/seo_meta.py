"""
SEO meta field builders for Yoast and RankMath.
Yoast requires PHP snippet in functions.php to expose fields via REST API.
RankMath exposes fields natively — no extra setup.
"""
from ..config import Config
from ..writer.article_generator import SEOMeta


# ── Yoast SEO field names (REST API meta keys) ─────────────────────────────────
YOAST_FIELD_MAP = {
    "focus_keyword":      "_yoast_wpseo_focuskw",
    "meta_description":   "_yoast_wpseo_metadesc",
    "title":              "_yoast_wpseo_title",
    "canonical_url":      "_yoast_wpseo_canonical",
    "og_title":           "_yoast_wpseo_opengraph-title",
    "og_description":     "_yoast_wpseo_opengraph-description",
    "twitter_title":      "_yoast_wpseo_twitter-title",
    "twitter_description":"_yoast_wpseo_twitter-description",
}

# ── RankMath field names (auto-registered, no PHP needed) ──────────────────────
RANKMATH_FIELD_MAP = {
    "focus_keyword":      "rank_math_focus_keyword",
    "meta_description":   "rank_math_description",
    "title":              "rank_math_title",
    "canonical_url":      "rank_math_canonical_url",
    "og_title":           "rank_math_og_title",
    "og_description":     "rank_math_og_description",
    "twitter_title":      "rank_math_twitter_title",
    "twitter_description":"rank_math_twitter_description",
}


def build_wp_meta(seo_meta: SEOMeta, config: Config, post_url: str = "") -> dict:
    """
    Build the `meta` dict for the WordPress REST API post payload.
    Selects Yoast or RankMath fields based on config.wp_seo_plugin.
    """
    field_map = (
        RANKMATH_FIELD_MAP if config.wp_seo_plugin == "rankmath"
        else YOAST_FIELD_MAP
    )

    values = {
        "focus_keyword":       seo_meta.focus_keyword,
        "meta_description":    seo_meta.meta_description,
        "title":               seo_meta.title,
        "og_title":            seo_meta.og_title,
        "og_description":      seo_meta.og_description,
        "twitter_title":       seo_meta.og_title,
        "twitter_description": seo_meta.og_description,
    }
    if post_url:
        values["canonical_url"] = post_url

    return {field_map[k]: v for k, v in values.items() if k in field_map}
