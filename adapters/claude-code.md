# Claude Code

## Records

| Fact | Status |
|---|---|
| Every hook receives `session_id` and `transcript_path`, the path of the session's transcript | documented |
| The transcript is written asynchronously and can lag the current turn; the final assistant text of a turn is given to `Stop` and `SubagentStop` hooks as `last_assistant_message` | documented |
| The transcript is JSON Lines, one record per line, under `~/.claude/projects/<encoded working directory>/<session id>.jsonl` | unverified |
| Records carry their own UUIDs, so positions can be `@<uuid>` | unverified |
| An assistant record holds several content blocks (text, tool uses); each becomes an event with its own pointer, such as `#/message/content/2` | unverified |
| Subagent transcripts are kept as separate files, linked to the parent session | unverified: find where, and how the parent is named |

## Hooks

Documented events useful to wadachi: `SessionStart`, `UserPromptSubmit`,
`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`,
`PermissionRequest`, `PermissionDenied`, `SubagentStart`, `SubagentStop`,
`PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`,
`InstructionsLoaded`, `FileChanged`, `CwdChanged`, `Stop` and `SessionEnd`.

- Plain standard output of `UserPromptSubmit`, `UserPromptExpansion`,
  `SessionStart` and `PostModelSwitch` hooks is added to the model's context,
  and `additionalContext` in structured output is added on many more events,
  wrapped as a system reminder (documented). A wadachi hook writes only to its
  own log and prints nothing.
- `InstructionsLoaded` is the natural source for a `manifest` event.
- `PostToolUseFailure` and `PermissionDenied` are direct sources for failures
  and permission decisions.
- Headless runs use print mode (`claude -p`): header `mode: "headless"`.

## Tools to kinds

| Tool | Kind | Status |
|---|---|---|
| `Read` | read | unverified |
| `Write` | write | unverified |
| `Edit`, `NotebookEdit` | edit | unverified |
| `Bash` | shell | unverified |
| `Glob`, `Grep` | search | unverified |
| `WebFetch`, `WebSearch` | fetch | unverified |
| `Agent` (named `Task` in older versions) | subagent | unverified |
| `TodoWrite` and other planning tools | other | unverified |
| `mcp__<server>__<tool>` | mcp | unverified |

## Known gaps

- Built-in checkpoints rewind edits made through the edit tools; shell writes
  are outside them. The `tree_before`/`tree_after` hook observation is still
  needed.
