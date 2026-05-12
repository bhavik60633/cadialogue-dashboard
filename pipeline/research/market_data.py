"""
Live market data fetcher.
Pulls Sensex, Nifty, S&P 500, BTC, ETH, and RBI repo rate.
Uses yfinance (no API key needed) + CoinGecko free API.
Falls back gracefully on any individual source failure.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
import yfinance as yf

from ..utils.logger import get_logger
from ..utils.retry import with_retry_sync

logger = get_logger("market_data")


@dataclass
class MarketSnapshot:
    sensex: float = 0.0
    sensex_change_pct: float = 0.0
    nifty: float = 0.0
    nifty_change_pct: float = 0.0
    sp500: float = 0.0
    sp500_change_pct: float = 0.0
    nasdaq: float = 0.0
    nasdaq_change_pct: float = 0.0
    btc_usd: float = 0.0
    btc_inr: float = 0.0
    eth_usd: float = 0.0
    rbi_repo_rate: float = 6.5      # Updated when scraped; fallback to last known
    usd_inr: float = 83.0
    timestamp: str = ""


@with_retry_sync(max_attempts=2, delay_seconds=2, backoff=1.5)
def _fetch_yfinance_ticker(symbol: str) -> tuple[float, float]:
    """Returns (price, change_pct) for a Yahoo Finance ticker."""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="2d", interval="1d", timeout=8)
    if len(hist) < 2:
        hist = ticker.history(period="5d", interval="1d", timeout=8)
    if len(hist) < 1:
        return 0.0, 0.0
    latest = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else latest
    change_pct = ((latest - prev) / prev * 100) if prev else 0.0
    return round(latest, 2), round(change_pct, 2)


@with_retry_sync(max_attempts=2, delay_seconds=2, backoff=1.5)
def _fetch_crypto() -> dict:
    """Fetch BTC + ETH prices from CoinGecko (no API key needed)."""
    resp = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd,inr",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "btc_usd": data.get("bitcoin", {}).get("usd", 0),
        "btc_inr": data.get("bitcoin", {}).get("inr", 0),
        "eth_usd": data.get("ethereum", {}).get("usd", 0),
    }


@with_retry_sync(max_attempts=1, delay_seconds=2)
def _fetch_rbi_repo_rate() -> float:
    """
    Scrape RBI website for current repo rate.
    Falls back to last known value (6.5%) if scraping fails.
    RBI rate changes ~6× per year, so a stale value is fine.
    """
    try:
        resp = requests.get(
            "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
            headers={"User-Agent": "Mozilla/5.0 (compatible; FinancePipeline/1.0)"},
            timeout=8,
        )
        resp.raise_for_status()
        import re
        # Look for pattern like "repo rate at 6.50 per cent" or "repo rate to 6.25%"
        match = re.search(r"repo rate[^\d]*(\d+\.?\d*)\s*(?:per\s*cent|%)", resp.text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    except Exception as exc:
        logger.warning(f"RBI scrape failed: {exc}. Using fallback rate 6.50%")
    return 6.50


async def fetch_market_snapshot() -> MarketSnapshot:
    """
    Fetch all market data concurrently and return a snapshot.
    Hard deadline: 30 seconds. Any source that doesn't respond gets defaults.
    """
    logger.info("Fetching market data…")
    snap = MarketSnapshot(timestamp=datetime.now(timezone.utc).isoformat())

    loop = asyncio.get_event_loop()

    # Run ALL sync fetches in thread pool truly in parallel
    names = ["sensex", "nifty", "sp500", "nasdaq", "usd_inr", "crypto", "rbi"]
    coros = [
        loop.run_in_executor(None, _fetch_yfinance_ticker, "^BSESN"),
        loop.run_in_executor(None, _fetch_yfinance_ticker, "^NSEI"),
        loop.run_in_executor(None, _fetch_yfinance_ticker, "^GSPC"),
        loop.run_in_executor(None, _fetch_yfinance_ticker, "^IXIC"),
        loop.run_in_executor(None, _fetch_yfinance_ticker, "USDINR=X"),
        loop.run_in_executor(None, _fetch_crypto),
        loop.run_in_executor(None, _fetch_rbi_repo_rate),
    ]

    # True parallel gather with 30s hard deadline
    try:
        raw_results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Market snapshot hit 30s deadline — using partial/default data")
        raw_results = [None] * len(names)

    results = {}
    for name, result in zip(names, raw_results):
        if isinstance(result, Exception):
            logger.warning(f"Market data fetch failed for {name}: {result}")
            results[name] = None
        else:
            results[name] = result

    if results.get("sensex"):
        snap.sensex, snap.sensex_change_pct = results["sensex"]
    if results.get("nifty"):
        snap.nifty, snap.nifty_change_pct = results["nifty"]
    if results.get("sp500"):
        snap.sp500, snap.sp500_change_pct = results["sp500"]
    if results.get("nasdaq"):
        snap.nasdaq, snap.nasdaq_change_pct = results["nasdaq"]
    if results.get("usd_inr"):
        snap.usd_inr = results["usd_inr"][0]
    if results.get("crypto"):
        c = results["crypto"]
        snap.btc_usd = c.get("btc_usd", 0)
        snap.btc_inr = c.get("btc_inr", 0)
        snap.eth_usd = c.get("eth_usd", 0)
    if results.get("rbi"):
        snap.rbi_repo_rate = results["rbi"]

    logger.info(
        f"Market snapshot: Sensex {snap.sensex:,.0f} ({snap.sensex_change_pct:+.2f}%) | "
        f"Nifty {snap.nifty:,.0f} | S&P {snap.sp500:,.0f} | "
        f"BTC ${snap.btc_usd:,.0f} | RBI repo {snap.rbi_repo_rate}%"
    )
    return snap
