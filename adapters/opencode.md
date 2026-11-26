# OpenCode

The converter is `src/wadachi/convert/opencode.py`. It uses the shared base.
All facts below are measured against the database and installed OpenCode 1.19.6,
unless a limit or a constructed test is named. No session content is quoted.

## Discovery and schema

The database had 145 sessions, 37,013 messages and 148,241 parts. Recorded
`session.version` values were 1.18.30, 1.18.31, 1.18.32, 1.18.33, 1.18.35,
1.19.4 and 1.19.6. This field belongs to the session, not necessarily the
executable that last wrote each row.

Data lives under `$XDG_DATA_HOME/opencode`, or the default XDG data directory.
The installed 1.19.6 JavaScript confirms `OPENCODE_DB`: absolute paths are
used directly; relative paths are under that data directory. `:memory:` cannot
be read from another process and is rejected. Discovery also scans the standard
channel database names. `OPENCODE_DISABLE_CHANNEL_DB=1` or `true` limits it to
the default database. `OPENCODE_CONFIG_DIR` changes configuration, not data.
No legacy JSON files were found under `storage/session`, `storage/message` or
`storage/part`; this converter therefore implements the measured SQLite layout.
No OpenCode runtime is launched by discovery or conversion.

The live source is opened with `mode=ro`. The SQLite backup API copies it to a
temporary file, including committed WAL data. Queries run only on that copy.
There are no migrations, checkpoints, explicit write locks or live writes.

Schema measured in OpenCode 1.19.6; these are column names and declared types,
not values. `session.id`, `message.id` and `part.id` are primary keys.
`message.session_id` points to a session. Parts carry both `session_id` and
`message_id`. User and assistant message bodies live in the JSON `data` column.
Assistant `data.parentID` identifies the user message it answers.

| Table | Columns and types |
|---|---|
| `account` | `id` TEXT, `email` TEXT, `url` TEXT, `access_token` TEXT, `refresh_token` TEXT, `token_expiry` INTEGER, `time_created` INTEGER, `time_updated` INTEGER |
| `account_state` | `id` INTEGER, `active_account_id` TEXT, `active_org_id` TEXT |
| `control_account` | `email` TEXT, `url` TEXT, `access_token` TEXT, `refresh_token` TEXT, `token_expiry` INTEGER, `active` INTEGER, `time_created` INTEGER, `time_updated` INTEGER |
| `credential` | `id` TEXT, `integration_id` TEXT, `label` TEXT, `value` TEXT, `connector_id` TEXT, `method_id` TEXT, `active` INTEGER, `time_created` INTEGER, `time_updated` INTEGER |
| `data_migration` | `name` TEXT, `time_completed` INTEGER |
| `event` | `id` TEXT, `aggregate_id` TEXT, `seq` INTEGER, `type` TEXT, `data` TEXT |
| `event_sequence` | `aggregate_id` TEXT, `seq` INTEGER, `owner_id` TEXT |
| `message` | `id` TEXT, `session_id` TEXT, `time_created` INTEGER, `time_updated` INTEGER, `data` TEXT |
| `migration` | `id` TEXT, `time_completed` INTEGER |
| `part` | `id` TEXT, `message_id` TEXT, `session_id` TEXT, `time_created` INTEGER, `time_updated` INTEGER, `data` TEXT |
| `permission` | `id` TEXT, `project_id` TEXT, `action` TEXT, `resource` TEXT, `time_created` INTEGER, `time_updated` INTEGER |
| `project` | `id` TEXT, `worktree` TEXT, `vcs` TEXT, `name` TEXT, `icon_url` TEXT, `icon_url_override` TEXT, `icon_color` TEXT, `time_created` INTEGER, `time_updated` INTEGER, `time_initialized` INTEGER, `sandboxes` TEXT, `commands` TEXT |
| `project_directory` | `project_id` TEXT, `directory` TEXT, `type` TEXT, `strategy` TEXT, `time_created` INTEGER |
| `session` | `id` TEXT, `project_id` TEXT, `workspace_id` TEXT, `parent_id` TEXT, `slug` TEXT, `directory` TEXT, `path` TEXT, `title` TEXT, `version` TEXT, `share_url` TEXT, `summary_additions` INTEGER, `summary_deletions` INTEGER, `summary_files` INTEGER, `summary_diffs` TEXT, `metadata` TEXT, `cost` REAL, `tokens_input` INTEGER, `tokens_output` INTEGER, `tokens_reasoning` INTEGER, `tokens_cache_read` INTEGER, `tokens_cache_write` INTEGER, `revert` TEXT, `permission` TEXT, `agent` TEXT, `model` TEXT, `time_created` INTEGER, `time_updated` INTEGER, `time_compacting` INTEGER, `time_archived` INTEGER |
| `session_context_epoch` | `session_id` TEXT, `baseline` TEXT, `snapshot` TEXT, `baseline_seq` INTEGER |
| `session_input` | `id` TEXT, `session_id` TEXT, `prompt` TEXT, `delivery` TEXT, `admitted_seq` INTEGER, `promoted_seq` INTEGER, `time_created` INTEGER |
| `session_message` | `id` TEXT, `session_id` TEXT, `type` TEXT, `seq` INTEGER, `time_created` INTEGER, `time_updated` INTEGER, `data` TEXT |
| `session_share` | `session_id` TEXT, `id` TEXT, `secret` TEXT, `url` TEXT, `time_created` INTEGER, `time_updated` INTEGER |
| `todo` | `session_id` TEXT, `content` TEXT, `status` TEXT, `priority` TEXT, `position` INTEGER, `time_created` INTEGER, `time_updated` INTEGER |
| `workspace` | `id` TEXT, `type` TEXT, `name` TEXT, `branch` TEXT, `directory` TEXT, `extra` TEXT, `project_id` TEXT, `time_used` INTEGER |

