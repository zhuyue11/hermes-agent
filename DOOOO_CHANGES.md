# doooo Changes to hermes-agent

Changes made on top of hermes-agent v0.11.0 for dooooHub integration.

Base version: `v0.11.0` (commit `bf196a3f`, 2026-04-23)

---

## Feature 1: Per-Agent Memory Isolation (Phase 10.6)

Each agent in the dooooHub agent registry gets its own `MEMORY.md` file while sharing a single `USER.md` across all agents.

**Changed files:**
- `run_agent.py` — `AIAgent.__init__` forwards `memory_dir` kwarg to `MemoryStore`
- `tools/memory_tool.py` — `MemoryStore` gains `memory_dir` param; `_path_for()` routes `MEMORY.md` to agent-specific subdir, keeps `USER.md` in shared root

**Commit:** `3b35902e`

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

**Not yet committed**
