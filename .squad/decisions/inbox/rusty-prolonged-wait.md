# Decision: Prolonged WAIT Contrarian Detection

**Date:** 2026-07-16
**Author:** Rusty (Agent Dev)
**Status:** Implemented

## Context

The contrarian agent only ran on alert decisions (SELL, ROLL_*, CLOSE). Normal WAITs were never challenged. However, when a position sits idle for 5+ consecutive analysis cycles with nothing but WAIT, there's a risk of capital-efficiency blind spots — theta decay stagnation, opportunity cost, changing market conditions that the primary agent isn't surfacing.

## Decision

- Added `_detect_prolonged_wait()` to `AgentRunner` — checks if the last N activities (default 5) are ALL non-alert WAITs with no errors.
- Integrated into both `run_symbol_agent()` and `run_position_monitor()` — triggers `_run_contrarian_review()` on prolonged WAIT, same as for alerts.
- Added `send_prolonged_wait_alert()` to `TelegramNotifier` — dedicated format with ⏳ prefix, only fires for MODERATE/STRONG contrarian challenges.
- Threshold is a class constant (`PROLONGED_WAIT_THRESHOLD = 5`), easily tunable.

## Constraints

- Detection NEVER blocks the pipeline — wrapped in try/except, returns False on any error.
- Uses `include_alerts=True` when fetching recent activities so that any real alert in the window disqualifies prolonged WAIT.
- Error activities also disqualify (checked via `act.get("error")`).

## Impact

- `src/agent_runner.py`: New method + two integration points
- `src/telegram_notifier.py`: New `send_prolonged_wait_alert()` method
