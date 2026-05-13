

---


### Context Injection for Agent Execution (2026-03-28T13:48)
**By:** dsanchor (via Copilot)  
**What:** Include last 2 decisions (configurable 0–5) for the symbol/position being analyzed. Signals embedded in decisions, not separate context.  
**Why:** Simplifies context injection model. Decisions are primary unit.  
**Impact:** Changes `src/context.py`, `config.yaml` defaults, agent runner context injection logic.  
**Status:** ✅ Implemented in Phase 2

---

## Backend / Infrastructure

### Switch from Azure CLI Credential to API Key Authentication
**Date:** 2025-07-XX  
**Decider:** Rusty (Backend Dev)  
**Status:** Implemented

Switched from `AzureCliCredential` to API key authentication for Azure OpenAI. Simpler user setup (env var only), better Docker compatibility, reduced dependencies. Updated `AzureOpenAIChatClient`, `config.yaml`, `requirements.txt`, and documentation.

**Files Changed:** `src/agent_runner.py`, `src/config.py`, `src/main.py`, `config.yaml`, `requirements.txt`, `README.md`  
**Commit:** c502632

---

### Dockerfile Architecture for Playwright MCP
**Date:** 2025-07  
**Agent:** Rusty  
**Status:** Implemented

Single-stage `python:3.12-slim` base with Node.js installed via NodeSource. Pre-caches Playwright browsers during build. ENTRYPOINT pattern allows natural flag appending (`--web-only`, `--port`).

**Volume mount contract:**
- `data/` — Watchlists, position files (read-write)
- `logs/` — JSONL decision/signal logs (read-write)
- `config.yaml` — Configuration (read-only)
- `~/.azure` — Azure CLI credentials (read-only)

---

### Render-time Signal Enrichment from Decisions
**Author:** Rusty  
**Date:** 2025-07  
**Status:** Implemented

Enrich signals at render time in `web/app.py` by matching each signal to the closest decision (same symbol key, ±2 hour window). Helper `_enrich_signal_from_decisions()` copies only missing fields. Keeps signal JSONL compact.

---

## Performance & Reliability

### Chat Context Preload Pattern
**Date:** 2025-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  

Per-symbol chat previously fetched CosmosDB config + last 5 activities + TradingView data on every message (~5-10s latency). Split into two endpoints:

1. `POST /api/symbols/{symbol}/chat/context` — Heavy data fetch, runs once on page load
2. Chat message endpoint — Accepts optional `context` field, uses cached context if provided

**Result:** Chat response time drops from ~8-12s to ~2-3s per message (after initial load).

**Key Choices:**
- POST (TradingView fetch is a side effect)
- Optional context field (backward compatible)
- Extracted helpers `_build_symbol_context()` and `_build_symbol_system_prompt()` to avoid duplication

---

## Data Management

### Runtime Telemetry Infrastructure
**Date:** 2025-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  

Added a second CosmosDB container (`telemetry`) to track runtime performance stats for agent executions and TradingView data fetching.

**Design:**
- Separate container with partition key `/metric_type` (operational data separate from business data)
- Best-effort initialization (system works without telemetry container)
- 30-day TTL on all telemetry docs (per-document, no manual cleanup)
- Fetcher stores stats in `self.last_fetch_stats`; caller (AgentRunner) handles write (decoupling)
- Telemetry writes post-execution in separate try/except (never masks real errors)
- Python-side aggregation for `get_telemetry_stats()`

**Impact:** Settings page shows runtime stats card; no changes to agent logic or activity/signal flow.

---

### Position Rollover Design

#### Roll Position — Atomic Single-Write
**Date:** 2025-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  

Rolling a position (close old, open new with same monitor-agent signal) happens with a single in-memory operation and single `replace_item` CosmosDB call. Avoids partial-write states.

**Traceability:**
- Old position → `rolled_to: <new_position_id>` + `closing_source: {snapshot}`
- New position → `rolled_from: <old_position_id>` + `source: {snapshot}`
- Both snapshots reference same `decision_id` from monitor signal

**No Watchlist/Cascade Side Effects:** Unlike "Open Position from Activity" (watch agents), roll endpoint does NOT disable watchlist flags or cascade-delete activities. Monitor agents track open positions — disabling would break monitoring.

---

#### Cascade runs after watchlist flag is persisted
**Date:** 2025-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  

When a user toggles off a watchlist agent (covered_call or cash_secured_put), cascade delete runs AFTER the watchlist document update is persisted (`replace_item`), not before.

**Reasoning:** If cascade fails mid-way, flag is already `False` — UI correctly shows agent as disabled. Orphaned activities/signals are harmless and would be cleaned up on subsequent toggle-off or manual cleanup.

---

### Render-time Alert Enrichment from Activities
**Date:** 2025-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  

Enrich alerts at render time in `web/app.py` by matching each alert to the closest activity (same symbol key, ±2 hour window). Helper `_enrich_alert_from_activities()` copies only missing fields. Keeps alert JSONL compact.


---

## Data Fetching & Backend Architecture

### Refactor TradingView Fetchers from Playwright to BeautifulSoup + Scanner API
**Date:** 2026-07-14  
**Author:** Rusty (Backend Dev)  
**Status:** Implemented  
**Impact:** Performance, reliability, resource usage  

All 5 TradingView data fetchers in `src/tv_data_fetcher.py` used Playwright (headless Chromium) to load full pages and extract innerText. This was heavyweight — every fetch launched browser tabs, waited for networkidle, and pulled raw unstructured text.

Test scripts (`test/test_fetcher.py`, `test/test_dividends_fetcher.py`, `test/test_technicals_fetcher.py`, `test/test_forecast_fetcher.py`) proved that 4 of 5 resources could be fetched via plain HTTP requests + BeautifulSoup, with a scanner API fallback.

**Decision:** Switch overview, technicals, forecast, and dividends to **requests + BeautifulSoup + TradingView scanner API**. Keep Playwright **only** for options chain (requires browser-level API interception).

**Key Changes:**
1. **4 fetchers refactored** — multi-strategy: HTML extraction → embedded JSON → scanner API
2. **Options chain unchanged** — still Playwright with response interception
3. **Lazy browser init** — Playwright only starts when options chain is needed
4. **Structured JSON output** — fetchers return `json.dumps()` with typed fields instead of raw page text
5. **Added `beautifulsoup4>=4.12.0`** to requirements.txt

**Trade-offs:**
- **Pro:** ~10x faster fetches (no browser startup), lower memory, structured data for LLM analysis
- **Pro:** Playwright failure modes (timeouts, consent banners, JS rendering) eliminated for 4/5 resources
- **Pro:** Lazy browser means Playwright isn't loaded at all when options chain isn't requested
- **Con:** Depends on TradingView's HTML structure / scanner API stability (same as test scripts)
- **Con:** Return format changed from plain text to JSON string — callers that parsed raw text may need adjustment (current callers just pass strings through, so no impact)

**Implications:**
- All callers (`agent_runner.py`, `web/app.py`, agent wrappers) are unchanged — they call `fetch_all()` which returns `dict[str, str]`
- LLM agents now receive structured JSON instead of raw page dumps — potentially better analysis quality
- If TradingView changes their scanner API or page structure, the 3-strategy fallback provides resilience

---

### Use Playwright Locators for Targeted Data Extraction
**Date:** 2025-01-XX  
**Author:** Rusty (Backend Dev)  
**Status:** Implemented  

The original `fetch_overview` method grabbed the entire `#tv-content` innerText, which returned excessive noise. We needed a more surgical approach to extract only the "Fundamentals and stats" section.

**Decision:** Rewrote `fetch_overview` to use Playwright's locator API:
1. Locate the H1 element containing "Fundamentals and stats"
2. Traverse to its parent container using `.locator('..')`
3. Extract only that container's inner text

**Implementation Details:**
- Uses `page.locator('h1:has-text("Fundamentals and stats")').locator('..')`
- Includes fallback to old `_fetch_page_text()` approach if locator fails
- Maintains retry wrapper compatibility
- Proper page lifecycle management with finally block

**Rationale:**
- Reduces noise in overview data by targeting specific DOM section
- More resilient than hardcoded CSS selectors (semantic text-based targeting)
- Graceful degradation ensures system doesn't break if page structure changes
- Pattern can be applied to other fetch methods if similar issues arise

**Impact:**
- Overview data should be cleaner and more focused on fundamental metrics
- Slightly more complex code, but better failure handling with fallback
- No breaking changes to return format or API contract

**Future Considerations:**
- Monitor success rate of locator approach vs. fallback usage
- Consider applying same pattern to `fetch_technicals`, `fetch_forecast`, etc. if they have similar noise issues
- If TradingView changes page structure, fallback ensures continuity

---|---|---|
| >30 days | Open normally | None |
| 15-30 days | Allow if exp ≥7d before earnings | `earnings_approaching` |
| 7-14 days | Allow if exp ≥5d before earnings (caution) | `earnings_soon` |
| <7 days | Block | `earnings_imminent` |
| 0-2 days after | Ideal | None |
| Unknown | Conservative DTE (<21d CC, <30d CSP) | `unknown_earnings` |

**Rationale:** The risk is the position being open during earnings, not earnings existing on the calendar. Pre-earnings IV inflation produces better premiums — sellers should capture this when expiration is safely before the event.

