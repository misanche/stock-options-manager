# Decision: Mandatory Premium Cross-Verification Step

**Author:** Linus (Quant Dev)
**Date:** 2026-07-14
**Status:** Implemented

## Problem

The CSP watcher agent was reporting premium (bid) from the correct strike but wrong expiration date — specifically the last expiration key in the options chain JSON. The LLM reads a multi-expiration nested dict and silently crosses expiration boundaries when extracting prices.

## Decision

Add a mandatory "Premium Cross-Verification" step to every agent instruction file that produces a JSON activity block. The step requires the agent to explicitly cite the full chain lookup path (e.g., `puts["20260613"]["95.0"]["bid"] = 3.45`) and verify the expiration key matches the recommended date before writing the JSON output.

## Scope

- **Watcher agents** (CSP, CC): New numbered step in RESPONSE STRUCTURE before JSON Activity Block
- **Roll agents** (open call roll, open put roll): New subsection before Final Activity JSON Schema — verifies both buyback (ask) and new position (bid) paths
- **Chat agents** (call chat, put chat): Lighter-weight verification guidance section
- **Schema description** (`options_chain_parser.py`): Added COMMON ERROR warning to DATA INTEGRITY section — injected into all agents at runtime

## Rationale

- Zero runtime cost — this is prompt text only, no code logic changes
- Forces the LLM to make its lookup explicit, which naturally catches cross-expiration errors
- The contrarian agent already had a similar check added in a prior fix; this extends the pattern to the primary agents
- Same structural pattern as the "Never output bare ROLL" fix — making implicit behavior explicit prevents silent errors

## Files Modified

`options_chain_parser.py`, `tv_cash_secured_put_instructions.py`, `tv_covered_call_instructions.py`, `tv_open_call_roll_instructions.py`, `tv_open_put_roll_instructions.py`, `tv_open_call_chat_instructions.py`, `tv_open_put_chat_instructions.py`
