# Decision: yfinance dividendYield normalization

**Author:** Linus (Quant Dev)
**Date:** 2025-07-25

## Context
MSFT was showing ~88% dividend yield in the DGI screener modal. The actual yield is ~0.8%.

## Root Cause
yfinance `dividendYield` returns values in **percentage form** (0.88 = 0.88%, 2.42 = 2.42%). The old normalization `if raw_yield > 1: raw_yield /= 100` only caught yields above 1%, leaving sub-1% stocks (MSFT 0.88, AAPL 0.37) in percentage form while the rest of the pipeline (scoring, categorization, filters) expected decimal (0.0088).

**Downstream effects of the bug:**
- Filter modal showed `0.88 * 100 = 88.00%` (line 459)
- Scoring: `0.88 / 0.05 * 100 = 1760`, clamped to 100 — always max score
- Categorization: `0.88 >= 0.04` → wrongly classified as "High Yield"
- Table display happened to look correct (`0.88%`) by accident

## Decision
Always divide `dividendYield` by 100 (unconditional). Verified against 6 stocks: yfinance `dividendYield` is consistently percentage-form across all yield ranges.

## Files Changed
- `src/dgi_screener.py` — two normalization blocks (single-symbol + batch)
- `web/templates/dgi_screener.html` — table display (`* 100`) + JS filter comparison

## Impact
All team members: dividend_yield is now stored as **decimal** everywhere (0.0088 = 0.88%). This is consistent with `payout_ratio`, `returnOnEquity`, and `dividend_cagr_5y`.
