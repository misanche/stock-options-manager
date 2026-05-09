# Decision: Post-Agent Premium Validation

**Author:** Rusty (Agent Dev)  
**Date:** 2026-07-13  
**Status:** Implemented

## Context
LLM agents sometimes hallucinate premiums when reading the options chain JSON — picking bid values from wrong expiration dates. For example, the CSP agent reported $1.55 for strike $45 exp 2026-06-18, but that bid belonged to the 2026-12-18 expiration. The real bid was $0.15. Prompt instructions alone cannot prevent this.

## Decision
Added a programmatic post-agent validation step (`_validate_premium_against_chain`) in `AgentRunner` that cross-checks every reported premium against the actual parsed options chain data. This runs after the agent produces its JSON output but before persistence.

### What it validates
- **Watchlist (SELL signals):** premium (bid) at the reported strike + expiration
- **Monitor (ROLL signals):** new_premium (bid of new contract) and buyback_cost (ask of current contract)
- **Delta:** corrected if chain shows a different value

### Behavior
- Mismatches > $0.02 are auto-corrected with a WARNING log
- `premium_corrected: True` flag is set for traceability
- premium_pct and net_credit are recalculated on correction
- Defensive: wrapped in try/except, never crashes the pipeline
- Logs at DEBUG when validation passes, WARNING on corrections

## Files Changed
- `src/agent_runner.py` — added `_validate_premium_against_chain()`, `_validate_single_premium()`, `_validate_buyback_cost()`, plus call sites in both `run_symbol_agent()` and `run_position_monitor()`
