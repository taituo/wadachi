# Claude Code

The converter is `src/wadachi/convert/claude_code.py`. It uses the shared base.
No session content or identifying values appear in these notes or fixtures.

## Records

Measured on one machine: 5 session transcripts and 1 subagent transcript, all
written by Claude Code 2.1.296. That is a small corpus. Rows marked
**reported** or **documented** were not seen in it.

| Fact | Status |
|---|---|
| Transcripts are JSON Lines at `CLAUDE_CONFIG_DIR/projects/<encoded cwd>/<session id>.jsonl`; the default config directory is `~/.claude` | measured (2.1.296) |
| Subagent transcripts are at `projects/<encoded cwd>/<parent session id>/subagents/agent-<agent id>.jsonl`, next to `agent-<agent id>.meta.json` | measured (2.1.296) |
| Subagent lines carry the parent's `sessionId`, their own `agentId`, and `isSidechain: true`. The agent id is unique only within the parent, so the native id is `<sessionId>/<agentId>` | measured (2.1.296) |
| `meta.json` holds `agentType`, `isBuiltIn`, `description`, `toolUseId` (the parent's `Agent` call), `spawnDepth`, `requestShape`, `requestNonInteractive` | measured (2.1.296) |
| Conversation records (`user`, `assistant`, `attachment`, `system`) carry a unique `uuid`, `parentUuid`, `timestamp`, `sessionId`, `version`, `cwd`, `gitBranch`, `entrypoint`, `userType` | measured (2.1.296); no repeated uuid in a file |
| Bookkeeping records have no uuid or timestamp: `mode`, `permission-mode`, `atis-latch`, `file-history-snapshot`, `last-prompt`, `ai-title`, `custom-title`, `agent-name`, `cost-state`; `queue-operation` has a timestamp | measured (2.1.296) |
| Every measured timestamp has a UTC zone (`Z`) | measured (2.1.296) |
| An `assistant` line holds exactly one content block. Blocks of one API message are consecutive lines that share `message.id` and repeat `message.usage` | measured (2.1.296) |
| `thinking` blocks were all empty with a `signature`: the reasoning is not kept | measured (2.1.296) |
| A human prompt is a `user` line with string content and `origin: {"kind": "human"}`, `promptSource: "typed"`, `turnOrigin`, `turnPosition` | measured (2.1.296) |
| Slash commands (`<command-name>…`) and their local output (`<local-command-stdout>…`) are `user` lines without `origin`; a caveat line before them has `isMeta: true` | measured (2.1.296) |
| A tool result is a `user` line whose content holds `tool_result` blocks; the line also has `toolUseResult` (structured result), `sourceToolAssistantUUID` and sometimes `permissionDecision` | measured (2.1.296) |
| `toolUseResult` for `Bash` holds `stdout`, `stderr`, `interrupted`, `isImage`, `noOutputExpected`; **no exit code** | measured (2.1.296) |
| `tool_result.content` is a string or a list of text blocks; `is_error` is present on some | measured (2.1.296) |
| `WebFetch` returns the answer of a second model to the call's `prompt`, not the page; the page is not in the transcript | measured (2.1.296), and documented |
| The `Agent` tool can run a subagent in **hand-back** mode: the tool result is a harness note (`toolUseResult.handback: "send"`, `handbackReport`, `agentId`), and the report arrives later as an `attachment` of type `queued_command` whose `origin` is `{"kind": "peer", "from": <agent id>, "handback": true, "body": …}` | measured (2.1.296) |
| The same hand-back appears as a `queue-operation` pair (`enqueue`, then `remove` with reason `absorbed_mid_turn`) | measured (2.1.296) |
| API failures are `assistant` lines with `isApiErrorMessage: true` and `error` (for example `authentication_failed`) | measured (2.1.296) |
| `attachment` lines carry injected context, with the exact text the model was given in `rendered` (a list of `{content}` blocks) and its role in `renderedRole` (`system` or `user`): `prompt_snapshot` (the full system prompt), `environment`, `model`, `date`, `session_context` (which includes the account's email address), `deferred_tools_delta`, `agent_listing_delta`, `skill_listing`, `mcp_instructions_delta`, `total_tokens_reminder`, `remote_session_change`, `credential_org`, `plan_mode` | measured (2.1.296) |
| `system` lines seen: `turn_duration`, `away_summary` | measured (2.1.296) |
| Compaction writes a `system` line with subtype `compact_boundary` and `compactMetadata.preTokens`, followed by a `user` line with `isCompactSummary: true` | reported; not in this corpus |
| An interrupt is a user text `[Request interrupted by user]` or `[Request interrupted by user for tool use]` | reported; not in this corpus |
| `CLAUDE_CODE_ENTRYPOINT` is `cli` for the interactive app and `sdk-*` for headless use | documented; only `cli` measured |

`f1` is the transcript. `f2` is reserved for a hook log. `f3` is a subagent's
`meta.json` (role `aux`, no events). Positions are `@<uuid>`; records without a
uuid use byte offsets; one content block adds `#/message/content/<i>`, a usage
event `#/message/usage`, a permission event `#/permissionDecision`. No
filename supplies a native id or a parent: both come from recorded
`sessionId` and `agentId`.

## Record-to-event table

Every event keeps the record's other fields in `raw` (the message without its
`content`, `toolUseResult`, `origin` and so on). Records without events are
counted by type in `x.claude-code.skipped_records`.

| Source | Mapping | Status |
|---|---|---|
| first `version`, `cwd`, `entrypoint`, `gitBranch` | header `harness.version`, `cwd`; `entrypoint` and `gitBranch` in `raw` | measured (2.1.296) |
| `entrypoint` | `mode`: `cli` is `interactive`, `sdk-*` is `headless`; a subagent is `subagent` | measured for `cli`; documented for `sdk-*` |
| first `model` attachment, else first assistant `message.model` | header `model` | measured (2.1.296) |
| subagent `sessionId` | header `parent` (relation `subagent`) and `invoked_by` (`agent`); `meta.json` `agentType` is `agent.name`, its other fields go to `raw.subagent_meta` | measured (2.1.296) |
| `user`, string content, `origin.kind` `human` | `prompt`, actor human | measured (2.1.296) |
| `user`, string content, other `origin.kind` | `prompt`, actor caller | not measured |
| `user`, string content, no `origin` | `prompt`; actor human with `how: inferred:interactive-entrypoint` when `entrypoint` is `cli`, caller with `inferred:non-interactive-entrypoint` otherwise, caller with `inferred:subagent-task` in a subagent | measured (2.1.296) |
| `user` with `isMeta: true` | `context`, role `user`: harness text the model was given (caveats, reminders) | measured (2.1.296) |
| `user` text starting `<local-command-stdout>`, `<local-command-stderr>` or `<local-command-caveat>` | `context`, role `user`: written by the harness, not a prompt | measured (2.1.296) for stdout and caveat |
| `user` text that is exactly an interrupt marker | `interrupt`, actor human, `how: inferred:interrupt-marker` | reported |
| `user` with `isCompactSummary: true` | `compaction` with the summary as `text` | reported |
| `user`, `tool_result` block | `tool_result` linked by `tool_use_id`; `text` when the content is a string or one text block; `is_error` as `status_as_recorded`; no `exit_code` (none recorded) | measured (2.1.296) |
| `user`, text block beside `tool_result` blocks | `steer` (`how: inferred:text-beside-tool-result`), or `interrupt` for a marker | reported |
| `user`, `permissionDecision` | `permission`: `accept` is `allowed`, `reject` or `deny` is `denied`; `reasonType` is `rule`; actor human when `source` is `user`, else harness; `of` the call when the line holds one result | measured (2.1.296) for `accept` from `config` |
| `assistant`, `text` block | `assistant_text` | measured (2.1.296) |
| `assistant`, `thinking` block | `reasoning`; empty thinking is `redacted: true`, signature in `raw.block` | measured (2.1.296) |
| `assistant`, `redacted_thinking` block | `reasoning`, `redacted: true` | reported |
| `assistant`, `tool_use` block | `tool_call`: `tool`, `kind`, `call_id`, `args` as recorded, `paths` per the table below | measured (2.1.296) |
| `assistant`, last line of a `message.id` | `usage` from `message.usage` | measured (2.1.296) |
| `assistant` with `isApiErrorMessage: true` | `error`, actor harness, `code` from `error`, `text` from the message | measured (2.1.296) |
| `attachment` `model` | `setting` with `model`, and its rendered text as `context` | measured (2.1.296) |
| `attachment` with `rendered` (all other types except `queued_command`) | `context`, one per rendered block: `name` the attachment type, `role` from `renderedRole`, `text` the block's `content`; the attachment's structured fields in `raw` once | measured (2.1.296) |
| `attachment` `prompt_snapshot` | `context`, one per `systemPrompt` section, role `system`; the rest of the snapshot (tool list, rendering settings) in `raw` of the first | measured (2.1.296) |
| `attachment` `queued_command`, `origin.kind` `peer` and `handback` | `subagent_end`, actor agent: `text` is the delivered `prompt`, `text_origin: agent`, `session` the child's id, `of` the `Agent` call whose result recorded the same `agentId` (`how: inferred:agent-id-matches-tool-result`) | measured (2.1.296) |
| `attachment` `queued_command`, `origin.kind` `human` | `steer`, actor human | not measured |
| `attachment` without `rendered`, such as `credential_org` | none: not given to the model | measured (2.1.296) |
| `system` `compact_boundary` | `compaction`, `before_tokens` from `compactMetadata.preTokens` | reported |
| `cost-state` | none; the last one goes to header `x.claude-code.cost_state`, numbers that are not integers as strings | measured (2.1.296) |
| other `system` subtypes, bookkeeping records, `queue-operation` | none | measured (2.1.296) |

## Tools to kinds

| Tool | Kind | `paths` from | `text_origin` of its result | Status |
|---|---|---|---|---|
| `Read` | read | `file_path` | | documented |
| `Write` | write | `file_path` | | documented |
| `Edit`, `MultiEdit` | edit | `file_path` | | documented |
| `NotebookEdit` | edit | `notebook_path` | | documented |
| `Bash` | shell | | | measured (2.1.296) |
| `Glob`, `Grep` | search | `path` | | documented |
| `WebFetch` | fetch | | `model` | measured (2.1.296) |
| `WebSearch` | fetch | | | documented |
| `Agent` (named `Task` in older versions) | subagent | | `tool` when `toolUseResult.handback` is `"send"`; `agent` when there is no `handback`; left out for any other value | measured (2.1.296) for hand-back |
| `mcp__<server>__<tool>` | mcp | | | documented |
| anything else, including `SubagentHandback`, `TodoWrite` | other | | | measured (2.1.296) for `SubagentHandback` |

## Privacy

A transcript holds more than the conversation: the full system prompt
(`prompt_snapshot`), the account's e-mail address (`session_context`) and the
organization id. Since converter 0.2.0 the first two are `context` events,
because the model was given them; the organization id is not. Treat a store
like the transcripts themselves, and apply the `secrets` layer to anything
given to a model or exported (SPEC.md section 13).

## Known gaps

- No exit code is recorded for shell calls. A hook observation is needed.
- Built-in checkpoints rewind edits made through the edit tools; shell writes
  are outside them (documented). The `tree_before`/`tree_after` hook
  observation is still needed.
- The parent's `Agent` call is named in `meta.json` (`toolUseId`), but its
  event id needs the parent's record, so `parent.event` is left out.
- Not measured: compaction, interrupts, headless runs, resumed and forked
  sessions, images, MCP calls.
