# Antigravity CLI

The converter is `src/wadachi/convert/antigravity.py`. It uses the shared base.
No session content or identifying values appear in these notes or fixtures.

## Records

Measured on one machine: 7 conversations, 6 with a transcript (445 steps).
The installed CLI was `agy` 1.5.18; its logs name 1.5.12 and 1.5.13 as the
versions that ran earlier. No conversation file records a version, so the
header has none, `converter.measured` lists only 1.5.18, and `dump` reports
every Antigravity session as `unversioned`.

| Fact | Status |
|---|---|
| Conversations live under `~/.gemini/antigravity-cli/brain/<conversation id>/` | measured (1.5.18) |
| `.system_generated/logs/transcript_full.jsonl` is the complete transcript; `transcript.jsonl` has the same steps with `tool_calls` (198 steps) and `content` (44 steps) cut short | measured (1.5.18) |
| `logs/chunks/transcript_full/*.jsonl` and `logs/chunks/transcript/*.jsonl` are the same bytes as the full and short transcripts, split at arbitrary byte positions (a line can span two chunks) | measured (1.5.18) |
| Each line is a step: `step_index` (unique, increasing), `source` (`USER_EXPLICIT`, `MODEL`, `SYSTEM`), `type`, `status` (`DONE`, `RUNNING`, `ERROR`), `created_at` (UTC, `Z`) | measured (1.5.18) |
| Step types: `USER_INPUT` (content wrapped in `<USER_REQUEST>`), `PLANNER_RESPONSE` (`content`, `thinking`, `tool_calls`, `input_tokens`, `output_tokens`, `cache_read_tokens`, sometimes `model`), `GENERIC` (a tool's result: `content` starting `Created At:`, sometimes `error`), `SYSTEM_MESSAGE`, `EPHEMERAL_MESSAGE` (no content) | measured (1.5.18) |
| A planner step holds at most one tool call, `{name, args}`, with no call id; the next step is its `GENERIC` result (197 of 198 calls; the other was the last step) | measured (1.5.18) |
| `steps/<index>/output.txt` (and sometimes `content.md`) holds a tool's output beside the transcript; it differs from the step's `content` in 121 of 156 cases | measured (1.5.18) |
| `messages/*.json` holds messages between conversations and tasks: `sender`, `recipient`, `content`, `sourceMetadata.tool.conversationId`, `stepIndex`, `timestamp` | measured (1.5.18) |
| The conversation id is only the directory name; it is the id `agy --conversation=<id>` takes | measured (1.5.18), documented |
| `history.jsonl` in the CLI's home indexes prompts of every conversation (`display`, `timestamp`, `workspace`, `conversationId`) | measured (1.5.18) |
| `conversations/<id>.db` is a SQLite database per conversation (tables `trajectory_meta`, `steps`, `gen_metadata`, `executor_metadata`, `parent_references`, `trajectory_metadata_blob`, `battle_mode_infos`; step data as protocol buffer blobs); every conversation has one, and one of 7 had no transcript at all | measured (1.5.18) |
| `/fork` | reported; not in this corpus |

`f1` is `transcript_full.jsonl`. `f2` is reserved for a hook log. `f3` is
`transcript.jsonl`, listed with `truncated: true` and not read for events.
Every other file in the conversation's directory (chunks, step outputs,
messages, scratch files), and the CLI's `conversations/<id>.db` and
`annotations/<id>.pbtxt` for it, are listed in the header's `unread` with
their hashes, and kept by `wadachi dump --keep-raw`. A conversation directory
without a transcript is still discovered; its conversion fails and `dump`
counts it, so it is never left out silently. Positions are `@step/<step_index>`.
The native id comes from the directory name, marked
`how: {"native_id": "inferred:conversation-directory"}`.

The CLI home can be moved for wadachi with `WADACHI_ANTIGRAVITY_HOME`; the
CLI documents no variable of its own.

## Record-to-event table

Raw keeps every field an event's data does not hold, per step type. A
review by another model (Antigravity, Gemini 4 Neon) compared all 6 sessions
with the raw files; its findings are fixed in converter 0.2.0. That is a
model's review, not a measurement.

| Step | Mapping | Status |
|---|---|---|
| `USER_INPUT` | `prompt`; actor human when `source` is `USER_EXPLICIT`, else caller (`how: inferred:not-user-explicit`); text as recorded, wrapper included | measured (1.5.18) |
| `SYSTEM_MESSAGE`, `EPHEMERAL_MESSAGE` | `context`, `name` the step type | measured (1.5.18) |
| `PLANNER_RESPONSE` | `setting` for a `model` that differs from the one before (the header takes the first), `reasoning` for `thinking`, `assistant_text` for `content`, `tool_call` per call, `usage` for the token counts, each with its pointer | measured (1.5.18) |
| `GENERIC` | `tool_result`: `text` the content, `status_as_recorded` the status; `of` the previous step's call when that step is a planner step with exactly one call (`how: inferred:next-step-answers-call`); an `error` field adds an `error` event | measured (1.5.18) |
| any other type | `record`, kept whole | |

## Tools to kinds

| Tool | Kind | `paths` from | Status |
|---|---|---|---|
| `run_command` | shell | | measured (1.5.18) |
| `view_file` | read | `AbsolutePath` | measured (1.5.18) |
| `write_to_file` | write | `TargetFile` | measured (1.5.18) |
| `search_web`, `read_url_content` | fetch | | measured (1.5.18) |
| `call_mcp_tool`, `mcp_*` | mcp | | measured (1.5.18) |
| `invoke_subagent` | subagent | | measured (1.5.18) |
| `manage_task`, `manage_subagents`, `send_message`, anything else | other | | measured (1.5.18) |

## Hooks

| Fact | Status |
|---|---|
| The SDK has `pre_turn` and `on_tool_error` hooks, and can save sessions to a chosen directory | documented (SDK) |
| The CLI has agent hooks | reported; check events and inputs against the current version |

## Known gaps

- No version, cwd or exit code is recorded in a conversation's files.
- Subagents and tasks are other conversations; the link is only in
  `messages/*.json` (`sender` such as `<conversation id>/task-65`), which is
  not read yet, so no `parent` is set.
- `steps/<index>/output.txt` can hold more than the step's content. It is
  listed and hashed, not read.
- The per-conversation SQLite database is the CLI's own record and exists
  even when the transcript does not. Its blobs are protocol buffers without a
  published schema; it is listed and hashed, not read.
