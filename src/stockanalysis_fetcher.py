"""StockAnalysis.com dividend data fetcher.

Scrapes the dividend summary widget from stockanalysis.com to supplement
Yahoo Finance dividend metrics.  The primary value-add is the authoritative
``growth_years`` field (consecutive years of dividend increases) which is
more reliable than computing it from Yahoo's dividend series.

All percentage values are returned as decimals (e.g. 2.56% → 0.0256).
Returns ``None`` on any error so callers can fall back gracefully.
"""

import logging
import random
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-Agent rotation (same pattern as tv_data_fetcher.py)
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
]

_BASE_URL = "https://stockanalysis.com/stocks/{symbol}/dividend/"

# In-memory cache for the current run (symbol → parsed dict)
_cache: dict[str, Optional[dict]] = {}


def _get_headers() -> dict:
    """Realistic browser headers to avoid bot detection."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _parse_percentage(text: str) -> Optional[float]:
    """Convert '2.56%' or '-1.23%' to decimal (0.0256 / -0.0123)."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    m = re.search(r"(-?[\d.]+)\s*%", text)
    if m:
        return float(m.group(1)) / 100.0
    return None


def _parse_currency(text: str) -> Optional[float]:
    """Convert '$2.12' to 2.12."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    m = re.search(r"\$?\s*(-?[\d.]+)", text)
    if m:
        return float(m.group(1))
    return None


def _parse_int(text: str) -> Optional[int]:
    """Convert '13' or '13 Years' to int."""
    if not text:
        return None
    m = re.search(r"(\d+)", text.strip())
    if m:
        return int(m.group(1))
    return None


# Map of label text (lowercased) → (output key, parser function)
_FIELD_MAP = {
    "dividend yield": ("dividend_yield", _parse_percentage),
    "annual dividend": ("annual_dividend", _parse_currency),
    "payout ratio": ("payout_ratio", _parse_percentage),
    "dividend growth": ("dividend_growth", _parse_percentage),
    "growth years": ("growth_years", _parse_int),
    "payout frequency": ("payout_frequency", lambda t: t.strip() if t else None),
    "buyback yield": ("buyback_yield", _parse_percentage),
    "shareholder yield": ("shareholder_yield", _parse_percentage),
}


def fetch_dividend_data(symbol: str) -> Optional[dict]:
    """Scrape dividend summary data from stockanalysis.com.

    Args:
        symbol: Ticker symbol (e.g. ``"AAPL"``).

    Returns:
        Dict with parsed dividend metrics, or ``None`` on failure.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return None

    # Check cache first
    if symbol in _cache:
        logger.debug("[SA] Cache hit for %s", symbol)
        return _cache[symbol]

    url = _BASE_URL.format(symbol=symbol.lower())
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[SA] HTTP error fetching %s: %s", symbol, exc)
        _cache[symbol] = None
        return None

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        result: dict = {}

        # Strategy: find all key-value pairs in the dividend summary widget.
        # The page uses a table or grid with label/value pairs. We search
        # for known labels and grab the adjacent value.
        # Approach 1: look for <td>/<th> or <span> elements with known labels.
        for element in soup.find_all(["td", "th", "span", "div"]):
            text = element.get_text(strip=True).lower()
            for label, (key, parser) in _FIELD_MAP.items():
                if key in result:
                    continue
                if label in text and text.replace(label, "").strip() in ("", ":"):
                    # The value is in the next sibling element
                    value_el = element.find_next_sibling()
                    if value_el is None:
                        # Try parent's next sibling (common in grid layouts)
                        parent = element.parent
                        if parent:
                            value_el = parent.find_next_sibling()
                            if value_el:
                                value_el = value_el.find(["td", "span", "div"]) or value_el
                    if value_el:
                        raw = value_el.get_text(strip=True)
                        parsed = parser(raw)
                        if parsed is not None:
                            result[key] = parsed

        # Approach 2: regex scan the full HTML for data patterns as fallback
        if "growth_years" not in result:
            m = re.search(r"Growth\s+Years[^<]*?<[^>]*>\s*(\d+)", resp.text, re.IGNORECASE)
            if m:
                result["growth_years"] = int(m.group(1))

        if "dividend_yield" not in result:
            m = re.search(r"Dividend\s+Yield[^<]*?<[^>]*>\s*([\d.]+)%", resp.text, re.IGNORECASE)
            if m:
                result["dividend_yield"] = float(m.group(1)) / 100.0

        if "payout_ratio" not in result:
            m = re.search(r"Payout\s+Ratio[^<]*?<[^>]*>\s*([\d.]+)%", resp.text, re.IGNORECASE)
            if m:
                result["payout_ratio"] = float(m.group(1)) / 100.0

        if "dividend_growth" not in result:
            m = re.search(r"Dividend\s+Growth[^<]*?<[^>]*>\s*(-?[\d.]+)%", resp.text, re.IGNORECASE)
            if m:
                result["dividend_growth"] = float(m.group(1)) / 100.0

        if not result:
            logger.warning("[SA] No dividend data parsed for %s from %s", symbol, url)
            _cache[symbol] = None
            return None

        logger.info("[SA] Parsed %d fields for %s: %s", len(result), symbol,
                     ", ".join(f"{k}={v}" for k, v in result.items()))
        _cache[symbol] = result
        return result

    except Exception as exc:
        logger.warning("[SA] Parse error for %s: %s", symbol, exc, exc_info=True)
        _cache[symbol] = None
        return None