**Files Changed:**
- `src/tv_covered_call_instructions.py` — 6 sections updated
- `src/tv_cash_secured_put_instructions.py` — 6 sections updated

---

### Alert Pre-fill Pattern for Position Forms

**Date:** 2026-07  
**Author:** Rusty  
**Status:** Implemented  

Alert data for position pre-fill is embedded as JavaScript objects in the page (via `latest_sell_alerts` template variable) rather than fetched via API. The backend extracts the latest SELL alert per watchlist agent type from the already-fetched alerts list — no extra CosmosDB query needed.

**Rationale:**
- Instant UX: checking the checkbox fills the form with zero latency
- No new API endpoints to maintain
- Reuses the same alert field set as the existing `from-activity` endpoint's `source` dict
- The checkbox is purely a convenience — it pre-fills but doesn't create any link between the position and the alert

**Pattern:**
- `latest_sell_alerts` dict keyed by agent_type (`covered_call`, `cash_secured_put`)
- Frontend maps position type to agent type: `call → covered_call`, `put → cash_secured_put`
- Checkbox visibility gated by BOTH watchlist enabled AND alert exists with valid strike+expiration

---

### Alert Checkbox Attaches Source Metadata, Does Not Pre-fill Form

**Date:** 2026-07  
**Author:** Rusty  
**Status:** Implemented  

The alert checkbox on the Add Position form was pre-filling strike/expiration/notes from alert data. User wanted it to transparently attach alert source metadata instead, with no form field changes.

**Decision:**
- Checkbox sends `source_activity_id` in POST body to `/api/symbols/{symbol}/positions`
- Backend looks up the activity and builds the same `source` dict used by the from-activity route
- Source metadata is stored on the position document but does NOT affect form fields
- No side effects: no watchlist disable, no cascade-delete

**Files Changed:**
- `web/app.py` — `api_add_position` route accepts optional `source_activity_id`
- `web/templates/symbol_detail.html` — removed `applyAlertPrefill()`, updated label and submit logic

---

### Monitor Earnings Decision Matrix

**Author:** Linus (Quant Dev)  
**Date:** 2026-07-16  
**Status:** Implemented  
**Commit:** f587058

The analysis agents had a sophisticated Earnings Decision Matrix but the monitor agents had only 3-5 lines of vague earnings handling. A monitor recommended selling a call with expiration AFTER earnings without flagging it.

**Decision:** Port the Earnings Decision Matrix to both monitor instruction files, adapted for monitoring (HOLD/FLAG/ROLL/CLOSE) rather than opening (OPEN/AVOID/BLOCK).

**Key Design Choices:**
1. **Same tier structure** as analysis agents (>30d, 15-30d, 7-14d, <7d, just-passed, unknown) for consistency
2. **Expiration-vs-earnings is the primary axis**: "Does my position span earnings?" drives the action
3. **Urgency escalation**: FLAG → ROLL recommended → ROLL urgently → CLOSE as earnings get closer
4. **Override rule**: When earnings risk is urgent and position spans earnings, it overrides favorable Greeks
5. **Legacy compatibility**: `earnings_before_expiry` retained as alias for `earnings_within_dte`
6. **Put-specific additions**: earnings miss gap risk and downgrade clustering added to put monitor only

**Impact:**
- Both monitor agents now apply the same earnings risk rigor as analysis agents
- Risk flags are consistent across all 4 agent types (CC, CSP, call monitor, put monitor)
- JSON output examples updated to demonstrate correct flag usage

**Files Changed:**
- `src/agents/tv_open_call_instructions.py` — 10-tier earnings assessment, risk flags, HOLD/FLAG/ROLL/CLOSE actions
- `src/agents/tv_open_put_instructions.py` — 10-tier earnings assessment with put-specific gap risk and downgrade handling

---

### Client-side Markdown Rendering for Chat

**Date:** 2026-07-22  
**Author:** Rusty  
**Status:** Implemented  
**Commit:** 23c0817  

LLM chat responses contain markdown formatting (`**bold**`, `# headers`, `- lists`, tables) that was displayed as raw text.

**Decision:**
- Use `marked.js` via CDN (`https://cdn.jsdelivr.net/npm/marked/marked.min.js`) loaded in `base.html`
- Only assistant messages get markdown rendering; user messages remain plain text
- Assistant bubbles get `.markdown-body` class with dedicated CSS for tables, code blocks, lists, headers, blockquotes
- Graceful fallback: if `marked` fails to load, messages render as plain text

**Files Changed:**
- `web/templates/base.html` — added marked.js CDN script tag
- `web/templates/chat.html` — updated `addMessage()` for markdown rendering
- `web/templates/symbol_chat.html` — same update
- `web/static/style.css` — added `.markdown-body` and child element styles

---

### Risk & Moneyness columns on Symbol Detail positions table

**Date:** 2026-07-15  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  
**Commit:** e8d56c8

The dashboard already showed assignment_risk and moneyness for position monitors, but the symbol detail page's positions table lacked this data — requiring users to scroll through activities to find the risk status of each open position.

**Decision:** Enrich positions in the symbol detail route by scanning the already-fetched activities for the latest monitor activity per `position_id`. Attach `_assignment_risk` and `_moneyness` as transient fields (underscore prefix = not persisted). Reuse existing CSS classes from the dashboard.

**Impact:**
- **Files changed:** `web/app.py`, `web/templates/symbol_detail.html`, `web/static/style.css`
- **No new queries:** Reuses the activities already fetched for the page; zero additional CosmosDB calls.
- **Fallback:** Positions without monitor data show "—" gracefully.

---

### Settings must always be read from CosmosDB first

**Date:** 2026-07  
**Author:** Rusty  
**Status:** Implemented  

On deploy, user-configured settings (scheduler cron, timezone, telegram config) were being displayed incorrectly on the dashboard. The root cause: the dashboard route read settings from `config.yaml` (which resets to defaults with every new container image), while the Settings/Config page correctly read from CosmosDB.

**Decision:** All web routes that display or use user-configurable settings MUST read from CosmosDB first, falling back to `config.yaml` only if CosmosDB is unavailable.

**Pattern:**
```python
cosmos_settings = _load_settings_from_cosmos(cosmos)
config = cosmos_settings if cosmos_settings else _load_config()
```

**Exceptions:** Connection credentials (`azure.*`, `cosmosdb.*`) should still come from `config.yaml` / env vars since they are infrastructure config, not user settings.

**Changes Made:**
- `web/app.py` dashboard route: CosmosDB-first for scheduler cron/timezone
- `web/app.py` telegram test route: CosmosDB-first for telegram settings
- `web/app.py` settings save: now passes timezone to `scheduler.reschedule()`

**Notes:**
- The `merge_defaults()` logic in `cosmos_db.py` is correctly implemented (never overwrites existing keys)
- The startup banner in `run.py` still reads from `config.yaml` since CosmosDB isn't initialized yet — cosmetic only, acceptable


---

### Unified Mandatory Earnings Gate

**Date:** 2026-07-09
**Author:** Linus (Quant Dev)
**Status:** Implemented
**Impact:** Team-wide (changes agent output schema)

The LLM was ignoring the Earnings Decision Matrix (added in ccf299a) because it was buried at section 8/9 among many other analytical sections. A watcher agent recommended selling a call with expiration AFTER earnings, with no earnings flag. The matrix wasn't prominent enough for the LLM to consistently follow.

**Decision:** Created a **MANDATORY EARNINGS GATE** that runs as the FIRST analytical step (before technicals, volatility, fundamentals) in all 4 instruction files.

**Key Design Choices:**

1. **Gate-before-analysis architecture**: The earnings check is a pre-flight gate, not one section among many. If it returns BLOCKED, the agent must output WAIT/CLOSE immediately — it never reaches the technical analysis.

2. **Mandatory `earnings_analysis` output object**: Every JSON response now MUST include an `earnings_analysis` object with computed fields (next_earnings_date, days_to_earnings, expiration_to_earnings_gap, earnings_gate_result, earnings_risk_flag). This forces the LLM to explicitly reason about earnings timing before recommending. If it must fill in the fields, it can't skip the logic.

3. **HARD OVERRIDE RULE**: Explicit language stating no combination of bullish technicals, strong fundamentals, or favorable IV can override a BLOCK. This is a binary gate, not a weighted factor.

4. **Unified terminology across all 4 files**: Same thresholds, same flag names, same matrix structure. Only the actions differ (watchers: OPEN/WAIT; monitors: HOLD/ROLL/CLOSE).

**Implications for Team:**

- **Rusty (Infrastructure)**: The JSON output schema now includes `earnings_analysis` as a required field. If any downstream parsing depends on the schema, it should be updated to expect this new object. The agent_runner's JSON extraction should handle it transparently since it parses the full JSON block.

- **Schema change**: All agents now output `earnings_analysis` in every response. This is a non-breaking addition (new field, existing fields unchanged).

- **Testing**: Recommend testing with a symbol where earnings are 10-20 days away to verify the gate correctly blocks positions that span earnings.

**Files Changed:**
- `src/tv_covered_call_instructions.py`
- `src/tv_cash_secured_put_instructions.py`
- `src/tv_open_call_instructions.py`
- `src/tv_open_put_instructions.py`

**Commit:** b51ea1a

