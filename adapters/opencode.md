# OpenCode

## Records

| Fact | Status |
|---|---|
| Sessions are in a SQLite database; `opencode db path` prints its location | reported |
| Older versions keep JSON files: session info under `storage/session/<project hash>/ses_*.json`, contents under sibling `storage/message/` and `storage/part/` | reported |
| Message metadata includes `sessionID`, `role`, `time.created`, `agent`, the model's provider and id, and `path.cwd` | reported |
| Sessions, messages and parts have ids (`ses_…`, `msg_…`, `prt_…`), so positions are keys such as `@part/prt_…` | reported |
| Fields of tool parts (state, input, output, exit status, times) | unverified: inspect real parts |

## Hooks

Server plugins can hook (documented):

| Domain | Hook | Use for wadachi |
|---|---|---|
| Tools | `execute.before`, `execute.after` (`status` is `completed` or `error`) | call timing, outcome |
| Shell | `create.before` (command, working directory, environment) | real shell commands |
| Permissions | `evaluate` | `permission` events |
| Session | `fork` | `parent` with relation `fork` |
| Session | `compaction` | `compaction` events |
| Session | `context` (system prompt, messages, tools) | the `manifest` |
| Session | `retry` | `error` events |

Plugins run inside the OpenCode process, so tree snapshots around a tool call
can be taken in `execute.before` and `execute.after`. A plugin must not change
the request or the context; it records only.

## Tools to kinds

| Tool | Kind | Status |
|---|---|---|
| `read`, `list` | read | unverified |
| `write` | write | unverified |
| `edit`, `patch` | edit | unverified |
| `bash` | shell | unverified |
| `glob`, `grep` | search | unverified |
| `webfetch` | fetch | unverified |
| `task` | subagent | unverified |
| `todowrite`, `todoread` | other | unverified |
| MCP tools | mcp | unverified |
