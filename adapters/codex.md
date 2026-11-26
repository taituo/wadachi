# Codex CLI

The converter is `src/wadachi/convert/codex.py`. It uses the shared base.
No session content or identifying values appear in these notes or fixtures.

## Records

Discovery measured 16 rollouts across seven versions. A version in this table
is the file's `session_meta.cli_version`, not a claim about every later record
in a resumed file. Files can outlive the executable that created them.

| `cli_version` | Files | Top-level record types seen |
|---|---:|---|
| 0.154.0 | 5 | `session_meta`, `event_msg`, `response_item`, `world_state`, `turn_context`, `token_usage_record` |
| 0.157.1 | 1 | the same, plus `compacted` |
| 0.160.1 | 1 | the same, plus `compacted` |
| 0.162.1 | 2 | the same, plus `compacted` |
| 0.163.0 | 2 | the same, plus `compacted` |
| 0.164.0 | 1 | the six record types in the first row |
| 0.167.1 | 4 | the same, plus `compacted` |

| Fact | Status |
|---|---|
| Rollouts are JSON Lines under `CODEX_HOME/sessions`; default home is the Codex configuration directory | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `session_meta.payload.id` identifies the thread; `session_id` was equal in all 16 metadata records | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `session_meta` carries `cli_version`, `cwd`, `timestamp`, `source` and `thread_source`; some carry `git.commit_hash` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| Each outer record has its own `timestamp`; every measured timestamp has a UTC zone | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `response_item` message blocks have `type` and `text`; metadata has `content_item_kinds` and `turn_id` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| User input is marked `user.text` or `user.image`; environment and instruction blocks have other kinds | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| Automated goal input is a user-role message marked `goal.internal_context`, with the active task's `turn_id`; four such records were found | measured (codex-cli 0.157.1) |
| UI `UserMessage` items carry `turn_id`, `content` and `client_id`; multiple user messages can share a turn id | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `function_call.arguments` is a JSON-encoded string | measured (codex-cli 0.154.0, 0.157.1, 0.162.1, 0.163.0, 0.167.1) |
| `custom_tool_call.input` is a string; outer `exec` calls contain JavaScript | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| Call outputs can be strings or lists of `input_text` and `input_image` blocks | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `CommandExecution` has `exit_code`, `status`, `duration.secs`, `duration.nanos`, `command`, `cwd` and `aggregated_output`; some also have `stdout` and `stderr` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `CommandExecution.id` did not match the outer response calls' `call_id` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `compacted` has `message`, `replacement_history` and `resume_metadata`; a replacement history is not a new sequence of prompts | measured (codex-cli 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `token_count.info` holds `last_token_usage` and `total_token_usage`; `token_usage_record` holds `usage`, `turn_token_usage` and `thread_token_usage` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| No truncated duplicate files, explicit parent links, headless sources or `ghost_snapshot` records were found | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1); absence in this corpus only |

`f1` is the rollout. `f2` is reserved for a hook log. Byte offsets identify
records without unique ids. Response item ids and completed item ids use
separate stable key namespaces; content blocks add their actual JSON Pointer.
Repeated native record ids fall back to byte offsets. No filename supplies a
missing native id or timestamp.

## Record-to-event table

Every emitted event keeps the whole payload in `raw.payload`, including fields
not mapped. Header metadata keeps the complete `session_meta` payload in `raw`.
Records without events are counted by type in `x.codex.skipped_records`.

