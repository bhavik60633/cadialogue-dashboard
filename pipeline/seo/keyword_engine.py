"""
Keyword Research Engine — discover, cluster, and score keywords.

Data sources (all FREE or already paid):
  1. Google Autocomplete API  — suggestions for seed keywords
  2. NewsAPI                  — trending finance topics (already integrated)
  3. DuckDuckGo Instant API   — related searches, zero-click data
  4. "People Also Ask" scrape — question-format keywords

Clustering algorithm:
  - Generate embeddings for all keywords
  - Group by cosine similarity > 0.75 (tight semantic clusters)
  - Label each cluster with GPT-4o-mini

Scoring:
  - Estimated competition: proxied by Google Autocomplete depth
  - Intent classification: informational / transactional / comparison / navigational
  - Topical relevance score: cosine sim with cadialogue.in topic space
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Literal

import requests

from ..config import Config
from ..utils.json_utils import gemini_json_call
from ..utils.logger import get_logger
from .embeddings_store import embed_text, _cosine_similarity

logger = get_logger("seo.keyword_engine")

STATE_DIR      = Path(__file__).resolve().parents[2] / "pipeline" / "state" / "seo"
KW_STORE_FILE  = STATE_DIR / "keyword_clusters.json"

# Finance seeds for cadialogue.in — expanded over time
INDIA_FINANCE_SEEDS = [
    "Nifty 50", "Sensex today", "RBI rate", "SEBI news", "gold price India",
    "SIP mutual fund", "income tax India", "GST rate", "IPO India",
    "personal finance India", "stock market crash", "FD interest rate",
    "inflation India", "rupee dollar", "NSE BSE", "CA exam", "ICAI",
    "real estate India", "crypto India", "budget 2025 India",
    "bank NPA", "UPI payment", "LIC policy", "NPS pension",
    "small cap stocks", "dividend stocks India", "demat account",
]

IntentType = Literal["informational", "transactional", "comparison", "navigational", "question"]


# ── Storage ───────────────────────────────────────────────────────────────────

def load_kw_store() -> dict:
    """
    Load keyword database.
    Schema: {
      "clusters": [{
        "cluster_id": str,
        "label": str,
        "head_keyword": str,
        "keywords": [{kw, volume_est, difficulty, intent, added_at}, ...],
        "embedding": [float],
      }],
      "unclustered": [{kw, volume_est, difficulty, intent, added_at}],
      "last_discovery": float,
    }
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not KW_STORE_FILE.exists():
        return {"clusters": [], "unclustered": [], "last_discovery": 0}
    try:
        return json.loads(KW_STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"clusters": [], "unclustered": [], "last_discovery": 0}


