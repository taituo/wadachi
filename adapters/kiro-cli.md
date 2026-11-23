# Kiro CLI

The harness behind the first measurements of this project. A read-only session
reader for it exists (ksess), which a converter to wadachi can build on.

## Records

| Fact | Status |
|---|---|
| Sessions are files on disk, in three record formats across versions | measured, 2,654 sessions on 2026-11-23 |
| The oldest format (v2) has no permission approvals, and its tool output is not searchable | measured |
| Shell calls that exited with 1 are recorded with `status: success`; the truth is in the result's exit status | measured |
| A prompt sent while a turn runs is queued; durations and costs of queued turns have been merged by a reader that did not account for it | measured |
| Cost is recorded in credits, per request | documented; goes to `x.kiro.credits`, as a string |
| The location of session files | unverified: record it here from a real machine |

## Hooks

| Fact | Status |
|---|---|
| `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse` and `stop`, configured per agent in the agent definition | measured |
| Hook output reaches the model wrapped in an instruction to follow it | measured; wadachi hooks must print nothing |
| A configuration sync can overwrite agent definitions, and the hooks with them | measured; install hooks idempotently and check they are still there |
| Protocol mode (ACP), where a client approves every tool call | measured; header `mode: "protocol"`, the client in `middleware` |

## Tools to kinds

The names come from the reader built for this harness; confirm each row against
the version you convert.

| Tool | Kind | Status |
|---|---|---|
| `fs_read` | read | unverified |
| `fs_write`, command `create` | write | unverified |
| `fs_write`, other commands (`str_replace`, `insert`, `append`) | edit | unverified |
| `execute_bash` | shell | unverified |
| `use_aws` | other | unverified |
| `use_subagent` | subagent | unverified |
| `knowledge`, `introspect`, `report_issue`, `todo_list`, `thinking` | other | unverified |
| MCP tools | mcp | unverified: check how their names are written |

## Known gaps

- Instructions the model received (skill descriptions as rendered, steering
  files) are not stored with the session. A `manifest` hook event at session
  start closes this.
- Multi-line YAML skill descriptions have reached the model as the literal
  text `>-` (measured). A manifest makes such regressions visible.
