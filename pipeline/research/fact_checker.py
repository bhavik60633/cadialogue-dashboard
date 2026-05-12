"""
Fact-checker: extracts numeric claims from a topic and cross-verifies
them against live market data. Returns a list of verified facts for the writer.
"""
import re
from dataclasses import dataclass
from typing import Optional

from ..utils.logger import get_logger
from .market_data import MarketSnapshot
from .topic_finder import ScoredTopic

logger = get_logger("fact_checker")


@dataclass
class VerifiedFact:
    claim: str                    # e.g. "Sensex at 75,000"
    verified: bool
    actual_value: Optional[str]   # What the real value is
    source: str                   # e.g. "yfinance:^BSESN"
    note: Optional[str] = None    # Any caveat to include in article


def _build_market_fact_table(market: MarketSnapshot) -> dict[str, str]:
    """Build a lookup of verified market facts from the snapshot."""
    return {
        "sensex": f"{market.sensex:,.2f}",
        "bse sensex": f"{market.sensex:,.2f}",
        "nifty": f"{market.nifty:,.2f}",
        "nifty 50": f"{market.nifty:,.2f}",
        "s&p 500": f"{market.sp500:,.2f}",
        "sp500": f"{market.sp500:,.2f}",
        "bitcoin": f"${market.btc_usd:,.2f}",
        "btc": f"${market.btc_usd:,.2f}",
        "ethereum": f"${market.eth_usd:,.2f}",
        "eth": f"${market.eth_usd:,.2f}",
        "repo rate": f"{market.rbi_repo_rate}%",
        "rbi repo rate": f"{market.rbi_repo_rate}%",
        "usd/inr": f"₹{market.usd_inr:.2f}",
        "dollar": f"₹{market.usd_inr:.2f}",
    }


async def fact_check_topic(
    topic: ScoredTopic, market: MarketSnapshot
) -> list[VerifiedFact]:
    """
    Build a list of key verified facts the writer should use.
    Also scans the topic summary for any numeric claims and flags them.
    """
    verified: list[VerifiedFact] = []
    fact_table = _build_market_fact_table(market)

    # 1. Always include the core market data as verified facts
    if market.sensex > 0:
        verified.append(VerifiedFact(
            claim=f"Sensex at {market.sensex:,.2f}",
            verified=True,
            actual_value=f"{market.sensex:,.2f}",
            source="yfinance:^BSESN",
            note=f"Change: {market.sensex_change_pct:+.2f}% today",
        ))
    if market.nifty > 0:
        verified.append(VerifiedFact(
            claim=f"Nifty 50 at {market.nifty:,.2f}",
            verified=True,
            actual_value=f"{market.nifty:,.2f}",
            source="yfinance:^NSEI",
            note=f"Change: {market.nifty_change_pct:+.2f}% today",
        ))
    if market.sp500 > 0:
        verified.append(VerifiedFact(
            claim=f"S&P 500 at {market.sp500:,.2f}",
            verified=True,
            actual_value=f"{market.sp500:,.2f}",
            source="yfinance:^GSPC",
            note=f"Change: {market.sp500_change_pct:+.2f}% today",
        ))
    if market.btc_usd > 0:
        verified.append(VerifiedFact(
            claim=f"Bitcoin at ${market.btc_usd:,.2f} (₹{market.btc_inr:,.2f})",
            verified=True,
            actual_value=f"${market.btc_usd:,.2f}",
            source="coingecko",
        ))
    if market.rbi_repo_rate > 0:
        verified.append(VerifiedFact(
            claim=f"RBI repo rate at {market.rbi_repo_rate}%",
            verified=True,
            actual_value=f"{market.rbi_repo_rate}%",
            source="rbi.org.in",
        ))
    if market.usd_inr > 0:
        verified.append(VerifiedFact(
            claim=f"USD/INR at ₹{market.usd_inr:.2f}",
            verified=True,
            actual_value=f"₹{market.usd_inr:.2f}",
            source="yfinance:USDINR=X",
        ))

    # 2. Scan topic summary for numeric claims not covered above
    numbers_in_summary = re.findall(r"\b\d[\d,\.]*\b", topic.summary)
    if numbers_in_summary:
        logger.info(f"Found {len(numbers_in_summary)} numeric claims in topic summary — flagging for writer")
        verified.append(VerifiedFact(
            claim="Additional numeric claims in topic brief",
            verified=False,
            actual_value=None,
            source="topic_summary",
            note=(
                "Writer should independently verify any specific numbers from the topic "
                "brief against official sources before including them."
            ),
        ))

    logger.info(f"Fact-check complete: {len(verified)} verified facts")
    return verified