------|------------|-----------|
| Session creation overhead | Medium | ~50ms per session, negligible vs. 5–15s network I/O per symbol |
| IP-based blocking persists | Low | Monitor 403 rates; if problem persists, user deploys with proxy rotation (out of scope v1) |
| Exponential backoff increases runtime | Medium | Worst case 3 retries × 45s per symbol; for 50 symbols with 10% failure rate, adds ~11 min total (acceptable for 4-hour cron) |
| Randomization breaks determinism | Low | Already configurable; keep default true (high value) |

### Configuration Changes Summary

**New `config.yaml` section (Phase 1–4):**
```yaml
tradingview:
  request_delay_min: 1.0         # Existing
  request_delay_max: 3.0         # Existing
  
  # NEW: Anti-403 settings
  warmup_enabled: false          # Phase 4: Visit homepage before fetching
  max_403_retries: 3             # Phase 2: Retry attempts on 403
  retry_delays: [5, 15, 45]      # Phase 2: Exponential backoff (seconds)
  randomize_symbols: true        # Phase 3: Shuffle symbol order
```

**Defaults:** Conservative (warmup off, randomize on)

### Implementation Checklist

- [ ] Phase 1: Core Session Isolation (Rusty)
  - [ ] Refactor 4 agent wrappers — move `async with create_fetcher()` inside symbol loop
  - [ ] Remove `self.has_403` from fetcher
  - [ ] Update `fetch_all()` to return `{"error_403": "message"}` in result dict
  - [ ] Update `agent_runner.py` to check `data.get("error_403")`
  
- [ ] Phase 2: Graduated Recovery (Rusty)
  - [ ] Replace `_check_403()` with `_fetch_with_403_recovery()` implementing exponential backoff + session refresh
  - [ ] Update all `self._session.get()` calls to use new recovery method
  - [ ] Add config: `max_403_retries`, `retry_delays`
  
- [ ] Phase 3: Symbol Randomization (Rusty)
  - [ ] Add `random.shuffle(cc_symbols)` in all 4 agent wrappers after `cosmos.get_*_symbols()`
  - [ ] Add config: `randomize_symbols` (default: true)
  
- [ ] Phase 4: Optional Warm-Up (Rusty)
  - [ ] Add `_warmup()` method to `TradingViewFetcher`
  - [ ] Call `await self._warmup()` at start of `fetch_all()` if enabled
  - [ ] Add config: `warmup_enabled` (default: false)
  
- [ ] Testing (Basher)
  - [ ] Verify each symbol gets fresh session
  - [ ] Simulate 403 (firewall block); verify retry + recovery
  - [ ] Verify symbol order randomized when enabled
  - [ ] Monitor 403 rates before/after deployment

### Alternatives Considered (and Rejected)

| Alternative | Why Rejected |
|-------------|-------------|
| Proxy rotation | Requires external infrastructure. If IP-based blocking persists, user can deploy to multiple VMs later. |
| Playwright for all resources | 10x slower (~15s vs ~1s per resource); would increase runtime from ~5min to ~40min for 50 symbols. Only justified for options chain (requires browser API interception). |
| Per-resource session rotation | Too granular (5 resources × 50 symbols = 250 sessions likely triggers rate-limiting). Per-symbol isolation is sweet spot. |
| TradingView API keys | TradingView doesn't offer public API for retail users. |

### Approval & Next Steps

**Decision:** Pending user (dsanchor) review and approval.

**If Approved:**
1. Rusty implements Phase 1–2 (core changes)
2. Basher validates with real TradingView access
3. Monitor 403 rates for 1 week post-deployment
4. Deploy Phase 3–4 if additional improvement needed

**Alignment with Team Proposals:**

Danny's "Per-Symbol Session Isolation" proposal prioritizes simpler per-symbol lifecycle (always fresh session per symbol). Linus's "TV Fetcher 403-Resilience Analysis" proposes hybrid with request-count thresholds.

**Resolution:** Both converge on core strategy. Danny's simpler approach preferred for MVP implementation; Linus's threshold optimization can be Phase 5 enhancement if needed.

### Related Files

- `.squad/decisions/inbox/danny-anti403-strategy.md` (detailed Danny proposal)
- `.squad/decisions/inbox/linus-anti403-implementation.md` (detailed Linus proposal)
- `.squad/orchestration-log/2026-04-06T14-00-danny-antibot.md` (Danny task log)
- `.squad/orchestration-log/2026-04-06T14-00-linus-antibot.md` (Linus task log)
- `.squad/log/2026-04-06T14-00-anti403-strategy.md` (Session summary)

---

## Symbol Position Report — LLM Endpoint Pattern

**Date:** 2026-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented

### Decision

Added a new LLM report generation endpoint (`POST /api/symbols/{symbol}/report`) that follows the same Azure OpenAI calling pattern as `symbol_chat_api` but with:
- Higher `max_completion_tokens` (4096 vs 2048) for comprehensive reports
- Per-agent-type activity loading (last 3 each) instead of mixed last-3-overall
- Cache-only TradingView data (no `force_refresh`) for speed
- Structured Spanish-language system prompt with 7 mandatory sections

### Rationale

- Reports need more token budget than chat replies since they cover all sections
- Per-agent activity breakdown gives better context than the chat's mixed approach
- Using cache avoids 30-60s TradingView fetches during interactive report generation
- Spanish output matches the user's communication language

### Impact

- `web/app.py`: New endpoint between fetch-preview page route and fetch-preview API
- `web/templates/symbol_detail.html`: Report button + modal overlay + markdown renderer
- No changes to existing endpoints or data models

### Related Files

- `.squad/orchestration-log/2026-04-18T0827-rusty-report.md` (Agent routing log)
- `.squad/log/2026-04-18T0827-symbol-report.md` (Session summary)


---

## Centralized Options Chain Schema Description

**Date:** 2026-07-25  
**Author:** Linus (Quant Dev)  
**Status:** Implemented

### Decision

All agent prompts, chat contexts, and reports that include options chain data now prepend a standardized schema description (`OPTIONS_CHAIN_SCHEMA_DESCRIPTION` from `src/options_chain_parser.py`). This ensures every LLM receiving options chain data knows the JSON structure and field semantics.

### Rationale

Agents were receiving raw JSON without context on what fields mean — especially critical fields like `iv` (decimal, not percentage), `delta` (sign convention), and `theta` (negative = decay). This led to potential misinterpretation in analysis.

### Impact

- The constant is defined once in `options_chain_parser.py` and imported everywhere
- Any new injection point for options chain data should import and prepend `OPTIONS_CHAIN_SCHEMA_DESCRIPTION`
- No logic changes — only documentation added to prompts

---

## Filter TradingView Scanner Responses by totalCount

**Date:** 2026-07-25  
**Author:** Linus (Quant Dev)  
**Status:** Implemented  
**Impact:** Data quality for options chain fetching

### Context

The `fetch_options_chain` method intercepts TradingView scanner API responses matching `_OPTIONS_SCAN_URLS`. One of the intercepted responses contains `totalCount: 1` — it's metadata/noise, not actual option chain data. This polluted the captured data sent downstream.

### Decision

Filter responses at capture time inside `_on_response`: parse the JSON body and discard any response where `totalCount <= 1`. Responses that fail JSON parsing are kept (safe default).

### Rationale