| Source | Mapping | Status |
|---|---|---|
| `session_meta` | header: native id, version, recorded cwd, start time, git commit | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `turn_context` | `setting`, with recorded model, cwd and effort | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `world_state` | `setting`; only string model values map, other state stays in raw | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `response_item/message`, user | `prompt` or `steer`; instruction and environment blocks are excluded by `content_item_kinds` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `response_item/message`, user, `goal.internal_context` | program input: caller `prompt` for the first input in its recorded turn, otherwise caller `steer` | measured (codex-cli 0.157.1) |
| `response_item/message`, assistant | one `assistant_text` per text block, each with a pointer | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `response_item/message`, other roles (`developer`) | `context`, one per content block: `role` as recorded, `name` the block's `content_item_kinds` entry when there is one; never human input | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `response_item/message`, user, blocks of other `content_item_kinds` (environment, instructions) | `context`, role `user`, `name` the kind; the user's own blocks still make the prompt | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `response_item/reasoning` | text blocks as `reasoning`; summaries are redacted, encrypted content stays in raw with `redacted: true` | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `response_item/function_call`, `custom_tool_call` | `tool_call`; arguments and input stay strings | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1); function calls absent in 0.160.1 |
| `response_item/function_call_output`, `custom_tool_call_output` | `tool_result`, linked by the recorded call id; multi-block output stays in raw unless it contains exactly one text block | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1); function outputs absent in 0.160.1 |
| `response_item/additional_tools` | `setting`, declarations in raw | measured (codex-cli 0.162.1, 0.164.0, 0.167.1) |
| `response_item/configuration_update` | `setting`, reasoning effort when recorded | measured (codex-cli 0.167.1) |
| `event_msg/task_started` | used for turn context; counted | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `event_msg/task_complete` | counted; completing a turn is not ending a session | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `event_msg/turn_aborted` | `interrupt`, recorded reason, actor harness | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `event_msg/thread_settings_applied` | `setting`, other settings in raw | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `event_msg/token_count` | `usage` from `last_token_usage`; totals and rate limits stay in raw | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `event_msg/thread_goal_updated` | counted; no matching base event type | measured (codex-cli 0.157.1) |
| `event_msg/item_completed`, `UserMessage` | fallback input when no corresponding response input exists in that turn | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `event_msg/item_completed`, `AgentMessage` | fallback `assistant_text`; matching response ids suppress the duplicate; unmatched asynchronous messages remain | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1); asynchronous delivery measured in 0.162.1, 0.163.0 and 0.167.1 |
| `event_msg/item_completed`, `Reasoning` | fallback reasoning; matching response ids suppress the duplicate | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `event_msg/item_completed`, `CommandExecution` | shell `tool_result`, exit code and status side by side; duration remains in raw | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `event_msg/item_completed`, `FileChange` | edit `tool_result`; every key in `changes` becomes a path, in order | measured (codex-cli 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `event_msg/item_completed`, `ImageView` | read `tool_result`, recorded path | measured (codex-cli 0.160.1, 0.162.1) |
| `event_msg/item_completed`, `McpToolCall` | mcp `tool_result`, recorded tool and status; arguments, result and duration in raw | measured (codex-cli 0.157.1, 0.162.1) |
| `event_msg/item_completed`, `Extension` | `tool_result`; `web.search` is fetch, `clock.sleep` is other | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `event_msg/item_completed`, `ContextCompaction` | `compaction`, without borrowing the summary from another record | measured (codex-cli 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `token_usage_record` | `usage` from request `usage`; turn and thread totals in raw | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.164.0, 0.167.1) |
| `compacted` | `compaction.text` from `message`; replacement history stays in raw | measured (codex-cli 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `ghost_snapshot` and unknown types | counted, not attached to a neighbouring event | unmeasured; constructed test only |

## Tool-to-kind table

These tool names were seen in response calls or UI MCP completions. Command
text is never parsed to guess a different tool kind or file path.

| Tool | Kind | Status |
|---|---|---|
| `exec` | other; JavaScript orchestration | measured (codex-cli 0.154.0, 0.157.1, 0.160.1, 0.162.1, 0.163.0, 0.167.1) |
| `wait` | other | measured (codex-cli 0.154.0, 0.157.1, 0.162.1, 0.163.0, 0.167.1) |
| `sleep` | other | measured (codex-cli 0.157.1, 0.167.1) |
| `request_user_input_async` | other | measured (codex-cli 0.162.1, 0.163.0, 0.167.1) |
| `search_service.web_run` | mcp, from `McpToolCall` | measured (codex-cli 0.162.1) |
| `github.list_repositories` | mcp, from `McpToolCall` | measured (codex-cli 0.157.1) |
| `github.search_repositories` | mcp, from `McpToolCall` | measured (codex-cli 0.157.1) |

The fixed fallback for names beginning `mcp__` is mcp; it is covered by a
constructed test, not by a response tool in this corpus. All other unknown
names are other. UI item kinds use their own fixed table shown above. Missing
tool names stay missing, including on inner shell completion records.

## Rules and quirks

- `inferred:shared-turn-user-message`: the first mapped input with a recorded
  turn id is a prompt; another with the same id is a steer. Inputs include
  human messages and automated goal messages. A queued input with a different
  id starts its own prompt even while an earlier task remains active. Without
  an input's own id, the active task id is used. Without either id, the input
  starts a prompt. This is an inference, not an explicit queued-message flag.
  Repeated user messages within a turn were measured across the corpus; the
  individual delivery mechanism is not recorded.
- `inferred:goal-context-input`: a user-role message whose kinds include
  `goal.internal_context` but no `user.text` or `user.image` is input from a
  program continuing a goal. It maps to actor caller, never harness: SPEC.md
  4.2 allows human and caller prompts. Its first input starts the turn at that
  record, and its text comes only from the goal-context blocks. Both type and
  actor are marked inferred on that prompt. A later goal message in the same
  turn is a caller steer, with the shared-turn type rule and this actor rule.
  A mixed user-and-goal message keeps the ordinary user actor and user text.
  This shape was measured in codex-cli 0.157.1; converter 0.1.2 fixes its
  earlier exclusion. The first real human message after automated work in the
  same task is therefore a steer. Earlier work, usage and subsequent work
  remain in the goal's turn, and its digest starts at the recorded goal input.
- `task_started` alone does not supply a prompt: it precedes normal human
  prompts too. Completion or abortion closes active-task fallback and never
  starts a turn. A later input with a new task id starts a new prompt. A task
  aborted without any recorded input creates no invented prompt. As SPEC.md
  4.3 requires, settings before the initiating input remain before the turn;
  raw harness ids are retained, not substituted for derived turn numbers.
- `inferred:item-id-matches-call`: a completed UI item's id matches a recorded
  response call id. Only then does its result get `of`. This was measured for
  clock extension items in codex-cli 0.157.1 and 0.167.1. No proximity matching
  connects inner shell commands to outer JavaScript calls.
- User inputs appear in both response and UI streams. The response stream is
  primary; per-turn occurrence counts suppress matching UI copies. Assistant
  and reasoning copies are matched by their recorded ids. These duplicate
  streams were measured in all versions above. Goal-context records do not
  count as human UI copies.
- The source can keep both an opaque reasoning response and a UI completion;
  neither its text nor a neighbouring timestamp is substituted for the other.
- Token-count snapshots and request usage records can repeat the same numbers.
  They are separate source facts. Do not sum both streams as usage deltas.
- A completed turn can be followed by more turns in the same file. No session
  end or duration is inferred from it. Compaction replacement histories are
  preserved, never replayed as fresh user input.
- Status does not stand in for an exit code. `CommandExecution.status` maps to
  `status_as_recorded`; `exit_code` maps independently. Missing or noninteger
  exit codes remain unmapped. Durations stay in their source's raw payload.

## Discovery and dump

`CODEX_HOME` overrides the configuration home. Discovery reads the first
complete metadata line and reports native id, path and byte size. Conversion
reads a complete-line snapshot once through the shared base.

`CODEX_THREAD_ID` and `CODEX_SESSION_ID` were present in child-process
environments; both matched the calling thread's metadata id in the measured
codex-cli 0.167.1 session. `--self` prefers `CODEX_THREAD_ID`, then
`CODEX_SESSION_ID`. If neither identifies a discovered rollout, dump selects
the newest rollout by file modification time whose recorded `cwd` equals the
current directory, and reports that fallback on stderr. Nothing is guessed
into the session header by this selection rule.

Herdr's read-only `api snapshot` returns
`result.snapshot.panes[].agent_session`. Its `agent`, `kind` and `value` fields
identify a harness session when kind is id. Duplicate panes are deduplicated.
Aliases claude and agy select claude-code and antigravity converters when
registered. Panes without an id are ignored; selected ids missing from discovery
count as failures. No prompts are sent to agents.

Dump skips matching source hashes with the same converter version. `--keep-raw`
retains exactly the converted snapshot bytes under their hash, including on a
skipped conversion. A partial final line is neither hashed nor retained.

## Limits and unmeasured cases

- No measured rollout used a headless exec source. The explicit source value
  exec maps to headless and caller in constructed tests. CLI maps to interactive;
  an IDE source alone does not prove protocol mode or caller ownership.
- No measured file carried `forked_from_id` or a subagent parent link. Those
  supported shapes are tested only with invented values: `forked_from_id` maps
  to fork, and `source.subagent.thread_spawn.parent_thread_id` maps to subagent.
  A child thread id is already machine-wide; no parent prefix is added.
- Resumption metadata was measured inside compaction records. It does not prove
  a separate child session or a parent relation, so none is invented. Separate
  child rollouts are discovered as separate sessions.
- No ghost snapshot was measured. The format has no base event for it; its
  count is exposed and its source bytes remain authoritative.
- The measured records do not provide git tree transitions, a reliable inner
  shell-to-outer-call link, a distinct session-end marker, or an explicit
  prompt-versus-steer flag. No hook lifecycle was measured. A wrapper or hook
  is needed for independent tree and process observations. Shell exit codes
  and durations *are* recorded in the UI completion stream.

## Checks

Converter 0.1.1 converted all 16 discovered rollouts with zero failures. All
16 outputs passed validation. An incremental pass skipped 15 unchanged
rollouts and converted one live rollout. Live self and Herdr selection passed.

Three rollouts were compared event by event against their sources: 740 events,
including nine failed shell results and one steer. The comparison checked
source positions, text, timestamps, arguments, exit status, links, usage,
turns and skip counts. All fixtures in the test suite are constructed.

Converter 0.1.2 re-converted all 16 rollouts with zero failures and clean
validation. Comparing 0.1.1 and 0.1.2 on identical source snapshots changed
existing turn numbers in one session and zero other sessions. Four recorded
goal inputs became caller prompts. The goal-driven sample was re-checked
from its initiating input through task completion: all 1,163 mapped events,
including 195 usage records before the human steer and five after it, remained
in the goal's turn. The constructed regression includes that sequence and an
expected full canonical output. Another test compares every mapped record's
turn to its recorded harness turn id across normal, queued, goal and aborted
tasks.
