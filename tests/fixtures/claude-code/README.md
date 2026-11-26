# Constructed Claude Code fixtures

These records are built by hand. Field names, nesting, types and order follow
Claude Code 2.1.296 transcripts. All text, ids, paths, versions, counts and
timestamps are invented. No record was copied from a real session. Home is
`/home/user`.

`parent.constructed.jsonl` records bookkeeping lines, a model attachment, a
typed prompt, an empty signed thinking block, an `Agent` call in hand-back
mode with its permission decision and harness note, the subagent's report
delivered as a `queued_command`, an answer, a slash command and its local
output, a turn with a `WebFetch` and a failed `Read` in one API message and an
interrupt marker beside their results, and an API error.

`parent-session/subagents/agent-a0constructed01.jsonl` and its `.meta.json`
are the subagent: its task prompt, a `WebFetch` and its result, and the
`SubagentHandback` call.

`parent.expected.jsonl` and `child.expected.jsonl` are the expected full
canonical conversions, marked constructed in `x.fixture`. The test substitutes
the invented provenance paths before comparing bytes; the input hashes are
still checked.
