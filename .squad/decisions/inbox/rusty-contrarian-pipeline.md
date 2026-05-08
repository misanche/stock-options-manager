# Decision: Contrarian Agent Pipeline Integration

**Date:** 2026-07-17  
**Author:** Rusty (Agent Dev)  
**Status:** Implemented (MVP)  
**Implements:** Danny's contrarian architecture (Option A: Pipeline Automático)

## What was decided

The contrarian agent runs as a **post-write enrichment step** in both `run_symbol_agent()` and `run_position_monitor()`. It only activates on alert decisions (`is_alert=True`), never on WAITs.

## Key implementation choices

1. **Post-write pattern:** Activity is persisted to CosmosDB FIRST, then contrarian runs. If contrarian fails, the original activity is untouched. The `contrarian_view` field is patched onto the document via `update_activity_field()`.

2. **Same client, separate agent:** Uses the same `AzureOpenAIChatClient` (same model, same endpoint) but creates a new `ChatAgent` instance per review. This avoids conversation contamination while reusing the connection.

3. **Telegram noise filtering:** Only MODERATE and STRONG challenges appear in push notifications. WEAK challenges are stored in CosmosDB for dashboard review only.

4. **Graceful failure everywhere:** `_run_contrarian_review()` wraps everything in try/except → returns None on any failure. `update_activity_field()` returns bool. Neither can crash the pipeline.

## Interface contract with Linus

Depends on `src/tv_contrarian_instructions.py` providing:
- `get_contrarian_instructions(agent_type: str, decision_type: str) -> str`
- `CONTRARIAN_OUTPUT_SCHEMA` (string describing expected JSON schema)

The contrarian JSON response must contain: `challenge_strength` (WEAK/MODERATE/STRONG), `counter_arguments`, `net_assessment`, `one_liner`.

## Files changed

- `src/agent_runner.py` — contrarian method + pipeline integration
- `src/cosmos_db.py` — `update_activity_field()` method
- `src/telegram_notifier.py` — contrarian line in sell + roll alerts
