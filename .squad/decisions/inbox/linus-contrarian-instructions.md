# Decision: Contrarian Instructions Design

**Date:** 2026-07-18  
**Author:** Linus (Quant Dev)  
**Status:** Implemented  
**Impact:** `src/tv_contrarian_instructions.py` (new), `agent_runner.py` (Rusty consumes)

## What

Created `src/tv_contrarian_instructions.py` — the system prompt for the Phase 3 Contrarian agent per Danny's Opción D architecture.

## Key Design Decisions

### 1. Parameterized function instead of static constant
- `get_contrarian_instructions(agent_type, decision_type)` returns a prompt customized to the specific agent and decision being challenged.
- Rationale: The contrarian needs different playbooks for WAIT vs ROLL_UP vs SELL, and different context for call monitors vs put watchlists. A single static prompt would either be too generic or too long.

### 2. Input validation with ValueError
- Invalid agent_type or decision_type (e.g., `open_put` + `ROLL_UP`) raises `ValueError` immediately.
- Rationale: Fail-fast prevents the LLM from receiving a nonsensical prompt. Rusty should catch this in `_run_contrarian_review()`.

### 3. Nine decision playbooks, not per-agent-type
- Playbooks are keyed by decision_type (WAIT, ROLL_UP, SELL, etc.), not by agent_type.
- The agent context paragraph (call monitor vs put watchlist) is injected separately.
- Rationale: The counter-arguments for "ROLL_DOWN" are structurally the same whether it's a call or put — what differs is the context (assignment direction, which support/resistance matters). Splitting by decision keeps playbooks DRY while the context paragraph adds agent-specific framing.

### 4. CONTRARIAN_OUTPUT_SCHEMA exported as dict
- JSON Schema dict importable by `agent_runner.py` for response parsing/validation.
- Matches the output format from Danny's architecture doc exactly: `challenge_strength`, `counter_arguments[]`, `net_assessment`, `one_liner`.

## For Rusty
- Import: `from src.tv_contrarian_instructions import get_contrarian_instructions, CONTRARIAN_OUTPUT_SCHEMA`
- Call: `get_contrarian_instructions("open_call", "ROLL_UP_AND_OUT")` returns the full system prompt string.
- Parse response against `CONTRARIAN_OUTPUT_SCHEMA`.
- Handle `ValueError` if agent_type/decision_type combo is invalid (shouldn't happen in production but good to guard).
