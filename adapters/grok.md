# Grok CLI

The converter is `src/wadachi/convert/grok.py`. It uses the shared base.
No session content or identifying values appear in these notes or fixtures.

## Records

Measured on one machine with Grok CLI 1.0.92: 3 local sessions (one
interactive with a compaction, one headless run made for this measurement).
A review by another model (Antigravity, Gemini 4 Neon) compared all of them
with the raw files; its findings are fixed in converter 0.2.0. That is a
model's review, not a measurement.
The CLI's own user guide is installed under `GROK_HOME/docs`.

| Fact | Status |
|---|---|
| Sessions live under `GROK_HOME/sessions/<percent-encoded cwd>/<session id>/`; `GROK_HOME` defaults to `~/.grok` | measured (1.0.92), documented |
| `chat_history.jsonl` is the model's input history: `system`, `user` (content a list of text items; `synthetic_reason` such as `system_reminder`, `compaction_meta`, `task_completed` marks harness-made input), `assistant` (`content`, `tool_calls` `{id, name, arguments}`, `model_id`), `reasoning` (`id`, `encrypted_content`, `summary` of `summary_text` items), `tool_result` (`tool_call_id`, `content`) | measured (1.0.92) |
| Chat history lines have **no times** and no ids except reasoning ids | measured (1.0.92) |
| `arguments` is a JSON-encoded string | measured (1.0.92) |
| `events.jsonl` is timed telemetry (`ts`, UTC `Z`): `turn_started` (`session_id`, `model_id`, `turn_number`), `phase_changed`, `loop_started`, `first_token`, `permission_requested`, `permission_resolved` (`decision`, `wait_ms`), `tool_started`, `tool_completed` (`tool_call_id`, `outcome` `success` or `error`, `duration_ms`), `turn_ended` | measured (1.0.92) |
| `summary.json` holds `info.id` (the session id, equal to the directory name), `info.cwd`, `created_at`, `current_model_id`, `chat_format_version` (1) and titles | measured (1.0.92) |
| `prompt_context.json` holds `version` (the number 1: the prompt context's format, not the CLI's version), `build_timestamp_utc`, `is_non_interactive`, `working_directory` and prompt settings. No session file records the CLI version | measured (1.0.92) |
| `system_prompt.txt` is the system prompt; `tool_definitions.json` the tool list | measured (1.0.92) |
| `usage.json` holds session and per-turn tokens and cost in ticks (10¹⁰ per USD) | measured (1.0.92), documented |
| `updates.jsonl` is the client protocol stream (`session/update`: message and thought chunks, tool calls and updates; `_x.ai/...` extensions), timed | measured (1.0.92) |
| Other files: `signals.json`, `plan.json`, `plan_mode.json`, `rewind_points.jsonl`, `resources_state.json`, `announcement_state.json`, `compaction/*.md`, `compaction_checkpoints/`, `compaction_requests/`, `terminal/call-*.log`, lock files | measured (1.0.92) |
| `grok sessions show <id>` prints a session as JSON | documented; not used |

Sources, with fixed keys: `f1` `chat_history.jsonl` (record), `f2` reserved
for a hook log, `f3` `events.jsonl`, `f4` `system_prompt.txt`, `f5`
`tool_definitions.json` (aux, read for events), `f6` `summary.json`, `f7`
`prompt_context.json`, `f8` `usage.json` (aux, kept whole in the header's
`raw`). Every other file of the session directory is listed in `unread` with
its hash and kept by `--keep-raw`. Positions are byte offsets; a reasoning
line with a unique id is `@reasoning/<id>`.

## Record-to-event table

| Source | Mapping | Status |
|---|---|---|
| header | native id `info.id`, `cwd`, `model`, `started_at` from `summary.json`; `mode` headless or interactive from `prompt_context.json` `is_non_interactive`; no `harness.version` (not recorded), so `dump` reports every Grok session as `unversioned` | measured (1.0.92) |
| `system` | `context`, role `system` | measured (1.0.92) |
| `user` with `synthetic_reason` | `context`, role `user`, `name` the reason | measured (1.0.92) |
| `user` with `prompt_index` | `prompt`; actor caller in a headless session, else human (`how: inferred:session-interactivity`) | measured (1.0.92) |
| `user` with neither | `context`, role `user` (`how: inferred:user-line-without-prompt-index`): the harness's own user-info and rules block at the start of a session | measured (1.0.92), found by the independent audit |
| `assistant` | `assistant_text` when content is not empty; `tool_call` per call with `call_id`, `args` as the recorded string | measured (1.0.92) |
| `reasoning` | `reasoning`, `redacted: true`; `text` the summary when there is one | measured (1.0.92) |
| `tool_result` | `tool_result` linked by `tool_call_id` | measured (1.0.92) |
| `events.jsonl` `turn_started` | `setting` only when the model differs from the one before; the header's `model` is the first turn's | measured (1.0.92) |
| `events.jsonl` `permission_requested`, `permission_resolved` | `permission`: `asked`, and `allow` is `allowed` | measured (1.0.92) for `allow` |
| `events.jsonl` `turn_ended` with outcome `cancelled` | `interrupt`, `reason` the cancellation category; actor human when the trigger is `ctrl_c` (`how: inferred:ctrl-c-trigger`) | measured (1.0.92) |
| `events.jsonl` `tool_completed` with outcome `error` | `error`, `of` the call | measured (1.0.92) |
| other `events.jsonl` lines | `record`, timed; `of` the call when they name one | measured (1.0.92) |
| `system_prompt.txt` | `context`, `name` `system_prompt` | measured (1.0.92) |
| `tool_definitions.json` | `context`, `name` `tool_definitions`; the file is a JSON array, kept as `raw.value` because raw is an object | measured (1.0.92) |
| any other chat history type | `record`, kept whole | |

Events from `events.jsonl` with no `of` come after the chat history's events
(SPEC.md section 5): telemetry has times, the history has none, and wadachi
does not interleave them by guessing.

## Tools to kinds

| Tool | Kind | Status |
|---|---|---|
| `read_file`, `list_dir` | read | measured (1.0.92) |
| `write` | write | measured (1.0.92) |
| `search_replace` | edit | measured (1.0.92) |
| `run_terminal_command` | shell | measured (1.0.92) |
| `grep` | search | measured (1.0.92) |
| `mcp__*` | mcp | not measured |
| anything else | other | |

`paths` are not set: arguments are a JSON string whose keys were not measured
for every tool.

## Known gaps

- No times on the conversation itself; `updates.jsonl` has them but is not
  read yet.
- No exit codes; `terminal/call-*.log` may hold more output and is listed, not
  read.
- Subagents, forks and resumes were not in this corpus.