def save_kw_store(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    KW_STORE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Data fetching ─────────────────────────────────────────────────────────────

def _google_autocomplete(seed: str, lang: str = "en", country: str = "in") -> list[str]:
    """
    Fetch Google Autocomplete suggestions for a seed keyword.
    Free — no API key required.
    Returns up to 10 suggestions.
    """
    try:
        url    = "https://suggestqueries.google.com/complete/search"
        params = {"client": "firefox", "q": seed, "hl": lang, "gl": country}
        resp   = requests.get(url, params=params, timeout=8,
                              headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            data = resp.json()
            return data[1] if isinstance(data, list) and len(data) > 1 else []
    except Exception as exc:
        logger.debug(f"Autocomplete failed for '{seed}': {exc}")
    return []


def _ddg_related(seed: str) -> list[str]:
    """
    DuckDuckGo Instant Answer API — related topics.
    Free, no key required.
    """
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": seed, "format": "json", "no_html": 1},
            timeout=8,
        )
        if resp.ok:
            data  = resp.json()
            terms = []
            # Related Topics
            for rt in data.get("RelatedTopics", []):
                if isinstance(rt, dict) and rt.get("Text"):
                    # Extract short keyword from text
                    text = rt["Text"][:60].split(" - ")[0]
                    terms.append(text.strip())
            return terms[:10]
    except Exception as exc:
        logger.debug(f"DDG failed for '{seed}': {exc}")
    return []


def discover_keywords(seeds: list[str] | None = None) -> list[str]:
    """
    Expand seed keywords using Google Autocomplete + DDG.
    Returns a flat list of raw keyword strings (deduplicated).
    """
    seeds   = seeds or INDIA_FINANCE_SEEDS
    found   : set[str] = set()

    for seed in seeds[:20]:   # cap at 20 seeds to avoid rate limits
        try:
            suggestions = _google_autocomplete(seed)
            found.update(s.lower().strip() for s in suggestions if s)
            related = _ddg_related(seed)
            found.update(r.lower().strip() for r in related if r)
            time.sleep(0.2)   # polite delay
        except Exception as exc:
            logger.debug(f"Discovery failed for '{seed}': {exc}")

    # Always include the seeds themselves
    found.update(s.lower().strip() for s in seeds)
    return sorted(found)


# ── Intent + difficulty scoring ───────────────────────────────────────────────

def _classify_intent(kw: str) -> IntentType:
    """
    Rule-based intent classifier — fast, no API needed.
    Finance-specific patterns.
    """
    kw_lower = kw.lower()

    # Question patterns → informational
    if re.search(r"^(what|how|why|when|where|who|which|is|are|can|should|does)\b", kw_lower):
        return "question"

    # Comparison
    if re.search(r"\b(vs|versus|compare|difference|better|best|top)\b", kw_lower):
        return "comparison"

    # Transactional
    if re.search(r"\b(buy|sell|invest|open|apply|download|login|sign up|register|price|rate|charges|fee)\b", kw_lower):
        return "transactional"

    # Navigational
    if re.search(r"\b(login|portal|website|official|site|app)\b", kw_lower):
        return "navigational"

    return "informational"


def _estimate_difficulty(kw: str) -> int:
    """
    Rough difficulty proxy (0-100) based on:
    - Keyword length (longer = easier)
    - Presence of brand names (harder)
    - Question format (easier)
    - Single word (hardest)
    No SERP API needed — this is a heuristic.
    """
    words = kw.strip().split()
    score = 50  # baseline

    # Shorter = more competitive
    if len(words) == 1:   score += 35
    elif len(words) == 2: score += 20
    elif len(words) == 3: score += 5
    elif len(words) >= 5: score -= 15
    elif len(words) >= 4: score -= 10

    # Question format — generally lower competition
    if re.match(r"^(how|what|why|when|where|is|are|can)\b", kw.lower()):
        score -= 15

    # India localisation — lowers competition vs generic
    if re.search(r"\bindia\b|\bindian\b|\binr\b|₹", kw.lower()):
        score -= 10

    # Big brand keywords are hard
    if re.search(r"\b(reliance|hdfc|sbi|icici|tata|infosys|wipro)\b", kw.lower()):
        score += 15

    return max(0, min(100, score))


def _estimate_volume(kw: str) -> int:
    """
    Very rough monthly search volume estimate for Indian finance keywords.
    Based on keyword characteristics — heuristic only.
    """
    words = kw.strip().split()

    # Base by word count
    if len(words) == 1:   base = 5000
    elif len(words) == 2: base = 2000
    elif len(words) == 3: base = 800
    elif len(words) == 4: base = 400
    else:                 base = 150

    # Finance high-volume patterns
    if re.search(r"\b(nifty|sensex|gold|bitcoin|ipo|sip|fd|tax)\b", kw.lower()):
        base = int(base * 2.5)

    # Question patterns — moderate volume
    if re.match(r"^(how|what)\b", kw.lower()):
        base = int(base * 1.3)

    return base


# ── Clustering ────────────────────────────────────────────────────────────────

def _cluster_keywords(
    keywords: list[str],
    config: Config,
    similarity_threshold: float = 0.72,
) -> list[dict]:
    """
    Cluster keywords by semantic similarity using OpenAI embeddings.

    Algorithm:
      1. Embed all keywords (batch of 100 at a time to save API calls)
      2. Greedy clustering: assign each keyword to the first cluster
         whose centroid has sim > threshold; else create new cluster
      3. Label each cluster with GPT-4o-mini

    Returns list of cluster dicts.
    """
    if not config.has_openai:
        # No embeddings available — group by first word as fallback
        clusters: dict[str, list[str]] = {}
        for kw in keywords:
            key = kw.split()[0] if kw.split() else "misc"
            clusters.setdefault(key, []).append(kw)
        return [
            {
                "cluster_id":   k,
                "label":        k.capitalize(),
                "head_keyword": v[0],
                "keywords":     v,
                "embedding":    [],
            }
            for k, v in clusters.items()
        ]

    logger.info(f"Clustering {len(keywords)} keywords via embeddings…")

    # Embed in batches (API allows up to 2048 strings/call but we keep small)
    client   = config.make_ai_client()
    vectors  : dict[str, list[float]] = {}

    BATCH = 50
    for i in range(0, len(keywords), BATCH):
        batch = keywords[i : i + BATCH]
        try:
            resp = client.embeddings.create(model="text-embedding-3-small", input=batch)
            for kw, item in zip(batch, resp.data):
                vectors[kw] = item.embedding
            time.sleep(0.1)
        except Exception as exc:
            logger.warning(f"Embedding batch {i//BATCH} failed: {exc}")

    # Greedy clustering
    cluster_centroids: list[list[float]] = []
    cluster_members  : list[list[str]]   = []

    for kw, vec in vectors.items():
        if not vec:
            continue
        best_idx, best_sim = -1, -1.0
        for idx, centroid in enumerate(cluster_centroids):
            sim = _cosine_similarity(vec, centroid)
            if sim > best_sim:
                best_sim, best_idx = sim, idx

        if best_sim >= similarity_threshold and best_idx >= 0:
            cluster_members[best_idx].append(kw)
            # Update centroid (running mean)
            n = len(cluster_members[best_idx])
            c = cluster_centroids[best_idx]
            cluster_centroids[best_idx] = [(c[j] * (n - 1) + vec[j]) / n for j in range(len(c))]
        else:
            cluster_centroids.append(vec)
            cluster_members.append([kw])

    # Label each cluster
    results: list[dict] = []
    for idx, (members, centroid) in enumerate(zip(cluster_members, cluster_centroids)):
        head = members[0]
        label = _label_cluster(members[:8], config)
        results.append({
            "cluster_id":   f"c{idx:04d}",
            "label":        label,
            "head_keyword": head,
            "keywords":     members,
            "embedding":    centroid[:20],   # store truncated centroid to save space
        })

    logger.info(f"Clustered {len(keywords)} keywords → {len(results)} clusters")
    return results


def _label_cluster(samples: list[str], config: Config) -> str:
    """Label a keyword cluster with a short descriptive phrase."""
    prompt = (
        f"These keywords form a semantic cluster: {', '.join(samples[:8])}\n"
        f"Give this cluster a SHORT label (2-4 words) that captures the shared topic.\n"
        f"Return ONLY JSON: {{\"label\": \"short label\"}}"
    )
    try:
        result = gemini_json_call(config, prompt, max_tokens=60)
        return str(result.get("label", samples[0]))[:50]
    except Exception:
        return samples[0][:40]


# ── Main entry point ──────────────────────────────────────────────────────────

def run_keyword_discovery(config: Config, extra_seeds: list[str] | None = None) -> dict:
    """
    Full keyword discovery + clustering pipeline.

    1. Expand seeds → raw keyword list
    2. Score each (difficulty, intent, volume estimate)
    3. Cluster semantically
    4. Save to kw_store

    Returns summary stats.
    """
    store = load_kw_store()

    # Collect existing keyword strings to avoid re-processing
    existing: set[str] = set()
    for cluster in store.get("clusters", []):
        existing.update(k.get("kw", k) if isinstance(k, dict) else k for k in cluster.get("keywords", []))
    existing.update(
        k.get("kw", k) if isinstance(k, dict) else k
        for k in store.get("unclustered", [])
    )

    all_seeds = (INDIA_FINANCE_SEEDS + (extra_seeds or []))
    raw = discover_keywords(all_seeds)
    new_kws = [kw for kw in raw if kw not in existing]

    logger.info(f"Discovered {len(raw)} keywords; {len(new_kws)} new")

    # Score new keywords
    scored = [
        {
            "kw":         kw,
            "volume_est": _estimate_volume(kw),
            "difficulty": _estimate_difficulty(kw),
            "intent":     _classify_intent(kw),
            "added_at":   time.time(),
        }
        for kw in new_kws
    ]

    # Cluster all new keywords
    kw_strings = [k["kw"] for k in scored]
    if kw_strings:
        new_clusters = _cluster_keywords(kw_strings, config)

        # Merge scored metadata into clusters
        kw_map = {k["kw"]: k for k in scored}
        for cluster in new_clusters:
            cluster["keywords"] = [kw_map.get(kw, {"kw": kw}) for kw in cluster["keywords"]]

        store["clusters"] = store.get("clusters", []) + new_clusters

    store["last_discovery"] = time.time()
    save_kw_store(store)

    return {
        "total_keywords": len(raw),
        "new_keywords":   len(new_kws),
        "clusters":       len(store.get("clusters", [])),
        "timestamp":      store["last_discovery"],
    }


def get_easy_win_keywords(max_difficulty: int = 40, top_n: int = 20) -> list[dict]:
    """
    Return the easiest-win keywords: low difficulty, informational/question intent,
    sorted by estimated volume descending.
    Ideal for planning the next batch of articles.
    """
    store   = load_kw_store()
    all_kws : list[dict] = []

    for cluster in store.get("clusters", []):
        for kw in cluster.get("keywords", []):
            if isinstance(kw, dict):
                all_kws.append({**kw, "cluster_label": cluster.get("label", "")})

    filtered = [
        k for k in all_kws
        if k.get("difficulty", 100) <= max_difficulty
        and k.get("intent") in ("informational", "question", "comparison")
    ]
    filtered.sort(key=lambda x: x.get("volume_est", 0), reverse=True)
    return filtered[:top_n]
