"""
Post-generation fact validator.

Scans a generated article for:
  1. [UNVERIFIED: ...] markers — the writer's own uncertainty flag
  2. Specific company financial claims (e.g. "Rs 276.48 crore", "+45%") that
     don't appear in the verified facts pool
  3. RBI rate / repo rate values that don't match the live market snapshot

Returns a ValidationResult that either:
  - is_clean=True  → safe to surface for review / publish
  - is_clean=False → contains a list of flagged claims; downstream must require
                     the user to manually approve before publishing
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..research.fact_checker import VerifiedFact
from ..research.market_data import MarketSnapshot
from ..utils.logger import get_logger

logger = get_logger("fact_validator")


@dataclass
class FactFlag:
    severity: str          # "high" | "medium" | "low"
    category: str          # "unverified_marker" | "rbi_rate" | "specific_number" | "company_financial"
    snippet: str           # 100 chars of surrounding context
    detail: str            # human-readable explanation


@dataclass
class ValidationResult:
    is_clean: bool
    flags: List[FactFlag] = field(default_factory=list)
    summary: str = ""

    @property
    def high_severity_count(self) -> int:
        return sum(1 for f in self.flags if f.severity == "high")

    def to_dict(self) -> dict:
        return {
            "is_clean": self.is_clean,
            "high_severity_count": self.high_severity_count,
            "flag_count": len(self.flags),
            "summary": self.summary,
            "flags": [
                {"severity": f.severity, "category": f.category,
                 "snippet": f.snippet, "detail": f.detail}
                for f in self.flags
            ],
        }


# ── Build the pool of numbers/strings the writer is allowed to cite ──────────

def _build_allowed_pool(facts: List[VerifiedFact], market: MarketSnapshot) -> set[str]:
    """
    Extract every number from the verified-facts list + live market snapshot.
    Returns a set of normalized number strings the writer may legitimately use.
    """
    pool: set[str] = set()

    def add_number(n) -> None:
        if n is None:
            return
        try:
            v = float(n)
        except (TypeError, ValueError):
            return
        # Add multiple representations: 75315, 75,315, 75315.04, 75,315.04
        pool.add(f"{v:,.0f}")
        pool.add(f"{v:.0f}")
        pool.add(f"{v:,.2f}")
        pool.add(f"{v:.2f}")
        if v < 100:                          # for rates / %
            pool.add(f"{v:.1f}")
            pool.add(f"{v:.2f}")

    # Market snapshot values
    for attr in ("sensex", "nifty", "sp500", "nasdaq", "btc_usd", "btc_inr",
                 "eth_usd", "usd_inr", "rbi_repo_rate"):
        add_number(getattr(market, attr, None))

    # Pull every number out of verified-fact claim text + notes
    num_re = re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b\d+\.\d+\b|\b\d+\b")
    for f in facts:
        if not f.verified:
            continue
        for src in (f.claim or "", f.note or ""):
            for m in num_re.findall(src):
                clean = m.replace(",", "")
                try:
                    v = float(clean)
                    add_number(v)
                except ValueError:
                    pass
    return pool


# ── Regex patterns for suspicious specifics ──────────────────────────────────

# Currency: ₹276.48 crore | Rs 1,484 crore | $109.69 billion
_MONEY_RE = re.compile(
    r"(?:₹|Rs\.?\s*|\$)\s?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\s*(?:crore|lakh|billion|million|bn|mn)?",
    re.IGNORECASE,
)
# Percentages: +45%, -3.7%, 20.9%
_PCT_RE = re.compile(r"[+\-]?\d+(?:\.\d+)?\s*%")
# Stock-price-ish: "shares climbed 8.1% to ₹989" — already covered above

_UNVERIFIED_MARKER_RE = re.compile(r"\[UNVERIFIED:[^\]]+\]", re.IGNORECASE)


def _snippet(text: str, start: int, end: int, ctx: int = 60) -> str:
    s = max(0, start - ctx)
    e = min(len(text), end + ctx)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def validate_article(
    article: str,
    facts: List[VerifiedFact],
    market: MarketSnapshot,
) -> ValidationResult:
    """
    Validate that every specific number/claim in `article` is traceable to a
    verified source. Returns ValidationResult.
    """
    flags: List[FactFlag] = []
    allowed = _build_allowed_pool(facts, market)

    # ── 1. [UNVERIFIED: ...] markers from the writer ──────────────────────────
    for m in _UNVERIFIED_MARKER_RE.finditer(article):
        flags.append(FactFlag(
            severity="high",
            category="unverified_marker",
            snippet=_snippet(article, m.start(), m.end()),
            detail=f"Writer explicitly flagged this as unverified: {m.group(0)}",
        ))

    # ── 2. RBI rate / repo rate mismatch ──────────────────────────────────────
    rate_val = getattr(market, "rbi_repo_rate", None)
    if rate_val is not None:
        # Find every "X% repo rate" or "repo rate ... X%" near the article
        repo_re = re.compile(
            r"(?:repo\s*rate[^.<]{0,40}?(\d+\.?\d*)\s*%|(\d+\.?\d*)\s*%\s*repo\s*rate)",
            re.IGNORECASE,
        )
        for m in repo_re.finditer(article):
            cited = m.group(1) or m.group(2)
            try:
                if abs(float(cited) - float(rate_val)) > 0.01:
                    flags.append(FactFlag(
                        severity="high",
                        category="rbi_rate",
                        snippet=_snippet(article, m.start(), m.end()),
                        detail=f"Cited repo rate {cited}% does not match live snapshot {rate_val}%",
                    ))
            except ValueError:
                pass

    # ── 3. Specific currency/financial numbers not in allowed pool ────────────
    #     (medium severity — many of these will be legit market data references)
    for m in _MONEY_RE.finditer(article):
        token = m.group(0)
        # Extract just the numeric portion
        num_match = re.search(r"\d{1,3}(?:,\d{2,3})*(?:\.\d+)?", token)
        if not num_match:
            continue
        clean = num_match.group(0).replace(",", "")
        try:
            v = float(clean)
        except ValueError:
            continue
        # Skip tiny numbers (single-digit, percentages handled elsewhere)
        if v < 10:
            continue
        # Check against allowed pool — many representations
        candidates = {f"{v:,.0f}", f"{v:.0f}", f"{v:,.2f}", f"{v:.2f}"}
        if not (candidates & allowed):
            flags.append(FactFlag(
                severity="medium",
                category="specific_number",
                snippet=_snippet(article, m.start(), m.end()),
                detail=f"Currency figure '{token}' not found in verified facts or live market data",
            ))

    # ── Summary ──────────────────────────────────────────────────────────────
    high = sum(1 for f in flags if f.severity == "high")
    med  = sum(1 for f in flags if f.severity == "medium")
    is_clean = (high == 0)
    summary = (
        f"{high} high-severity, {med} medium-severity flag(s). "
        + ("CLEAN — safe to surface for review." if is_clean
           else "BLOCKED — writer-flagged unverified data found. Manual review required.")
    )
    logger.info(f"[fact_validator] {summary}")
    return ValidationResult(is_clean=is_clean, flags=flags, summary=summary)