`session.directory` supplies cwd. Unix times in the rows and JSON `time` fields
are integer milliseconds. Every measured message row's `time_created` matched
its JSON `time.created`. They convert exactly to UTC with no guessed zone.
`session.time_updated` and `time_archived` do not prove a session ended.

## Source snapshots and hashes

`f1` is a per-session SQLite snapshot. `f2` is reserved for a hook log. The
source path remains the database as found, with home shortened by the base.
The source format is `opencode-session-sqlite/1`.

One physical SQLite backup supplies a batch. Each session snapshot copies its
unchanged session, message and part rows, plus any parent task part needed to
prove a child link. Referenced parent messages, parent sessions and project
rows close the foreign keys. Original table DDL and exact column values are
copied; JSON strings are not rewritten. Table order and insertion by binary
id are fixed. Foreign keys are enabled during construction and checked by a
constructed test. This selected snapshot is not a database to open with the
OpenCode runtime.

The converter reads rows back from this physical per-session database and
hashes exactly its bytes, as SPEC.md 3.3 permits for a consistent snapshot.
It does not hash a JSON dump, a concatenation of row values, the live file, or
a file-plus-WAL combination. Updates confined to unrelated session, message
and part rows cannot change these bytes. Changes to referenced project or
parent context refresh dependent snapshots. `--keep-raw` retains this exact
readable SQLite snapshot.
The constructed test changes another session and proves the first session's
snapshot remains byte-identical. Dump skips mapping and writing unchanged
sessions, while a changed session is converted.

Source positions are `@session/<id>`, `@message/<id>` and `@part/<id>`, escaped
with `escape_key`. The record view decodes the JSON `data` column for pointers;
`raw.row.data` keeps its original string. A tool part produces a call at
`#/data` and a result at `#/data/state`, so their ids stay distinct and stable.
Usage and errors from the same message likewise have distinct pointers.
Moving the database changes provenance paths, not native session or event ids.

## Record-to-event table

This table describes the current materialized rows. The `event` table is an
update history, not another stream of tool calls. Replaying its updates would
duplicate calls and stale streamed text; it is not converted. Account,
credential, policy, todo and editor tables are not session events and are not
copied into session snapshots. Only their schema was inspected. Referenced
project rows are copied solely to preserve foreign keys.

