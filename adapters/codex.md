# Codex CLI

## Records

| Fact | Status |
|---|---|
| Sessions are JSON Lines rollouts at `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` | reported |
| Record types include `session_meta` (once per file), `turn_context` (working directory, model), `response_item`, `event_msg` (such as `user_message`, `agent_reasoning`, `context_compacted`, `token_count`), `compacted` and `ghost_snapshot` | reported |
| A `response_item` carries a payload: a message, reasoning, a `function_call` or a `function_call_output` | reported |
| `function_call` arguments are stored as a JSON-encoded string | unverified; if so, `args` keeps the string |
| `ghost_snapshot` records git snapshots the harness takes itself | reported |
| Per-record timestamps and exit codes of shell calls | unverified: the write-ups do not describe them; check real files |

Mapping notes:

- `turn_context` with a new model or directory is a `setting` event.
- `token_count` is a `usage` event.
- `context_compacted` and `compacted` are `compaction` events.
- `ghost_snapshot` has no wadachi event type yet (see the open questions in
  SPEC.md). Until one is defined, the converter skips these records and counts
  them; the raw file keeps them. Do not attach them to a neighbouring event.
- Headless runs use `codex exec`: header `mode: "headless"`.

## Hooks

| Fact | Status |
|---|---|
| No hook system for tool calls found in the session-format write-ups checked on 2026-11-23 | reported; check the current version's documentation |
| A `notify` setting runs a program on some events | reported; check whether it sees tool calls, and what it receives |

Without hooks, the world record comes from a wrapper that owns the
environment: a filesystem watcher or tree snapshots per turn, and PATH shims
for shell commands to capture real exit codes.

## Tools to kinds

| Tool | Kind | Status |
|---|---|---|
| `shell` (and its newer variants) | shell | unverified |
| `apply_patch` | edit | unverified |
| `view_image` | read | unverified |
| `update_plan` | other | unverified |
| MCP tools | mcp | unverified |
