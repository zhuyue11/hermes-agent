# doooo Changes to hermes-agent

Changes made on top of hermes-agent v0.11.0 for dooooHub integration.

Base version: `v0.11.0` (commit `bf196a3f`, 2026-04-23)

---

## ~~Feature 1: Per-Agent Memory Isolation (Phase 10.6)~~ — REVERTED

Removed. All agents now share a single `MEMORY.md` and `USER.md` in `~/.hermes/memories/`. Memory isolation was unnecessary — agents serve the same user and benefit from shared context (user preferences, project facts). Behavioral differences are handled by each agent's personality/system prompt, not memory isolation. External memory providers (mem0, honcho, etc.) were never isolated per-agent anyway.

**Reverted changes:**
- `run_agent.py` — Removed `memory_dir` param from `AIAgent.__init__`
- `tools/memory_tool.py` — Removed `memory_dir` param from `MemoryStore`; `_path_for()` always uses the global memories directory

---

## Feature 2: Agent-Aware Sessions (Phase 10.6)

Sessions can be associated with a specific agent from the dooooHub agent registry, enabling per-agent session history.

**Changed files:**
- `hermes_state.py` — Added `agent_id TEXT` column to `sessions` table (schema v9), updated `create_session()` and `ensure_session()` with `agent_id` param, added `idx_sessions_agent` index

**Commit:** `141dd244`

---

## Feature 3: Credential Fill — Secure Website Login (Phase 4.13)

When the agent encounters a website login form during browser automation, the `credential_fill` tool injects stored credentials directly into form fields without exposing them to the LLM. If no credentials are stored, it prompts the user via a dedicated masked-password form, stores the response for future use, then injects.

**Security model:** 3-layer — proxy injection (LLM never sees credential values), session-scoped redaction (values masked in browser snapshots), approval gate (user prompted before each use unless auto-approve is toggled).

**New files:**
- `tools/credential_fill_tool.py` — Tool implementation with OpenAI function-calling schema. Handles vault lookup, user prompting via `credential_callback`, credential storage, and injection via `browser_type()`. Returns only status messages to the LLM.
- `agent/credential_vault.py` — HTTP client bridge to dooooHub sidecar credential endpoints (`POST /site-credentials/lookup`, `PUT /site-credentials/{service}`, `PATCH /site-credentials/{service}/auto-approve`)

**Modified files:**
- `toolsets.py` — Added `"credential_fill"` to `_HERMES_CORE_TOOLS` list and as its own toolset definition
- `run_agent.py` — Added `credential_callback` to `AIAgent.__init__`; added `_vault_lookup()` and `_vault_store()` bridge methods; added `credential_fill` handling in both concurrent (`_invoke_single_tool`) and sequential execution paths
- `agent/redact.py` — Added session-scoped secret redaction: `_session_secrets` set, `add_session_secrets()`, `clear_session_secrets()`, `_redact_session_secrets()`, hooked into `redact_sensitive_text()`
- `tui_gateway/server.py` — Added `credential_callback` to `_agent_cbs()` (emits `credential.request`, blocks until `credential.respond`); added `@method("credential.respond")` JSON-RPC handler

---

## Feature 4: Chain-Aware Sessions (task-system v1, Phase 4)

Extends Feature 2 so sessions can record the *chain* context they belong to, not just the agent. Sidecar's task system (`dooooHub/docs/task-system.md`) builds workflow chains across multiple agents under a single team; each chain step gets its own Hermes session, but they share team / workflow / chain identity. Storing those three columns lets the sidecar (a) JOIN messages by team for team-chat views (Phase 7), (b) let `handoff_to` walk the correct workflow (Phase 9), (c) reconstruct chain transcripts by `chain_id` (Phase 11). Hermes does no filtering on these — pure passive storage.

Also renames the existing v9 column `sessions.agent_id` to `sessions.agent_slug`, switching its value semantics from "registry UUID" to "namespaced marketplace slug" (e.g. `@doooo/visual-designer`) so all four context columns share one vocabulary. The sidecar no longer resolves slug→UUID before writing.

**Schema bump:** v9 → v10
- `ALTER TABLE sessions RENAME COLUMN agent_id TO agent_slug`
- New columns: `team_slug TEXT`, `workflow_slug TEXT`, `chain_id TEXT` (all nullable)
- New partial indexes (`WHERE col IS NOT NULL`): `idx_sessions_team_slug`, `idx_sessions_workflow_slug`, `idx_sessions_chain`
- Renamed index: `idx_sessions_agent` → `idx_sessions_agent_slug`

**API surface:** `create_session()` and `ensure_session()` gained `agent_slug` (renamed from `agent_id`), `team_slug`, `workflow_slug`, `chain_id` kwargs. All pass-through, no validation or filtering inside Hermes.

**No data backfill.** Pre-v10 sessions keep their legacy UUID-shaped values in the renamed `agent_slug` column; doooo is pre-prod and dev DBs wipe via repo reset if a clean slate is wanted.

**Changed files:**
- `hermes_state.py` — `SCHEMA_VERSION` 9→10, canonical `CREATE TABLE sessions` updated, v10 migration block added, `create_session()` / `ensure_session()` signatures + INSERTs updated
- `tests/test_hermes_state.py` — Added three v10 tests inside `TestSessionLifecycle` (roundtrip with values, roundtrip without kwargs, indexes exist)