| Source | Mapping | Status |
|---|---|---|
| Session row | header: native id, version, directory and recorded creation time; whole row in raw | measured (OpenCode 1.19.6) |
| User message row | setting with recorded model; metadata in raw | measured (OpenCode 1.19.6) |
| Assistant message row | usage from its tokens and cost; errors from its own error object; whole row in raw | measured (OpenCode 1.19.6) |
| User text part | prompt for that message, text unchanged; synthetic or proven task-child input uses caller | measured (OpenCode 1.19.6) |
| Assistant text part | assistant_text; a message marked summary becomes compaction text instead | measured (OpenCode 1.19.6) |
| Reasoning part | reasoning text, including an empty recorded string; opaque metadata remains in raw | measured (OpenCode 1.19.6) |
| Tool part | tool_call from state.input; terminal completed/error state adds tool_result linked to that same row's call | measured (OpenCode 1.19.6) |
| Tool task metadata.sessionId | subagent_start with derived child session id; no borrowed child-start timestamp | measured (OpenCode 1.19.6) |
| step-finish | usage from its own tokens and cost; reason and snapshot stay in raw | measured (OpenCode 1.19.6) |
| compaction | compaction marker; auto and tail_start_id stay in raw | measured (OpenCode 1.19.6) |
| step-start and patch | counted in skipped_parts; no invented git-tree observation or neighbouring event attachment | measured (OpenCode 1.19.6) |

All emitted events keep their complete original row. JSON numbers outside the
safe range and lone surrogates receive only the shared section-2 cleanup.
Missing text, tool names, arguments, exit codes and event times stay missing.
The measured user messages each had either one text part or a compaction part;
additional unrecognized parts are counted, not concatenated into invented text.

## Tool-to-kind table

These names were measured in OpenCode 1.19.6. The table is code, versioned with
the converter. Unknown tools are other; a model never classifies them.

| Names | Kind | Status |
|---|---|---|
| read | read | measured (OpenCode 1.19.6) |
| write | write | measured (OpenCode 1.19.6) |
| edit, apply_patch | edit | measured (OpenCode 1.19.6) |
| bash | shell | measured (OpenCode 1.19.6) |
| glob, grep | search | measured (OpenCode 1.19.6) |
| webfetch, websearch | fetch | measured (OpenCode 1.19.6) |
| task | subagent | measured (OpenCode 1.19.6) |
| invalid, question, skill, todowrite | other | measured (OpenCode 1.19.6) |
| rea_binary_overview, rea_binary_session, rea_close_binary, rea_execute_rizin_command, rea_export_evidence_bundle, rea_get_evidence_bundle, rea_inspect_analysis_settings, rea_inspect_binary_hardening, rea_inspect_elf_dependencies, rea_inspect_elf_notes, rea_inspect_go_binary, rea_inspect_native_exports, rea_inspect_rust_binary, rea_inspect_with_objdump, rea_open_binary, rea_search_guidance, rea_update_analysis_settings | mcp | measured (OpenCode 1.19.6) |

The known REA MCP names are explicit table entries. The generic `mcp__` prefix
fallback is tested with constructed data. Shell text is never parsed for paths.
Read, write and edit paths come from `input.filePath`; glob and grep use their
explicit input.path. Patch results keep every recorded metadata.files filePath
and movePath, in order. Arguments keep their original JSON types.

## States, timing and costs

There were 36,883 completed tool states, 210 error states and one running state.
The input object is state.input. Output and errors are state.output and
state.error. `status_as_recorded` is the exact state.status, independent of
`state.metadata.exit`; only an integer exit value becomes exit_code. Completed
status with a nonzero exit remains a failure. Null or missing exit values
never become zero. Tool duration remains in the recorded start/end fields;
no process duration is copied to another event. Truncation is preserved from
metadata.truncated; outputPath remains in raw, and that external file is not
read or substituted as if it were this row's output.

Tool calls and results use their own state.time.start and state.time.end.
Text and reasoning use their own time.start when present. A row creation or
update clock is a storage timestamp, not an invented model clock; using it is
marked with the corresponding how rule below. Native metadata clocks are not
borrowed from neighbouring events.

Record order is by fact time, then phase and stable key, with user input placed
at its message's recorded creation time and step-finish at its message's
recorded completion. This is needed because 773 user text parts were persisted
after a reply had started, and 20,650 step-finish rows were persisted well after
completion. Placement uses associated metadata; t still comes only from the
event's own row.
Tool call/result phases use distinct positions and are interleaved with other
records by their own times. Seq and turns are assigned by the base afterward.

Tokens input/output and cache read/write map to usage. Total and reasoning
counts remain in raw. Cost goes to x.opencode.cost as a canonical string,
never rounded or converted to another unit. Assistant messages and step-finish
parts can repeat request usage: they are separate source snapshots, not
additive deltas to sum across both streams.

## Parents, compaction and delivery

