# Antigravity CLI

Documentation of the on-disk layout is sparse. Everything below comes from
third-party experiments unless marked otherwise.

## Records

| Fact | Status |
|---|---|
| Conversations live under `~/.gemini/antigravity-cli/brain/<conversation id>/` | reported |
| `.system_generated/logs/transcript.jsonl` holds a shortened transcript and `transcript_full.jsonl` the untruncated one; each line is a step with fields such as `step_index`, `source`, `type` and `content` | reported |
| `conversations/` holds conversation data as protocol buffers, and a top-level `history.jsonl` appears to index conversations | reported |
| `/fork` branches a conversation from a chosen step; `agy --conversation=<id>` resumes one | reported |
| Session history has been lost after an unclean shutdown | reported by users; keep your own copies of the raw files |

Mapping notes:

- Read events from `transcript_full.jsonl`. List `transcript.jsonl` in `files`
  only if you read anything from it, with `truncated: true`.
- If `step_index` turns out to be stable when the harness rewrites a
  transcript (unverified), positions are `@step/<index>`; otherwise byte
  offsets.
- A fork should point at its parent conversation and step: header `parent`
  with relation `fork` and the step's event id. Whether the record shows the
  parent is unverified.

## Hooks

| Fact | Status |
|---|---|
| The SDK has `pre_turn` and `on_tool_error` hooks, and can save sessions to a chosen directory | documented (SDK) |
| The CLI has agent hooks | reported; check events and inputs against the current version |

## Tools to kinds

Not yet known. Fill this table from a real `transcript_full.jsonl`, one row per
tool name seen, with the version.
