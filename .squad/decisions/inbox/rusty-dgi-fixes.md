# Decision: DGI Screener Bug Fixes

**Date:** 2026-07
**Author:** Rusty (Agent Dev)
**Status:** Implemented

## Context
Basher's code review surfaced 5 critical and 3 moderate bugs in the DGI Screener pipeline. All were interface mismatches between dgi_screener.py (caller) and dgi_metrics.py / yfinance_fetcher.py (callees), plus a missing scheduler integration and missing config/deps.

## Decisions Made

1. **`days_on_list` starts at 1** — first day on list = day 1, not 0. This is more intuitive for users reading the dashboard.

2. **Technical indicator config passed as kwargs** — rsi_period, bb_period, bb_std from config are passed as keyword args only if present, otherwise the function defaults apply. This keeps the call site forward-compatible if new params are added to `calculate_technical_timing_score`.

3. **DGI scheduler follows options_chain pattern exactly** — same init → reschedule → trigger → display flow for consistency across all scheduler types.

## Team Impact
- Danny: config.yaml now has `dgi_screener` section — any future spec changes to filters/weights go there
- Linus: `calculate_quality_score` hardcodes weights internally (0.15/0.18/0.10/etc) — config weights are NOT passed through. If weights should be configurable, the function signature needs updating.
- Basher: All reported items addressed — ready for re-review