In the refreshed read-only snapshot, all 15 sessions with parent_id had
matching task-tool evidence:
the parent's task part metadata.sessionId names the child. The child's header
then names the parent and relation subagent. Both the task row and session row
are retained; no link is guessed from a title or directory. Zero parent ids
lacked evidence in this snapshot. The earlier 13-proven/two-ambiguous census
described an earlier snapshot. A parent_id without task evidence remains raw
without a guessed fork/subagent relation, as the constructed test checks.
No explicit fork marker was measured in the database.

There were 51 compaction parts and 51 assistant messages marked summary. The
summary text stays in compaction events, never assistant_text. Internal
reasoning on those messages stays reasoning; 18 such parts were measured.
Synthetic text is caller input. A compaction marker alone is not a new human
prompt. Patch hashes and step snapshots are not assumed to be observed git
tree transitions; there is no base event type for those records.

No persisted delivery flag was measured in messages. The session_input and
session_message tables were empty. Installed 1.19.6 code defines admission
delivery as steer or queue and defaults even an initial input to steer; that
label alone would not prove a mid-turn steer. The ordinary UserMessage schema
has no delivery field. A time overlap cannot distinguish a queued
prompt from an injected steer, so the converter does not guess steer from
arrival time. Its default message boundary and actor are explicitly inferred.
All ordinary user messages remain separate prompts; subsequent events get the
turn where they land, as SPEC.md 4.3 requires. The retained ids, clocks and
parentID fields allow a reader to audit this limit. Delivery semantics need a
real recorded marker before a more specific mapping can be claimed.

Permission had no rows and no permission-decision event type appeared in the
update log. Session permission policies remain in raw; an allow rule is not
proof that a particular request was allowed. No permission event is invented
from a failed call's error text. An observed decision needs another source.

## Inference rules

- inferred:user-message-boundary: the first text part of a distinct user
  message starts its prompt. There is no persisted steer/queued distinction.
- inferred:input-origin: root user input is treated as human; a proven task
  child or synthetic input is caller. API/headless origin is otherwise unknown.
- inferred:message-settings: user message metadata is a recorded settings
  snapshot; no model name or profile is filled from a neighbour.
- inferred:task-child: matching parent_id and task metadata.sessionId prove
  the child mapping. Unknown parent relations remain raw.
- inferred:task-session-link: a task tool's recorded child id supplies a
  subagent_start fact. Its exact child-start clock is not recorded here.
- inferred:summary-message: text on a message marked summary is the harness's
  compaction summary. Its source text is unchanged.
- inferred:row-created-time and inferred:row-updated-time: t is an actual
  storage-row clock because this part or usage snapshot has no native event
  clock. No timestamp is carried from another record.

## Self selection

Static inspection of the installed 1.19.6 JavaScript found inherited process
environment plus the shell.env plugin result passed to shell children. The
hook receives cwd, sessionID and callID, but core does not export a session id.
It exports OPENCODE and OPENCODE_PID, which identify the application/process,
not the current session. OPENCODE_ROUTE is an initial UI route and can become
stale; it is not used as current identity.

An optional wrapper/plugin may set OPENCODE_SESSION_ID, which dump accepts.
Otherwise, the current HERDR_PANE_ID selects that pane's recorded OpenCode
agent_session id. Without an exact id, dump uses the newest recorded
session.time_updated with directory equal to cwd and reports fallback on
stderr. The selection rule does not create a header field or change events.
Herdr --from-herdr keeps native ids through selection: one database path must
not expand a selected pane into every session in that database.
Unqualified --self uses the exported application marker when no exact id is
available and selects only the calling harness. Ambiguous caller identities
require an explicit --harness; peers are not dumped as extra fallbacks.

## Checks

Converter 0.1.3 converted all 145 discovered sessions with zero failures. All
145 passed validation. A second pass converted zero and skipped 145; live
Herdr selection skipped exactly its two selected OpenCode sessions.

Three real sessions were compared event by event with their database rows:
21,861 events, including a proven subagent, 19 terminal tool errors and 28
nonzero process exits. Source rows, pointers, text, arguments, timestamps,
usage, cost, paths, links, placement, turns and skip counts agreed. A second
agent independently checked four smaller sessions and 76 events, including
a subagent and both error states and failed exit codes, with no disagreement.
Detailed evidence remains private. All committed fixtures are constructed.
