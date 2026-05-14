# Decision: Market Status Card on Dashboard

**Author:** Linus (Quant Dev)
**Date:** 2026-07
**Status:** Implemented

## Context
David requested a visual market open/closed indicator on the dashboard.

## Decision
- Reused the existing `is_us_market_open()` probe from `src/market_hours.py` (MSFT ATM call bid/ask check, 5-min cache).
- Called it directly in the dashboard route handler and passed the boolean to the template — no new API endpoint needed.
- The probe call is synchronous but fast (cached most of the time). If it becomes a latency concern, we could move to an async background task that updates app state on a timer.

## Files Changed
- `web/app.py` — import + `market_open` in template context
- `web/templates/dashboard.html` — new `.summary-card-market` in summary row
- `web/static/style.css` — market dot styling using existing CSS vars

## Trade-offs
- First page load after cache expiry may be slightly slower (~1-2s for yfinance probe). Acceptable for a dashboard that's not latency-critical.
- No JS auto-refresh — the card reflects status at page load time. Could add a 5-min polling JS call later if desired.
