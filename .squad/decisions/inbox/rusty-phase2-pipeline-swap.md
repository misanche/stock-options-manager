# Phase 2 — Pipeline Swap Decisions

**Agent:** Rusty  
**Date:** 2026-07  
**Scope:** Replace TradingView data fetching with yfinance provider

## Decisions Made

### 1. Clean cut — no fallback
Removed all TradingView import paths and error handling (403, Playwright) from active code. Old `tv_data_fetcher.py` and `tv_cache.py` remain in the repo but are unreferenced by any modified file.

### 2. Exchange prefix removed from fetch calls
Old pattern: `f"{exchange}-{symbol}"` or `f"{exchange}:{symbol}"` passed to TV fetcher.  
New pattern: plain `symbol` passed to `provider.fetch_all(symbol)`.  
The exchange field is still stored in CosmosDB and used for display/context but not for data fetching.

### 3. `parse_options_chain()` replaced with `json.loads()`
The yfinance provider returns pre-structured JSON (matching the same schema), so the HTML parser is no longer needed. Filter functions (`filter_options_chain_by_type`, etc.) still work unchanged.

### 4. Provider singleton pattern
- In web/app.py: `app.state.yf_provider` initialized at startup, passed to helper functions
- In agent wrappers: one `create_provider()` call per batch, shared across all symbols
- Provider has built-in in-memory cache (keyed by symbol, TTL from config)

### 5. API backward compatibility
The `preferences` dict key `"tradingview"` is kept in the chat/context API to avoid breaking the frontend. It now controls yfinance market data inclusion.

### 6. `has_data_error` / `data_error` flag removed
TV-specific 403 tracking removed entirely. The yfinance provider raises exceptions on failure rather than returning partial data with error flags.

## Open Items for Team
- Old TV files (`tv_data_fetcher.py`, `tv_cache.py`) can be deleted once Phase 2 is validated in production
- Linus's `options_chain_filters.py` will allow updating filter imports (Phase 3)
