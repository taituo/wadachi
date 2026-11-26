# Constructed Codex fixtures

These records are built by hand. Field names, nesting, types and order follow
the rollout format. All text, code, ids, paths, versions, counts and timestamps
are invented. No record was copied from a real session. Home is `/home/user`.

`goal-continuation.constructed.jsonl` records a task start, its program-supplied
goal input, agent reasoning, a tool call and result, usage, a human steer and
its UI copy, further work and usage, and task completion.

`goal-continuation.expected.jsonl` is the expected full canonical conversion.
It is marked constructed in its header, converter and source format, as
WHY.md's “Forge” requires. The test substitutes the invented provenance path
before comparing bytes; the actual input hash is still checked.