- Filtering at the callback level prevents garbage from ever entering `captured_responses`
- `totalCount > 1` is a reliable discriminator: real option chain data always has multiple rows
- Non-JSON responses are allowed through as a safe fallback (shouldn't happen for these endpoints, but defensive)

### Files Modified

- `src/tv_data_fetcher.py` — `_on_response` callback in `fetch_options_chain`

# Decision: Enforce Hard 45 DTE Cap for New Positions

**Date:** 2026-07  
**Author:** Linus (Quant Dev)  
**Status:** ✅ Implemented  
**Impact:** Agent instructions (CC + CSP), user-facing recommendations

## Problem

User reported seeing expiration recommendations with DTE > 45 days too frequently. Root cause: instructions said "Optimal: 30-45 DTE" but "Avoid: >60 DTE", creating a 46-60 day gap the LLM treated as permitted. Additionally, the earnings gate post-earnings path could push expirations beyond 45 DTE.

## Decision

45 DTE is now a **hard maximum** for all new covered call and cash-secured put positions. If no expiration ≤45 DTE passes all criteria (earnings gate, Greeks, premium), the agent outputs WAIT instead of extending to a longer-dated expiration.

## Changes Made

Both `src/tv_covered_call_instructions.py` and `src/tv_cash_secured_put_instructions.py`:
1. Replaced "Avoid >60 DTE" with "⛔ HARD MAXIMUM: 45 DTE"
2. Added DTE ≤ 45 guard to earnings gate post-earnings allowance row
3. Added 45 DTE cap to DTE Selection Priority and KEY PRINCIPLE sections
4. Added "No Eligible Expiration ≤ 45 DTE" as explicit WAIT trigger
5. Added "Never exceed 45 DTE" to Theta descriptions

## Follow-up Needed

- Alpha Vantage and Massive.com instruction files likely have the same ">60 DTE" gap — should be audited and patched.

---

# Decision: Risk fields in Telegram notifications

**Date:** 2026-07
**Author:** Rusty
**Status:** Implemented

## Context
Telegram sell alerts already displayed `risk_rating` but it was never passed in the alert_data dict from agent_runner. Roll alerts had no risk info at all.

## Decision
- Sell alert_data now includes `risk_rating` (from agent JSON output)
- Roll alert_data now includes `assignment_risk` (from agent JSON output)
- Roll alert formatting shows "Assignment Risk: {value}" when present
- Summary agent instructions now guide inclusion of risk levels for notable cases

## Convention
When adding new fields to Telegram notifications, ensure both sides are wired: the alert_data dict in agent_runner.py AND the formatter in telegram_notifier.py. Fields should be optional (guarded with `if X is not None`) for backward compatibility.

---

# Decision: Always filter options chains by delta before passing to agents

**Date:** 2026-04-22  
**Author:** dsanchor (User)  
**Status:** Implemented  
**Initiated by:** Copilot directive 2026-04-22T05:01:55Z

## Context
Agents receive full options chains which include deep ITM/OTM contracts with extreme or missing deltas. These contracts are noise — agents rarely recommend them and they bloat the context window. User directive to standardize filtering across all data flows.

## Decision
Apply a delta filter in `_format_options_chain()` after position filtering but before JSON serialization:
- **Calls:** keep delta 0.15–0.90
- **Puts:** keep delta -0.60 to -0.15
- **Missing delta:** excluded

Default ranges are configurable via function parameters if future agents need different windows.

## Impact
- Reduces token usage in agent prompts (fewer contracts serialized)
- Agents focus on the most actionable strike range
- No behavioral change for agents that were already ignoring extreme-delta contracts

---

# Decision: Dashboard tables show activity timeline badges instead of count columns

**Date:** 2026-04-22  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  
**Commit:** be9c812

## Context
The dashboard agent tables previously showed Today/7d/30d alert count columns which were low-signal — a count of "3" doesn't tell you *what* happened. The activity feed below already had rich colored badges showing actionable results.

## Decision
- Replaced 3 count columns with a single "Recent" column containing up to 3 activity badges (oldest→newest) per row.
- Badges use the same `badge-{{ activity | lower }}` CSS classes as the activity feed for consistency.
- Each badge links to its activity detail page and has a timestamp tooltip.
- Removed the top summary cards for Alerts Today/7d/30d (kept Symbols Watched + Open Positions).
- `grand_totals` dict is preserved in the backend for any future use but no longer rendered.

## Trade-offs
- Loses exact numeric counts per time range (can still be seen in the activity feed with filters).
- Gains at-a-glance pattern recognition: seeing `[WAIT] › [WAIT] › [SELL]` is immediately actionable.

## Files Modified
- web/templates/dashboard.html
- web/app.py
- web/static/style.css

---

# Decision: Monitor Agent Split — Position Monitor + Roll Management

**Date:** 2026-04-22
**Author:** Danny (Lead)
**Status:** Recommended — awaiting user approval
**Impact:** Agent instructions, agent_runner.py, runner execution flow, instruction files

## Proposal (from dsanchor)

Split each monitor agent (open_call_monitor, open_put_monitor) into two sequential agents:
1. **Position Monitor** — Decides WAIT vs action (CLOSE/ROLL). Ends at WAIT.
2. **Roll Management** — When action ≠ WAIT, takes over to determine specific strike, expiration, premium using the option chain.

Goal: Simplify each agent's context so the roll agent focuses on reading the chain correctly, fixing credit miscalculations.

## Assessment

### Root Cause of Credit Miscalculation

The current monitor instructions are **589 lines (call) / 603 lines (put)**. A single agent must:

1. Run a 25-row earnings decision matrix (lines 62–100)
2. Execute 8 analysis dimensions (moneyness, DTE, delta/gamma, volume, ex-div, earnings, technicals, IV — lines 174–258)
3. Apply profit optimization gates (3 mandatory + 4-of-7 flexible conditions — lines 294–323)
4. **Then**, for ROLL decisions, correctly look up specific contracts by JSON key path (e.g., `calls["20260427"]["475.0"]["ask"]`)
5. Calculate roll economics arithmetic (buyback_cost - new_premium) per the premium-first policy (lines 331–393)
6. If initial candidate fails, run the roll search algorithm across multiple strikes/expirations (lines 369–378)

The options chain schema description (`OPTIONS_CHAIN_SCHEMA_DESCRIPTION` in `options_chain_parser.py`, 75 lines) is prepended to the chain JSON in the user message. The roll economics verification rules are buried at line ~340 of 589 total instruction lines.

**Diagnosis:** The model's attention is diluted across ~600 lines of instruction covering 8+ analysis dimensions. By the time it gets to the chain lookup (the most precise, arithmetic-heavy task), it has already consumed significant context processing the earnings matrix, fundamentals, technicals, and WAIT/ROLL decision logic. The chain reading task requires exact key-path navigation and bid/ask arithmetic — precisely the type of task that degrades under context pressure.

### Instruction Content Breakdown (Open Call Monitor)

| Section | Lines | Agent 1 needs? | Agent 2 needs? |
|---------|-------|----------------|----------------|
| Role + Strategy + Data Source | ~60 | ✅ | Partial (role only) |
| Earnings Gate (25-row matrix) | ~100 | ✅ | ❌ (receives result) |
| Earnings override + roll target rules | ~60 | ✅ | ✅ (roll target rules only) |
| Position context | ~10 | ✅ | ✅ (receives from Agent 1) |
| Analysis framework (8 dimensions) | ~100 | ✅ | ❌ |
| WAIT/ROLL criteria + triggers | ~30 | ✅ | ❌ |
| Roll types | ~15 | Partial | ✅ |
| Profit optimization gate | ~40 | ✅ | ❌ (Agent 1 decides) |
| Premium-first roll policy + search algo | ~70 | ❌ | ✅ |
| Output format + examples | ~130 | ~60 (WAIT only) | ~100 (ROLL + economics) |

**Agent 1 estimated size: ~350-400 lines** (everything except roll economics/search, reduced output examples)
**Agent 2 estimated size: ~200-250 lines** (roll types, premium-first policy, search algo, chain schema, output format)

### Data Flow Analysis

Current flow (`agent_runner.py` lines 433–528):
```
fetch_all() → [overview + technicals + forecast + options_chain] → single agent → activity JSON
```

Options chain is filtered by `filter_options_chain_for_position()` (±15 strikes) and `filter_options_chain_by_delta()` before injection.

Proposed flow:
```
fetch_all() → [overview + technicals + forecast + minimal chain*] → Agent 1 → WAIT? done
                                                                               → ROLL? → [chain + Agent 1 output + pivot points] → Agent 2 → activity JSON
```

*Agent 1 still needs the current contract's delta/IV for its analysis (single contract lookup). Could pass just the current expiration's row rather than the full filtered chain.

### Token Economics

~70-80% of monitor runs result in WAIT. For those runs:
- **Current:** Full chain processed, all 600 lines consumed, full response generated → wasted chain tokens
- **Proposed:** Agent 1 runs with minimal chain context, produces WAIT → done. Agent 2 never invoked.

For the ~20-30% that result in ROLL:
- **Current:** 1 API call
- **Proposed:** 2 API calls, but Agent 2's context is ~60% smaller instruction-wise

Net: likely token savings overall, with slightly higher latency for ROLL cases (~5-10s extra).

### Technical Handoff Design

Agent 1 output (when action ≠ WAIT) becomes Agent 2 input:

```json
{
  "action_needed": "ROLL_UP_AND_OUT",
  "symbol": "MO",
  "exchange": "NYSE",
  "current_strike": 72,
  "current_expiration": "2026-04-24",
  "underlying_price": 73.80,
  "moneyness": "ITM",
  "delta": 0.62,
  "assignment_risk": "critical",
  "earnings_analysis": { ... },
  "risk_flags": ["approaching_itm", "earnings_soon"],
  "reason": "Stock broke through $72 strike with bullish momentum...",
  "confidence": "high",
  "pivot_points": { ... }
}
```

Agent 2 receives this + the full filtered options chain + roll-specific instructions. Produces the final activity JSON (same schema as today, with `roll_economics` populated).

### Runner Impact (`agent_runner.py`)

`run_position_monitor()` (lines 433–665) becomes a 2-phase method:

```python
async def run_position_monitor(self, ...):
    # Phase 1: Position assessment
    phase1_result = await self._run_position_assessment(...)
    
    if phase1_result["activity"] in self._NON_ALERT_ACTIVITIES:
        # WAIT — persist and return
        cosmos.write_activity(...)
        return
    
    # Phase 2: Roll management
    final_result = await self._run_roll_management(
        phase1_output=phase1_result,
        options_chain=chain_data,
        ...
    )
    cosmos.write_activity(...)
```

Activity/alert persistence model is unchanged — the final JSON (whether from Agent 1 for WAIT or Agent 2 for ROLL) follows the same schema and gets written the same way.

### Pros

1. **Directly addresses the credit problem**: Agent 2 has ~200-250 lines focused purely on chain reading, roll economics, and search. No earnings matrix, no 8-dimension analysis, no fundamental checks competing for attention.
2. **Token savings on majority case**: ~70-80% of runs are WAIT → Agent 2 never invoked → chain tokens saved.
3. **Easier debugging**: Credit wrong? It's Agent 2. Decision wrong? It's Agent 1. Clean separation.
4. **Independent instruction tuning**: Can refine roll economics instructions without touching the position assessment logic.
5. **Extensible**: Agent 2 could eventually handle more complex multi-leg strategies without bloating the monitor.

### Cons / Risks

1. **Latency for ROLL cases**: Extra API call adds ~5-10s for non-WAIT decisions.
2. **Handoff contract maintenance**: Two instruction files per strategy (call/put) × 2 agents = 4 new files. Handoff schema must stay in sync.
3. **Agent 1 still needs some chain data**: Current delta/IV requires at least the current contract. Solution: pass only the current expiration+strike row to Agent 1, not the full chain.
4. **Agent 2 may need some technicals**: Roll candidate selection references pivot points (R1/R2/R3 for calls, S1/S2/S3 for puts). Solution: extract pivot points from technicals and pass to Agent 2 (small payload).
5. **Profit optimization complexity**: The ROLL_DOWN/ROLL_UP optimization gate (3+4 conditions) straddles both agents — Agent 1 runs the gate conditions, Agent 2 does the economics. Need clean ownership split.

### Gotchas

1. **JSON schema consistency**: Agent 2 must produce the exact same output schema as the current unified format. No schema migration needed if done right.
2. **Error handling**: If Agent 2 fails/errors, need to persist Agent 1's output with a "roll_economics_unavailable" flag rather than losing the entire run.
3. **Profit optimization gate**: Currently lives entirely in the monitor instructions. Under the split, the gate decision (ROLL_DOWN/ROLL_UP for premium capture) should stay in Agent 1, with Agent 2 only executing the economics.

## Recommendation

**✅ SUPPORT the split.** The instruction complexity is the most likely cause of credit miscalculation, and the split directly addresses it by isolating the chain-reading task into a focused ~200-line agent. The 70-80% WAIT case saves tokens, and the 2-agent overhead for ROLL cases is acceptable.

### Suggested Implementation Approach

1. **New instruction files**: `tv_open_call_assessment_instructions.py` + `tv_open_call_roll_instructions.py` (same for put)
2. **Agent 1 gets**: Overview, technicals, forecast, current contract delta/IV only, previous context
3. **Agent 2 gets**: Full filtered chain, Agent 1's decision output, pivot points subset, roll-specific instructions
4. **Handoff format**: Define a strict intermediate JSON schema (above)
5. **Runner refactor**: Split `run_position_monitor()` into `_run_position_assessment()` + `_run_roll_management()` with conditional chaining
6. **Fallback**: If Agent 2 fails, persist Agent 1's output with `roll_economics: null` + `"roll_agent_error"` flag

### Team Assignment (proposed)

- **Linus**: Write the split instruction files (4 files: call_assessment, call_roll, put_assessment, put_roll)
- **Rusty**: Refactor `agent_runner.py` for 2-phase execution, define handoff schema
- **Basher**: Test end-to-end with known positions, verify credit calculations match chain data
- **Danny**: Review instruction split for coverage gaps, approve handoff schema

---

# Decision: Monitor Instruction Split — Implementation Details

**Date:** 2026-07-22
**Author:** Linus (Quant Dev)
**Status:** Implemented — pending Rusty's runner integration
**Relates to:** danny-monitor-split.md

## What Was Done

Created 4 new instruction files per Danny's architecture decision, splitting each monitor agent into Assessment (Agent 1) + Roll Management (Agent 2).

## Design Decisions

### 1. Function-based exports (not module-level constants)
The new files use `get_open_call_assessment_instructions()` functions instead of `TV_OPEN_CALL_INSTRUCTIONS` constants. This allows future parameterization if needed (e.g., passing position-specific context into the prompt template).

### 2. Roll instructions import OPTIONS_CHAIN_SCHEMA_DESCRIPTION
Agent 2 files do `from src.options_chain_parser import OPTIONS_CHAIN_SCHEMA_DESCRIPTION` and inject it via f-string. This keeps the chain schema DRY — single source of truth in options_chain_parser.py.

### 3. Handoff schema includes roll_target_rules
Added a `roll_target_rules` field to the handoff JSON so Agent 2 can respect earnings-driven expiration constraints without needing the full earnings gate logic. Agent 1 pre-computes which expirations are blocked.

### 4. Profit optimization gate stays in Agent 1
Agent 1 evaluates the 3+4 gate conditions and reports `profit_optimization_gate: "passed"/"failed"/null`. Agent 2 trusts this and only handles the economics (finding the right strike, calculating net credit).

## Team Impact

- **Rusty**: Needs to wire up `agent_runner.py` to use the new instruction functions. The 2-phase flow: call `get_open_call_assessment_instructions()` for Agent 1, parse its output, and if non-WAIT, call `get_open_call_roll_instructions()` for Agent 2 with the handoff JSON + chain.
- **Basher**: Can test each agent independently — Agent 1 with mock position data, Agent 2 with mock handoff + chain.
- **Danny**: Review the handoff schema for completeness before Rusty integrates.

## Files

| File | Lines | Role |
|------|-------|------|
| `src/tv_open_call_assessment_instructions.py` | 463 | Call position assessment (Agent 1) |
| `src/tv_open_call_roll_instructions.py` | 298 | Call roll management (Agent 2) |
| `src/tv_open_put_assessment_instructions.py` | 462 | Put position assessment (Agent 1) |
| `src/tv_open_put_roll_instructions.py` | 300 | Put roll management (Agent 2) |

---

# Decision: Roll Cost Sign Convention + Profit Optimization Gate Split

**Author:** Linus (Quant Dev)
**Date:** 2026-07
**Status:** Implemented
**Files:** tv_open_call_roll_instructions.py, tv_open_put_roll_instructions.py, tv_open_call_assessment_instructions.py, tv_open_put_assessment_instructions.py

## Context
Rubber duck review of the monitor agent split found 3 issues in the instruction files.

## Decisions

### 1. estimated_roll_cost = new_premium - buyback_cost (always)
Examples in both roll files showed negative roll cost alongside positive net credit — contradictory. Fixed all examples so `estimated_roll_cost` equals the net credit/debit math. Positive = credit, negative = debit, consistent with the rules text.

### 2. Profit optimization gate: "eligible" (not "passed")
Agent 1 (assessment) was checking conditions it cannot evaluate — specifically "no earnings/ex-div before new expiration" — because Agent 2 (roll management) selects the expiration. Changed:
- Gate result from "passed" → "eligible" (Agent 1's checks passed, but Agent 2 must validate)
- Removed 2 candidate-dependent flexible conditions from assessment; now 5 stock-level conditions, need 3 of 5
- Added `profit_optimization_constraints` to handoff JSON so Agent 2 gets earnings/ex-div dates
- Added PROFIT OPTIMIZATION VALIDATION section to both roll files

### 3. Mandatory JSON output in roll agents
Added explicit warning: roll agents MUST always produce a JSON activity block. If no viable roll, output CLOSE with `roll_tier: "no_viable_roll"`.

## Team Impact
- **Rusty**: agent_runner.py should handle "eligible" in addition to "passed" if it inspects `profit_optimization_gate`. The null JSON issue (Finding 3) needs a framework-level guard in agent_runner.py too — instructions alone aren't sufficient.
- **Danny**: No direct frontend impact, but the `profit_optimization_gate` value in decision logs will now show "eligible" instead of "passed" for profit optimization rolls.

---

# Decision: Runner 2-Phase Execution — Implementation Details

**Date:** 2026-07-22
**Author:** Rusty (Agent Dev)
**Status:** Implemented
**Implements:** danny-monitor-split.md

## What was done

Refactored `agent_runner.py` and both monitor wrappers to support the 2-phase Position Assessment → Roll Management execution model.

## Key design decisions

### 1. Backward-compatible opt-in via optional params
`run_position_monitor()` gained `assessment_instructions` and `roll_instructions` as optional kwargs. When both are `None`, the original single-agent path runs unchanged. This means the refactor is safe to merge even before Linus's instruction files land.

### 2. Handoff detection via `action_needed` key
Phase 1's output format diverges from the standard activity format:
- **WAIT path:** `{ "activity": "WAIT", ... }` → standard `_try_extract_json()` picks it up
- **Action path:** `{ "action_needed": "ROLL_UP_AND_OUT", ... }` → new `_try_extract_handoff_json()` picks it up

Using a distinct key (`action_needed` vs `activity`) avoids ambiguity and makes the detection reliable.

### 3. Phase 2 error resilience
If Phase 2 (roll management) fails for any reason, the runner persists Phase 1's handoff as a degraded activity with `roll_economics: null` and `"roll_agent_error"` appended to `risk_flags`. The run never crashes — the user sees the assessment result even if roll economics are unavailable.

### 4. Try/except import for parallel development
Monitor wrappers import Linus's instruction functions inside a try/except ImportError block. If the files don't exist yet, `assessment_instructions` and `roll_instructions` stay `None`, and the runner falls back to single-agent mode.

## Files changed
- `src/agent_runner.py` — new methods: `_try_extract_handoff_json`, `_run_position_assessment`, `_run_roll_management`; refactored `run_position_monitor`
- `src/open_call_monitor_agent.py` — imports + passes assessment/roll instructions
- `src/open_put_monitor_agent.py` — same pattern for puts

## Dependencies
- **Linus:** 4 instruction files must be committed for 2-phase mode to activate:
  - `src/tv_open_call_assessment_instructions.py`
  - `src/tv_open_call_roll_instructions.py`
  - `src/tv_open_put_assessment_instructions.py`
  - `src/tv_open_put_roll_instructions.py`
- Until those exist, the runner operates in single-agent fallback mode.

---

# Decision: Remove Legacy Single-Agent Fallback from Position Monitors

**Date:** 2026-04-23
**Author:** Rusty (Agent Dev)
**Status:** Implemented
**Commit:** 7f04db7

## Context
The 2-phase position monitor flow (Phase 1: assessment, Phase 2: roll management) was introduced with a try/except ImportError fallback so the code could merge before Linus committed the instruction files. Both call and put instruction files are now committed and stable.

## Decision
Remove all legacy single-agent fallback paths:
- `open_call_monitor_agent.py` / `open_put_monitor_agent.py`: Direct imports instead of try/except; drop `instructions=` parameter from `run_position_monitor` calls.
- `agent_runner.py`: Drop `instructions` parameter from `run_position_monitor` signature; remove `two_phase` boolean check; delete the ~50-line single-agent `else` branch; hard-code `two_phase: True` in telemetry.

## Rationale
- Dead code: the single-agent path was unreachable since the instruction files are committed.
- Simpler control flow: one execution path instead of two branching conditionally.
- Prevents accidental regression to the less capable single-agent mode.
- Net deletion of ~80 lines.

## Impact
- No runtime behavior change — the 2-phase path was already the only path executed.
- Any future instruction file changes must keep the assessment/roll module pattern.

---

# DGI Screener Feature Decisions

## User Directive: Scope Simplification

**Date:** 2026-05-10T14:49  
**From:** David Sancho (via Copilot)  
**Decision:** Remove the CSP Recommender agent entirely from the DGI Screener feature. Instead, add a manual "Quick Analysis" button that triggers the existing quick analysis feature, and an "Add to Watchlist + CSP Watch" button. No new LLM agent needed — reuse existing infrastructure.  
**Rationale:** User preference for control; existing quick analysis is sufficient; eliminate need for a separate daily LLM agent.

---

## Decision: Scope Simplification — CSP Recommender Removed

**Date:** 2026-05-10  
**Author:** Danny (Lead)  
**Status:** Approved by David (User)  
**Impact:** Reduces complexity, accelerates delivery, improves user control

### Context
Initial DGI Screener v2 proposal (2026-05-10) included a daily LLM agent (CSP Recommender) to generate automatic Cash-Secured Put recommendations for each Top 20 symbol. User feedback reversed this decision.

### Changes
**Eliminated:**
- LLM agent: `dgi_csp_recommender.py`
- Agent instructions: `dgi_csp_recommender_instructions.py`
- Cron job: daily recommendation generation
- CosmosDB doc_type: `csp_recommendation`
- YAML config block: `dgi_csp_recommender`

**Added: Two manual buttons in DGI Screener dashboard**
1. "Quick Analysis" → `POST /api/chat` (mode: "quick-analysis") — reuses existing feature
2. "Add to Watchlist + CSP Watch" → `POST /api/dgi/add-to-watchlist` — integrates with existing CSP agent

### Benefits
- LLM cost reduced 80–90% (manual triggers vs. daily automation)
- Complexity: 1 agent + reused endpoints vs. 2 new agents
- Delivery: 50% faster (1–2 days vs. 3–4 days)
- Code reuse: maximized (no new agent code, reuses `/api/chat` + existing CSP infrastructure)
- User control: manual analysis before decisions

### Implementation Phases
1. **Phase 1 (3–4 days):** DGI Screener MVP (yfinance_fetcher, dgi_metrics, dgi_screener, CosmosDB, scheduler)
2. **Phase 2 (2–3 days):** Web dashboard (/dgi-screener, API endpoints, manual buttons)
3. **Phase 3 (1–2 days):** Error handling, logging, edge cases

---

## Decision: Technical Indicators for DGI Screener Entry Timing

**Date:** 2026-05-10  
**Author:** Danny (Lead)  
**Status:** Incorporated in DGI Screener proposal v2  
**Impact:** dgi_metrics.py, yfinance_fetcher.py, config.yaml quality_score calculation

### Context
User feedback: "Don't give me 20 good DGI stocks — I know which those are. Give me 20 with good entry points now."  
Screener evolves from purely fundamental-quality to hybrid: **70% fundamental quality + 30% technical entry timing**.

### Quality Score Rebalancing
- **Fundamental (70%):** Yield (15%), Growth (18%), Payout (10%), Valuation (10%), Health (7%), Consistency (10%)
- **Technical Timing (30%):** RSI (30%), SMA position (25%), 52-week high distance (25%), Bollinger Bands (20%)

### Technical Indicators (Programmatic, no LLM cost)
| Indicator | Implementation | Favorable Signal |
|-----------|---------------|------------------|
| RSI(14) | `calculate_rsi()` in dgi_metrics.py | < 40 (oversold) |
| SMA(50/200) | `calculate_sma()` | Price at or below SMA(200) |
| 52w High Distance | Direct calculation | > 15% pullback |
| Bollinger Bands(20,2) | `calculate_bollinger_bands()` | Lower quartile of bands |

### Data Source
- **Primary:** yfinance — `ticker.history(period="1y")` provides OHLCV daily data
- **Backup:** Existing TradingView integration
- `yfinance_fetcher.py` returns history + info + dividends

### Configuration
All parameters configurable in config.yaml:
- RSI/SMA/BB periods
- Quality score weights (fundamental vs. technical)
- Component sub-weights

### Rationale
- Best DGI stocks are stable and well-known; differentiation is timing entry
- Technical indicators are deterministic; no LLM cost
- 30% technical weight sufficient to influence ranking without sacrificing fundamental quality
- yfinance provides free, adequate OHLCV for these calculations

---

## Decision: Post-Agent Premium Validation

**Date:** 2026-07-13  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented  
**Impact:** agent_runner.py, options chain data integrity

### Context
LLM agents occasionally hallucinate premiums when reading options chain JSON — mismatching bid values from wrong expiration dates. Example: CSP agent reported $1.55 for strike $45 exp 2026-06-18, but $1.55 bid belonged to 2026-12-18; actual bid was $0.15. Instructions alone cannot prevent this error.

### Solution
Added programmatic post-agent validation step (`_validate_premium_against_chain`) in `AgentRunner` that cross-checks every reported premium against actual parsed options chain data **after** agent JSON output but **before** persistence.

### Validation Scope
- **Watchlist (SELL signals):** premium (bid) at reported strike + expiration
- **Monitor (ROLL signals):** new_premium (bid of new contract) and buyback_cost (ask of current contract)
- **Delta:** corrected if chain shows different value

### Behavior
- Mismatches > $0.02: auto-corrected with WARNING log
- `premium_corrected: True` flag set for traceability
- premium_pct and net_credit recalculated on correction
- Defensive: wrapped in try/except, never crashes pipeline
- Logs: DEBUG on validation pass, WARNING on correction

### Files Changed
- `src/agent_runner.py` — methods: `_validate_premium_against_chain()`, `_validate_single_premium()`, `_validate_buyback_cost()` plus integration into `run_symbol_agent()` and `run_position_monitor()`

---

## Decision: DGI Screener Bug Fixes

**Date:** 2026-07  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented

### Context
Basher's code review identified 5 critical and 3 moderate bugs in DGI Screener pipeline. All were interface contract mismatches between dgi_screener.py (caller) and dgi_metrics.py / yfinance_fetcher.py (callees), plus missing scheduler integration and config/dependencies.

### Fixes Implemented

1. **`days_on_list` counter starts at 1** 
   - First day on list = day 1, not 0
   - More intuitive for user dashboard display

2. **Technical indicator config passed as kwargs**
   - rsi_period, bb_period, bb_std from config.yaml passed as optional kwargs
   - Only if present in config; otherwise function defaults apply
   - Keeps call site forward-compatible for future parameters

3. **DGI scheduler mirrors options_chain pattern**
   - Follows same init → reschedule → trigger → display flow
   - Consistency across all scheduler job types

### Team Impact
- **Danny:** config.yaml now has `dgi_screener` section for filters/weights updates
- **Linus:** `calculate_quality_score` hardcodes weights internally — config weights NOT passed through; requires signature update if dynamic weights needed
- **Basher:** All critical/moderate findings resolved; ready for re-review

---

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

---

# Decision: DGI Screener Documentation Structure

**Author:** Rusty (Agent Dev)
**Date:** 2026-07
**Status:** Implemented

## Decision
The DGI Screener section in README.md is structured as a self-contained reference with subsections for categories, quality score, filters, data source, storage, scheduling, config, web UI, and pipeline steps. This mirrors the depth of existing sections (e.g., Symbol Report) while being independently readable.

## Key Choices
1. **DGI section placed after Symbol Report, before Project Structure** — follows the pattern of feature sections before structural/setup sections
2. **yfinance explicitly called out as independent of TradingView** — prevents confusion about data source overlap
3. **Config.yaml example included inline** — enables copy-paste setup without cross-referencing
4. **Provision script uses `DGI_CONTAINER` variable** — consistent with `TELEMETRY_CONTAINER` and `SETTINGS_CONTAINER` patterns

## Impact
- README accurately reflects 8 agents, 4 containers, and the DGI investment strategy
- Provision script creates all 4 containers in a single run
- New contributors can understand DGI Screener without reading source code

---

# Decision: DGI Screener ▶ Button → Chat Quick Analysis

**Date:** 2026-05-10  
**Agent:** Linus  
**Status:** Implemented  

## Decision

The DGI screener's ▶ (analyze) button now redirects to the Chat page's Quick Analysis mode instead of triggering the CSP analysis API in the background.

## Rationale

1. **Better UX**: Interactive chat analysis is more valuable than a background API call with no feedback
2. **Centralization**: The chat page already has all the Quick Analysis infrastructure — reuse rather than duplicate
3. **Flexibility**: Users can interact with the analysis, ask follow-ups, adjust parameters

## Implementation Details

**DGI Screener** (`web/templates/dgi_screener.html`):
- Button redirects to `/chat?mode=quick-analysis&symbol=XXX&market=YYY&option_type=put`
- Added Yahoo Finance exchange code mapping (NYQ→NYSE, NMS→NASDAQ, etc.)
- Market/exchange extracted from row's `data-entry` JSON (entry.exchange)

**Chat Page** (`web/templates/chat.html`):
- Detects URL params on load
- Pre-fills form and auto-starts `fetchAndAnalyze()` if params present
- User lands on chat page with analysis already running

## Technical Notes

- **Exchange Mapping Required**: Yahoo Finance returns codes (NYQ, NMS) but TradingView expects full names (NYSE, NASDAQ)
- **Option Type Default**: Always pre-selects "put" for DGI screener (cash-secured put strategy)
- **No Breaking Changes**: ➕ (add to watchlist) button and detail modal remain functional

## Pattern

**Redirect-to-Form-with-Auto-Submit**: When multiple features need similar functionality, redirect to the canonical implementation with URL params rather than duplicating logic. The receiving page owns the flow; the sender just bootstraps with context.

## Files Modified

- `web/templates/dgi_screener.html` — button click handler
- `web/templates/chat.html` — URL param detection & auto-start

## Future Considerations

- Could extend this pattern to other screeners/tables (e.g., watchlist, positions)
- Could add more URL params (e.g., `auto_submit=true` flag instead of implicit behavior)
- Exchange mapping could be centralized if needed elsewhere (currently inline in DGI screener JS)
# Decision: Chat View Output Format - Section-Based Cards vs Markdown Tables

**Date**: 2026-05-11  
**Author**: Linus (Quant Dev)  
**Status**: Implemented  
**Context**: Chat UI rendering optimization  

## Problem

Decision Summary tables in chat agent responses (covered calls, cash-secured puts) rendered poorly in chat bubbles:
- Wide 2-column markdown tables (`| Factor | Assessment |`) with long multi-line content using `<br>` tags
- Chat bubbles have constrained width, making wide tables cramped and hard to read
- `<br>` tags in markdown table cells are a hack that doesn't flow naturally
- Poor responsive behavior at different screen widths

## Decision

**Replace markdown table format with section-based card format** for Decision Summaries in chat agent prompts.

### Old Format (Markdown Table)
```markdown
## 📊 Decision Summary

| Factor | Assessment |
|--------|------------|
| **Overall Recommendation** | Cautiously Favorable |
| **Key Reasons AGAINST** | • Risk 1<br>• Risk 2<br>• Risk 3 |
| **Suggested Strikes** | $435: Reasoning<br>$440: Alternative |
```

### New Format (Section-Based Cards)
```markdown
## 📊 Decision Summary

**🎯 Overall Recommendation:** Cautiously Favorable for selling covered calls

---

**⚠️ Key Reasons AGAINST Selling:**
- Risk 1 — specific detail
- Risk 2 — specific detail
- Risk 3 if applicable

**💰 Suggested Strike Prices:**
- **$435 strike** (0.20 delta, OTM): Reasoning here
- **$440 strike** (0.15 delta, further OTM): Alternative
```

## Rationale

1. **Responsive**: Section-based format adapts to any chat bubble width without horizontal scrolling
2. **Readability**: Bullet lists are more natural than `<br>`-separated items in table cells
3. **Visual Hierarchy**: Emoji prefixes + markdown headers create clear visual sections
4. **Maintainability**: Easier for AI to generate — no need to manage table alignment or worry about `<br>` placement
5. **Content Preservation**: All the same information, just better formatted for the chat UI

## Implementation

- Updated prompt templates in `src/tv_open_call_chat_instructions.py` and `src/tv_open_put_chat_instructions.py`
- Changed both the format specification (template section) AND the example response
- Preserved strategy-specific differences (PUT uses "Assignment Readiness", CALL uses "Profit Target")
- Added CSS improvements to `web/static/style.css` for tables that remain (options chain in reports):
  - Horizontal scrolling support
  - Better dark theme colors
  - Alternating row backgrounds
  - Improved `<br>` tag spacing in cells
- Added formatting note to `src/tv_report_instructions.py` to avoid `<br>` in new tables

## Scope

**What Changed**:
- Chat agent output format for Decision Summaries (CALL and PUT)
- CSS for all tables in chat bubbles

**What Did NOT Change**:
- Strategy assessment logic or gate criteria
- Content guidelines (what to include in each section)
- Report agent tables (options chain, etc.) — those keep table format but with improved CSS

## Team Impact

- **Frontend/UI**: Chat views will render decision summaries more cleanly
- **AI Prompts**: Future prompt changes should use this section-based format for chat outputs
- **Reports**: Report agent continues to use compact markdown tables (appropriate for that context)

## Pattern for Future Reference

**Use section-based card format when**:
- Output appears in constrained-width UI (chat bubbles, mobile)
- Content has multi-line items within categories
- Visual scanning is important

**Use markdown tables when**:
- Displaying tabular data (options chains, dividend history)
- Fixed-width layout is available (reports, full-page views)
- Keep columns narrow; avoid `<br>` in cells (use multiple rows instead)

---

## DGI Enhancements (2026-05-11)

### Radar "Ideal Minimum" Thresholds Use Above-Filter Values
**Date:** 2026-05-11  
**Author:** Linus (Quant Dev)  
**Status:** ✅ Implemented

DEFAULT_FILTERS in dgi_metrics.py sit at the exact zero-point of each scoring function (all map to sub-score 0). Plotting them on the radar would show a collapsed dot at center — useless visually.

**Decision:** The "Ideal Minimum" red line uses moderately higher raw values representing a "decent DGI holding" floor rather than bare elimination cutoff:
- Yield 2.5% (score 22), Growth 5% CAGR (score 33), Payout ≤60% (score 30), PE ≤25 (score 25), D/E ≤1.5 + ROE ≥10% (score 29), Years ≥8 (score 23), Tech 40

**Implications:**
- If DEFAULT_FILTERS change, `_compute_minimum_thresholds()` may need updating — they're currently independent.
- The threshold is computed fresh each call (trivial cost) rather than cached.
- Legend is now displayed on the radar chart to distinguish the two datasets.

**Files Changed:** `src/dgi_metrics.py`, `web/templates/dgi_analysis.html`

---

### Beasts Filter Preset
**Author:** Linus (Quant Dev)  
**Date:** 2026-05-11  
**Status:** ✅ Implemented

User requested a "Beasts" preset filter button on the DGI screener page to quickly surface elite dividend stocks.

**Decision:** Added a `🐂 Beasts` button in `web/templates/dgi_screener.html` that sets filter thresholds: Quality Score ≥ 80, Dividend Yield ≥ 2.5%, Dividend Growth ≥ 10%, Years ≥ 10, Timing ≥ 90. The button reuses the existing `applyFilters()` function by programmatically setting slider values — no duplicate filter logic.

**Rationale:**
- Reusing sliders + `applyFilters()` keeps one source of truth for filtering logic.
- Users can see and adjust the preset values after clicking since sliders visually update.
- "Over X" interpreted as ≥ X for practical UI purposes.

**Files Changed:** `web/templates/dgi_screener.html`

---

### DGI Single-Symbol Analysis Page
**Date:** 2026-05-11  
**Author:** Linus (Quant Dev)  
**Status:** ✅ Implemented  
**Impact:** Frontend, API, scoring logic

Added a read-only DGI analysis page (`/dgi/analyze/{symbol}`) that lets users score any ticker — not just symbols in the S&P 500 screener universe.

**Key Design Choices:**
1. **New `analyze_single_symbol()` function** in `dgi_screener.py` rather than reusing `run_dgi_screener()` — avoids CosmosDB writes, config dependencies, and batch overhead. Single-symbol path fetches one ticker and returns immediately.
2. **New `calculate_quality_score_detailed()`** in `dgi_metrics.py` instead of modifying existing `calculate_quality_score()` — the detailed variant returns all sub-scores, weights, and health breakdowns. Original function untouched for backward compatibility.
3. **Executor thread for blocking I/O** — `yfinance` is synchronous, so the endpoint uses `run_in_executor()` to avoid blocking the FastAPI event loop.
4. **No CosmosDB dependency** — the analysis endpoint doesn't require CosmosDB at all. It fetches live data from yfinance and computes scores on the fly.

**Files Changed:** `src/dgi_metrics.py`, `src/dgi_screener.py`, `web/app.py`, `web/templates/dgi_screener.html`, `web/templates/dgi_analysis.html`

---

### DGI Score History Tracking
**Date:** 2026-05-11  
**Author:** Linus (Quant Dev)  
**Status:** ✅ Implemented  
**Impact:** Data model (CosmosDB `dgi_top20` documents), Frontend (detail modal)

When stocks persist in the DGI screener top_n across multiple runs, their quality_score may change as market conditions evolve.

**Decision:** Added a `score_history` array field to each `dgi_top20` document in CosmosDB:
- Format: `[{"date": "YYYY-MM-DD", "score": float}, ...]`
- Capped at 90 entries (matches the daily snapshot TTL)
- Deduplication: same day + same score → skip; same day + different score → replace last entry
- New stocks initialize with a single entry

**Implications for Team:**
- **Rusty (Framework):** No changes needed — the field is just another document property flowing through existing upsert/read paths.
- **Danny (Lead):** The 90-entry cap keeps document size bounded. If we later want longer history, consider moving to the snapshot collection instead.
- **Frontend:** Chart.js CDN added to `dgi_screener.html` (not base.html) — only loaded on the DGI page. If other pages need charts, consider moving to base.html.

**Files Changed:** `src/dgi_metrics.py`, `web/app.py`

---

### StockAnalysis.com as Supplementary Dividend Data Source
**Date:** 2026-05-11  
**Author:** Linus (Quant Dev)  
**Status:** ✅ Implemented  
**Impact:** DGI screener pipeline (both single-symbol and batch modes)

Yahoo Finance's dividend payment series produces unreliable `years_consecutive_increases` counts. StockAnalysis.com publishes an authoritative "Growth Years" metric on each stock's dividend page that matches established dividend aristocrat/champion databases.

**Decision:**
- **Growth Years**: ALWAYS prefer stockanalysis.com over Yahoo-calculated value. Fall back to Yahoo only when SA returns `None`.
- **Other metrics** (yield, payout ratio, CAGR): use SA as fallback only when Yahoo returns 0 or missing. Yahoo remains the primary source for these.
- `dgi_metrics.py` is NOT modified — the override happens at the integration level in `dgi_screener.py`.

**Risks:**
- Web scraping is fragile — SA may change page structure, block requests, or rate-limit.
- Mitigations: dual parsing strategy (DOM + regex fallback), `None` return on any error, in-memory cache, polite delays, User-Agent rotation.
- If SA is completely unreachable, the screener falls back silently to Yahoo-only behavior with no disruption.

**Files Changed:** `src/dgi_screener.py`

---

### Dual Threshold Lines on Radar Chart
**Author:** Linus (Quant Dev)  
**Date:** 2026-05-11  
**Status:** ✅ Implemented

The radar chart previously showed a single red "Ideal Minimum" threshold line. Now displays two uniform threshold lines:
- **Mínimo (65)** — red dashed line, uniform 65 on all axes.
- **Ideal (80)** — green dashed line, uniform 80 on all axes.

Uniform approach works because weights sum to 1.0: setting all sub-scores to N yields a weighted total of N.

**API Change:** `calculate_quality_score_detailed()` now returns `"ideal_thresholds"` in addition to `"minimum_thresholds"`.

**Files Changed:** `src/dgi_metrics.py`, `web/templates/dgi_analysis.html`

---

### yfinance dividendYield Normalization
**Author:** Linus (Quant Dev)  
**Date:** 2026-07-25  
**Status:** ✅ Implemented

MSFT was displaying ~88% dividend yield in DGI screener modal (actual yield ~0.8%).

**Root Cause:** yfinance `dividendYield` returns values in percentage form (0.88 = 0.88%, 2.42 = 2.42%). The normalization `if raw_yield > 1: raw_yield /= 100` only caught yields above 1%, leaving sub-1% stocks (MSFT 0.88, AAPL 0.37) in percentage form while downstream (scoring, categorization, filters) expected decimal.

**Downstream Effects:**
- Filter modal: `0.88 * 100 = 88.00%`
- Scoring: `0.88 / 0.05 * 100 = 1760`, clamped to 100 — always max score
- Categorization: `0.88 >= 0.04` → wrongly classified as "High Yield"

**Decision:** Always divide `dividendYield` by 100 (unconditional). Verified against 6 stocks: yfinance `dividendYield` is consistently percentage-form across all yield ranges.

**Files Changed:** `src/dgi_metrics.py`

---

### DGI Screener Payout Ratio Display Fix
**Author:** Linus (Quant Dev)  
**Date:** 2026-05-13  
**Status:** ✅ Implemented

The DGI screener detail modal displayed raw decimal values for `payout_ratio` ("0.3", "0.333") instead of formatted percentages ("30%", "33.3%").

**Investigation:**
1. yfinance returns `payoutRatio` as decimal (0.333 = 33.3%) — tested with ZTS, MSFT, JNJ, AAPL, KO
2. CosmosDB stores correctly as decimal (internal convention: 0-1 range for ratios)
3. Scoring functions expect decimal (`_payout_safety_score`, `max_payout: 0.75`)
4. Analysis page formats correctly (`dgi_analysis.html` uses `* 100`)
5. Bug location: `dgi_screener.html` detail modal uses generic `buildSection()` which applies `fmtVal()` to all fields — doesn't know about percentage vs. dollar vs. ratio fields

**Root Cause:** Formatting logic applied in wrong order. `fmtVal()` converted values to strings before field-specific numeric checks could run, causing conditionals to fail.

**Fix:** Reordered formatting logic in `web/templates/dgi_screener.html` (lines 422-447):
- **Field-specific formatting FIRST** (percentage, market cap, price, ratio) while values are still numeric
- **Generic fallback** to `fmtVal()` for other fields

**Formatted Fields:** payout_ratio, dividend_yield, dividend_cagr_5y, roe, debt_to_equity, market_cap, current_price

**Files Changed:** `web/templates/dgi_screener.html`

---

### Premium=0.0 — Root Cause & Diagnostic Fix
**Author:** Linus (Quant Dev)  
**Date:** 2026-05-11  
**Status:** 🔧 Applied — needs runtime verification

All trading agents returning premium=0.0. Options chain data confirmed present by user. Systemic across all agent types.

**Two Most Likely Causes:**
1. **TradingView endpoint migration:** `_OPTIONS_SCAN_URLS` only matched `scan2` endpoints. If TradingView migrated to `scan`, `screener`, or `scan3`, no API responses would be intercepted. DOM fallback fails → parser fails → agents get raw text → output premium=0.0.
2. **TradingView field name change:** If field names changed (e.g., "bid" → "option_bid"), parser stores bid=None, agents see null, output premium=0.0.

**Changes:**
- Broadened URL matching to cover scan/scan2/scan3/screener + added fallback for any scanner.tradingview.com response with "symbols-options"
- Added field name aliases to `_FIELD_MAP`
- Added diagnostic logging at ERROR level for missed scanner URLs and missing bid/ask fields
- Fixed broken tests in `test_options_chain_parser.py` (tests used `[0]` indexing but parser was refactored to strike-keyed dict format at commit 7be7d82)

**Key Pattern:** When intercepting third-party API responses by URL matching, URL patterns MUST be broadly defined and logged when they miss. Third parties change endpoints without notice. Always have fallback matcher and diagnostic logging.

**Files Changed:** `src/tv_data_fetcher.py`, `test_options_chain_parser.py`

---

### DGI Screener Observability Standards
**Author:** Linus (Quant Dev)  
**Date:** 2026-05-11  
**Status:** ✅ Implemented

User triggered a DGI screener run from web UI. Run appeared active but CosmosDB was never updated. Root cause: background thread error handlers lacked `exc_info=True`, making failures invisible.

**Decision:**
1. **All background thread error handlers must include `exc_info=True`** — without full tracebacks, async failures are undebuggable.
2. **All CosmosDB write operations must have INFO-level logging before AND after** — "Saving N entries..." / "✅ All N entries saved".
3. **The `container is None` guard in `cosmos_db.py` should be audited** — it silently skips writes with only a WARNING. For DGI screener writes, this is data loss and should log at ERROR level.

**Key Pattern:** Background-threaded operations need explicit error context. CosmosDB silent-skip patterns should log at ERROR when they cause data loss, not WARNING.

**Applies to:** All background-threaded operations (DGI screener, future scheduled tasks). Rusty should review other `cosmos_db.py` methods for similar silent-skip patterns.

**Files Changed:** `src/dgi_screener.py`, `src/cosmos_db.py`

---

### Per-Function Model Override System
**Author:** Rusty (Backend Dev)  
**Date:** 2026-07  
**Status:** ✅ Implemented

All agents used a single `model_deployment` config value. Different agents have different complexity/cost profiles and benefit from different models.

**Decision:**
- Added `azure.models` section to `config.yaml` with per-role keys
- `Config.model_for(role)` returns override or falls back to `model_deployment`
- `AgentRunner` lazily caches one `AzureOpenAIChatClient` per unique deployment name
- All overrides optional — backward compatible with existing configs

**Role Keys:** `monitor_assessment`, `monitor_roll`, `supervisor`, `alpha`, `analysis`, `summary`, `report`, `chat`, `symbol_chat`

**Backward Compatibility:** No breaking changes to existing env vars or configs.

**Files Changed:** `config.yaml`, `src/config.py`, `src/agent_runner.py`

---
