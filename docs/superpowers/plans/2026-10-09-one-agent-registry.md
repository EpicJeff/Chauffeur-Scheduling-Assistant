# One agent tool registry (retire `services/agent_tools.py`)

**Date:** 2026-10-09. **Kind:** behavior-preserving refactor. **User's rule:** nothing is lost — every tool name, schema and handler survives; only the module boundary moves.

## Finding

There is one LLM stack already: `agent_router` + `agent_tools_v2` serve chat, HA Assist, `@argyle` and the Mind. `services/llm.py::agentic_chat_loop` has no callers outside tests. `services/agent_tools.py` (v1) survives as:

1. the only name→schema→handler registry (`TOOL_SCHEMAS`, `TOOL_HANDLERS`, `execute_tool`), two thirds of whose handlers are one-line wrappers around v2 functions;
2. the implementation of 20 admin tools reachable through `BRIDGED_V1_TOOLS` (scheduling core, errands, rules, solver, car, memory, places, household status, four legacy trip tools) plus the trip-flight handlers v2's `manage_trip_flights` delegates to;
3. the catalogue `missions.proposable_tools()` and `chat_actions.execute_admin_action` read.

## Target

- `agent_tools_v2.py` holds everything: the v2 functions it has today, plus a **Registry** section (Pydantic arg models, `TOOL_SCHEMAS`, `get_openai_tools`, every `handle_*`, `TOOL_HANDLERS`, `execute_tool`) moved verbatim from v1.
- `BRIDGED_V1_TOOLS` → `ADMIN_TOOLS`; `SCHEDULE_MUTATING_V1_TOOLS` → `SCHEDULE_MUTATING_ADMIN_TOOLS`; `get_bridged_v1_tools` → `get_admin_tools`, built from the local registry. Same names, same gate, same `schedule_dirty` behavior.
- `agent_router`, `chat_actions`, `missions` import the registry from `agent_tools_v2`.
- `llm.py::agentic_chat_loop` deleted (`auto_name_conversation` stays; `main.py` uses it).
- `services/agent_tools.py` deleted. Tests re-pointed mechanically (`agent_tools.` → `agent_tools_v2.`).

## Proof

Gate = the 21 test files that import v1 + router/caller tests (`tools/test.py agent missions cancellations gift_shortlist location_resolve meals occasions optional_events pets pooled_rewards ride_groups shopping chat_actions argyle_chat assist mind_plan threads negotiation programs`), run with `HA_BASE_URL` unset, before and after. Same pass set, same count. Tool-name parity asserted by the (renamed) bridge test: registry ⊇ every name v1 had.

## Steps

1. Baseline gate; record counts.
2. Splice v1 (minus its first three import lines) onto the end of v2 under a `# Registry` banner; rewrite in-module `from services.agent_tools_v2 import x` lines inside moved wrappers to direct references.
3. v2 internals: `launch_mission` alias, `manage_trip_flights`, `get_admin_tools`; renames.
4. Router, chat_actions, missions: import switch.
5. Delete `agentic_chat_loop`; delete `agent_tools.py`.
6. Tests re-pointed; bridge test asserts parity against a frozen list of the 103 v1 names.
7. Gate again. `system_capabilities.md` entry, `config.yaml` bump, memory `two-agent-stacks` corrected, commit.
