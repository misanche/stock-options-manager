# Decision: Hybrid Options Chain (yfinance + TradingView Playwright Fallback)

**Date:** 2026-07  
**Author:** Linus (Quant Dev)  
**Status:** Implemented  
**Impact:** Options chain data pipeline, Dockerfile, requirements

## Problem

yfinance returns zeroed bid/ask/IV/volume data when US markets are closed. Agents consuming the options chain see premium=0.0 for every contract during off-hours, making after-hours analysis impossible.

## Decision

Use a **targeted fallback**: yfinance for options chain when market is open, TradingView Playwright scraping when closed. Only the options chain uses this hybrid approach — overview, technicals, forecast, dividends stay yfinance 24/7.

## Key Design Choices

1. **Market hours detection** (`src/market_hours.py`): Rule-based, no external dependencies. Covers 10 NYSE holidays, handles weekend adjustment. Uses `pytz` (already in deps).

2. **TradingView fetcher is standalone** (`src/tv_options_chain_fetcher.py`): Recovered from old `main:src/tv_data_fetcher.py` but fully self-contained. Includes its own parser that transforms TradingView scanner fields into the exact same JSON structure as yfinance output.

3. **Output format is identical**: Both paths produce the same strike-keyed dict with the same fields. Added `market_status` field ("open"/"closed") so consumers CAN detect which path was taken, but don't NEED to change their logic.

4. **Graceful degradation**: If Playwright fails (missing browser, TradingView blocks, timeout), falls back to yfinance zeros. Never crashes.

5. **Dockerfile adds Playwright Chromium**: `playwright install chromium --with-deps` after pip install.

## Files Changed

- `src/market_hours.py` — NEW
- `src/tv_options_chain_fetcher.py` — NEW
- `src/yfinance_data_provider.py` — Modified `_build_options_chain()`
- `requirements.txt` — Added playwright, beautifulsoup4
- `Dockerfile` — Added Playwright browser install step
