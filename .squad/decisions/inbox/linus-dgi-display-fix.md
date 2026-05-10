# DGI Screener Display & Data Fixes

**Date:** 2026-05-10
**Author:** Linus (Quant Dev)
**Status:** ✅ Implemented

## Changes

### 1. Dividend Yield Display — removed `* 100`
- `dividend_yield` from yfinance `info["dividendYield"]` is already in percentage form (e.g., 1.18 = 1.18%)
- Template was multiplying by 100 again → showing 118% instead of 1.18%
- `dividend_cagr_5y` from `calculate_dividend_cagr()` returns a ratio (0-1) → kept `* 100`

**Note:** The scoring functions in `dgi_metrics.py` (`_dividend_yield_score`, `categorize_stock`, `passes_minimum_filters`) treat `dividend_yield` as a ratio (thresholds like 0.015, 0.02). If yfinance now returns percentage values, these thresholds may need recalibration. Recommend verifying scoring accuracy after the next screener run.

### 2. Detail Modal on Row Click
- Added modal overlay reusing existing `.modal-*` CSS classes from `style.css`
- Clicking a row (not action buttons) shows full entry data grouped into: Overview, Fundamentals, Technical Timing (with nested sub-scores)
- Escape key, clicking outside, or × button closes the modal
- Entry data passed via `data-entry` JSON attribute on each `<tr>`

### 3. `years_consecutive_increases` Partial-Year Bug — FIXED
- **Root cause:** `ticker.dividends` includes the current (incomplete) year. If only 2 of 4 quarterly payments have been made, the current year total is lower than the previous year, breaking the consecutive streak at position 0.
- **Fix:** Both `calculate_years_consecutive_increases()` and `calculate_dividend_cagr()` now drop the current year from annual totals before comparing.
- This explains why most top-20 stocks showed 0 years despite being established dividend growers.
