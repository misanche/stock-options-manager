"""DGI (Dividend Growth Investing) metrics and scoring.

All calculations for the DGI Screener: technical indicators, fundamental
metrics, quality scoring, categorisation, and minimum-filter checks.
Formulas and thresholds follow the spec in danny-dgi-screener.md (v3).
"""

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ======================================================================
# Technical Indicators (computed from OHLCV data)
# ======================================================================


def calculate_rsi(close_prices: np.ndarray, period: int = 14) -> float:
    """Return RSI for the most recent bar.  Requires len ≥ period + 1."""
    prices = np.asarray(close_prices, dtype=float)
    if len(prices) < period + 1:
        return 50.0  # neutral fallback

    deltas = np.diff(prices[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def calculate_sma(close_prices: np.ndarray, period: int) -> float:
    """Simple moving average of the last *period* values."""
    prices = np.asarray(close_prices, dtype=float)
    if len(prices) < period:
        return float(np.mean(prices))
    return float(np.mean(prices[-period:]))


def calculate_bollinger_bands(
    close_prices: np.ndarray,
    period: int = 20,
    num_std: float = 2.0,
) -> Dict[str, float]:
    """Bollinger Bands — mid, upper, lower, and position (0–1 scale)."""
    prices = np.asarray(close_prices, dtype=float)
    mid = calculate_sma(prices, period)
    window = prices[-period:] if len(prices) >= period else prices
    std = float(np.std(window, ddof=0))

    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = upper - lower

    current = float(prices[-1])
    position = (current - lower) / band_width if band_width > 0 else 0.5

    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "position": position,
    }


def calculate_technical_timing_score(
    close_prices: np.ndarray,
    high_prices: np.ndarray,
    low_prices: np.ndarray,
    current_price: float,
    rsi_period: int = 14,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> Dict[str, Any]:
    """Combined technical timing score (0-100) with all sub-components.

    Returns dict with keys: score, rsi, sma_50, sma_200, high_52w,
    low_52w, bb, sub_scores.
    """
    close = np.asarray(close_prices, dtype=float)
    high = np.asarray(high_prices, dtype=float)
    low = np.asarray(low_prices, dtype=float)

    # --- RSI ---
    rsi_val = calculate_rsi(close, period=rsi_period)
    if rsi_val <= 30:
        rsi_score = 100
    elif rsi_val <= 40:
        rsi_score = 75
    elif rsi_val <= 50:
        rsi_score = 50
    elif rsi_val <= 70:
        rsi_score = 25
    else:
        rsi_score = 0

    # --- SMA position ---
    sma_50 = calculate_sma(close, 50)
    sma_200 = calculate_sma(close, 200)

    dist_sma200 = (current_price - sma_200) / sma_200 if sma_200 else 0.0
    if dist_sma200 <= -0.10:
        sma_score = 100
    elif dist_sma200 <= -0.03:
        sma_score = 80
    elif dist_sma200 <= 0.03:
        sma_score = 60
    elif dist_sma200 <= 0.10:
        sma_score = 30
    else:
        sma_score = 10

    # Golden cross bonus
    if sma_50 > sma_200:
        sma_score = min(100, sma_score + 10)

    # --- 52-week high distance ---
    trading_days_1y = min(252, len(high))
    high_52w = float(np.max(high[-trading_days_1y:]))
    low_52w = float(np.min(low[-trading_days_1y:]))
    dist_from_high = (high_52w - current_price) / high_52w if high_52w else 0.0

    if dist_from_high >= 0.25:
        high_dist_score = 100
    elif dist_from_high >= 0.15:
        high_dist_score = 80
    elif dist_from_high >= 0.08:
        high_dist_score = 60
    elif dist_from_high >= 0.03:
        high_dist_score = 35
    else:
        high_dist_score = 10

    # --- Bollinger Bands ---
    bb = calculate_bollinger_bands(close, period=bb_period, num_std=bb_std)
    bb_pos = bb["position"]

    if bb_pos <= 0:
        bb_score = 100
    elif bb_pos <= 0.25:
        bb_score = 80
    elif bb_pos <= 0.50:
        bb_score = 50
    elif bb_pos <= 0.75:
        bb_score = 25
    else:
        bb_score = 5

    # --- Combined ---
    combined = (
        rsi_score * 0.30
        + sma_score * 0.25
        + high_dist_score * 0.25
        + bb_score * 0.20
    )

    return {
        "score": round(combined, 2),
        "rsi": round(rsi_val, 2),
        "sma_50": round(sma_50, 2),
        "sma_200": round(sma_200, 2),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "bb": {k: round(v, 4) for k, v in bb.items()},
        "sub_scores": {
            "rsi_score": rsi_score,
            "sma_score": sma_score,
            "high_dist_score": high_dist_score,
            "bb_score": bb_score,
        },
    }


# ======================================================================
# Fundamental Dividend Metrics
# ======================================================================


def calculate_years_consecutive_increases(dividends_series: pd.Series) -> int:
    """Count consecutive years of dividend increases (most recent backward).

    Expects a ``pd.Series`` indexed by datetime with per-payment amounts
    (as returned by ``yfinance``).
    """
    if dividends_series is None or dividends_series.empty:
        return 0

    # Aggregate to annual totals
    annual = dividends_series.groupby(dividends_series.index.year).sum()
    annual = annual.sort_index()

    # Drop the current (partial) year — incomplete payments would break the streak
    current_year = pd.Timestamp.now().year
    if current_year in annual.index:
        annual = annual.drop(current_year)

    if len(annual) < 2:
        return 0

    years = list(annual.values)
    consecutive = 0
    for i in range(len(years) - 1, 0, -1):
        if years[i] > years[i - 1]:
            consecutive += 1
        else:
            break

    return consecutive


def calculate_dividend_cagr(
    dividends_series: pd.Series,
    years: int = 5,
) -> float:
    """Compound annual growth rate of dividends over *years*.

    Returns 0.0 when insufficient data or the starting value is zero.
    """
    if dividends_series is None or dividends_series.empty:
        return 0.0

    annual = dividends_series.groupby(dividends_series.index.year).sum()
    annual = annual.sort_index()

    # Drop the current (partial) year to avoid skewed CAGR
    current_year = pd.Timestamp.now().year
    if current_year in annual.index:
        annual = annual.drop(current_year)

    if len(annual) < years + 1:
        # Not enough history — use what we have
        if len(annual) < 2:
            return 0.0
        years = len(annual) - 1

    start_val = float(annual.iloc[-(years + 1)])
    end_val = float(annual.iloc[-1])

    if start_val <= 0:
        return 0.0

    return float((end_val / start_val) ** (1.0 / years) - 1.0)


# ======================================================================
# Sub-score helpers (all 0-100 scale)
# ======================================================================


def _clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


def _dividend_yield_score(dividend_yield: float) -> float:
    """1.5% → 0, 3% → 50, 6%+ → 100."""
    return _clamp((dividend_yield - 0.015) / 0.045 * 100)


def _dividend_growth_score(cagr_5y: float) -> float:
    """0% → 0, 7% → ~47, 15%+ → 100."""
    return _clamp(cagr_5y / 0.15 * 100)


def _payout_safety_score(payout_ratio: float) -> float:
    """75% → 0, 50% → 50, 25% → 100 (inverted)."""
    return _clamp((0.75 - payout_ratio) / 0.50 * 100)


def _valuation_score(pe_ratio: float) -> float:
    """P/E 30 → 0, 20 → 50, 10 → 100 (inverted)."""
    return _clamp((30 - pe_ratio) / 20 * 100)


def _financial_health_score(debt_to_equity: float, roe: float) -> float:
    """Average of D/E score and ROE score."""
    de_score = _clamp((2.0 - debt_to_equity) / 2.0 * 100)
    roe_score = _clamp(roe / 0.30 * 100)
    return de_score * 0.5 + roe_score * 0.5


def _consistency_score(years_consecutive: int) -> float:
    """3 yrs → 0, 10 → ~32, 25+ → 100."""
    return _clamp((years_consecutive - 3) / 22 * 100)


# ======================================================================
# Quality Score (0-100)
# ======================================================================


def calculate_quality_score(
    metrics: Dict[str, Any],
    technical: Dict[str, Any],
) -> float:
    """Weighted quality score: 70 % fundamental + 30 % technical timing.

    Parameters
    ----------
    metrics:
        Dict with keys: dividend_yield, dividend_cagr_5y, payout_ratio,
        pe_ratio, debt_to_equity, roe, years_consecutive_increases.
    technical:
        Dict returned by :func:`calculate_technical_timing_score`
        (must contain ``"score"``).
    """
    yield_s = _dividend_yield_score(metrics.get("dividend_yield", 0))
    growth_s = _dividend_growth_score(metrics.get("dividend_cagr_5y", 0))
    payout_s = _payout_safety_score(metrics.get("payout_ratio", 1.0))
    val_s = _valuation_score(metrics.get("pe_ratio", 30))
    health_s = _financial_health_score(
        metrics.get("debt_to_equity", 2.0),
        metrics.get("roe", 0),
    )
    consist_s = _consistency_score(metrics.get("years_consecutive_increases", 0))
    tech_s = technical.get("score", 0)

    score = (
        yield_s * 0.15
        + growth_s * 0.18
        + payout_s * 0.10
        + val_s * 0.10
        + health_s * 0.07
        + consist_s * 0.10
        + tech_s * 0.30
    )
    return round(score, 2)


# ======================================================================
# Categorisation
# ======================================================================


def categorize_stock(metrics: Dict[str, Any]) -> str:
    """Assign a single DGI category based on metric thresholds.

    Priority: Aristocrat > Rising Star > Compounder > High Yield > Balanced.
    """
    y = metrics.get("dividend_yield", 0)
    g = metrics.get("dividend_cagr_5y", 0)
    p = metrics.get("payout_ratio", 1.0)
    yrs = metrics.get("years_consecutive_increases", 0)

    if yrs >= 25 and y >= 0.02:
        return "Aristocrat"
    if g >= 0.15 and yrs <= 10 and y < 0.02:
        return "Rising Star"
    if g >= 0.10 and y < 0.03 and p <= 0.50:
        return "Compounder"
    if y >= 0.04:
        return "High Yield"
    return "Balanced"


# ======================================================================
# Minimum Filters
# ======================================================================

DEFAULT_FILTERS: Dict[str, Any] = {
    "min_yield": 0.015,
    "max_payout": 0.75,
    "max_pe": 30,
    "max_de": 2.0,
    "min_years": 3,
    "min_market_cap": 10_000_000_000,  # $10 B
    "min_growth": 0.0,
}


def passes_minimum_filters(
    metrics: Dict[str, Any],
    filters: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return ``True`` if *metrics* satisfy all eliminatory filters."""
    f = {**DEFAULT_FILTERS, **(filters or {})}

    checks = [
        metrics.get("dividend_yield", 0) >= f["min_yield"],
        metrics.get("payout_ratio", 1.0) <= f["max_payout"],
        metrics.get("pe_ratio", 999) <= f["max_pe"],
        metrics.get("debt_to_equity", 999) <= f["max_de"],
        metrics.get("years_consecutive_increases", 0) >= f["min_years"],
        metrics.get("market_cap", 0) >= f["min_market_cap"],
        metrics.get("dividend_cagr_5y", 0) > f["min_growth"],
    ]
    return all(checks)
