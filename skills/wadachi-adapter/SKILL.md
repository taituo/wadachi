---
name: wadachi-adapter
description: Write or fix a converter that turns a coding agent harness's session files (Claude Code, Codex, OpenCode, Antigravity, Kiro or any other) into the wadachi format, and the hooks that record what the session files miss. Use when asked to support a new harness, when a harness's record format changes, or when a converter's output fails validation or disagrees with the raw files.
---

# Writing a wadachi adapter

An adapter has two parts: a **converter** that reads a harness's own session
files and writes wadachi, and optional **hooks** that record what those files
do not (real exit codes, what changed on disk). The format is in SPEC.md of the
wadachi repository; read sections 1 to 7 before you start. Next to this file is
`converter_template.py`, a working converter for a toy format: copy it, and
fill in only the marked parts.

The one rule that matters most: **never invent.** A converter that fills a gap
with a plausible value is worse than one that leaves the gap, because the gap
is visible and the invention is not.

## 1. Find the raw records

Before writing code, look at real files on the machine.

- Where are sessions kept, in what format (JSON Lines, JSON, SQLite,
  protocol buffers), and does the format carry a version?
- Is there more than one copy of a session, for example a truncated and a full
  transcript? Read events from the full one; list every file you read in the
  header's `files`, with `truncated: true` on the ones known to cut content.
- What is the harness's own session id, and is it unique on its own? Some
  subagent ids are unique only within their parent; then `native_id` is the
  parent's native id, `/`, and the child's id. Where are subagents, forks and
  resumed sessions kept, and how do they point at their parent?
- Do records carry their own ids (UUIDs, row keys)? Then positions are
  `@<id>`, written with `wadachi.ids.escape_key`, and survive the harness
  rewriting its file. Otherwise byte offsets, without leading zeros.
- Which times have a zone? `wadachi.times.from_source` converts a zoned time to
  wadachi's one form (UTC, `Z`, no trailing zeros) and returns `None` for one
  without a zone or that does not exist; such values stay in `raw` and give no
  `t`. Unix times convert with `wadachi.times.from_unix`.
- Do any strings hold lone surrogates (text cut in the middle of an emoji)?
  Replace each with U+FFFD. Do any numbers exceed 2^53 − 1, such as nanosecond
  timestamps? Write them as strings.

Write what you found into `adapters/<harness>.md` as you go, marking each fact
as seen in real files (with the version) or taken from documentation.

## 2. Map records to events

Make a table from every record type you saw to wadachi event types (SPEC.md
section 4.2). Things that are easy to get wrong:

- **One record, several events.** An assistant message with text and three
  tool calls is four events. Each needs its own JSON Pointer in `src`, or their
  ids collide.
- **Prompts versus steers.** A message the human sent while the agent was
  still working is a `steer`, not a `prompt`; it does not start a turn. Find
  out how the harness marks queued or mid-turn messages.
- **Who sent the prompt.** In headless and protocol sessions the prompt usually
  comes from a program: `actor: "caller"`, not `human`.
- **Exit codes.** Find where the real exit code is. Keep the harness's own
  status as `status_as_recorded` next to it: the value of the field the harness
  uses, a string as it is, anything else as its canonical JSON (`true`).
  Document which field. Harnesses have been seen to record a failed shell call
  as a success.
- **Arguments.** Keep `args` as recorded. Arguments the harness stored as a
  JSON-encoded string stay a string.
- **Missing fields stay missing.** No `text` means no `text`, not `""`; no tool
  name means no `tool`. The digest shows the difference (`h?` against `h0`).
- **Paths.** Put every path the tool names in `paths`, in order. A multi-file
  read keeps all of them, not the first. Paths parsed out of a shell command are
  a guess: record them only with `how: {"data.paths": "inferred:<rule>"}`.
- **Compaction.** The summary a harness writes is model text; it goes in
  `compaction.text` and nowhere else.
- **Usage and cost.** Token counts go in `usage` events; harness-specific cost
  units go under `x.<harness>`, as strings if they are not integers.

## 3. Map tools to kinds

Write the harness's tool names into a fixed table: tool name to `read`,
`write`, `edit`, `shell`, `search`, `fetch`, `subagent`, `mcp` or `other`.
MCP tools are `mcp` whatever they do. Unknown tools are `other`. The table is
code, versioned with the converter; a model never picks a kind.

## 4. Build with the shared machinery

The template already does the parts every converter shares; do not rewrite
them:

- reading a live file once, up to its last complete line, and hashing exactly
  those bytes
- `path` in `files` as SPEC.md section 3.3 defines it: absolute, symbolic links
  not resolved, home as `~`
- file keys: `record` sources first, then `hook`, then `aux`
- ids from `wadachi.session_id` and `wadachi.event_id`; an event id depends
  only on the session id and `src`, so moving the raw files changes no ids
- `of` resolved from call ids
- hook events placed after the event they observe and its results (SPEC.md
  section 5)
- `seq` and `turn` assigned after ordering
- every line written with `wadachi.dumps`

## 5. Hooks

Hooks record what the session files cannot know. Write them to append-only
JSON Lines logs outside the agent's reach (not in the repository, not in a
directory the agent can write). A recommended line format, which the template
reads as `wadachi-hook/0.1`:

```json
{"at":"2026-11-23T18:02:40.311Z","event":"post_tool","session":"<native id>","call_id":"toolu_03","exit_code":0,"tree_before":"git-tree:51de2b835bd35a67eb32dbcd3d77d4b96e5aa39d","tree_after":"git-tree:405906c9d5be6ae5393ca65fb0e7c38e0d585ecb","duration_ms":292,"cwd":"/work/x"}
```

- `at` in UTC from the hook's own clock.
- `tree_before` and `tree_after`: the full tree id from `git add -A && git
  write-tree` against a separate `GIT_DIR` and index, so the agent's own
  repository is untouched. Never abbreviate it. It covers what git sees in the
  working tree; ignored files and writes outside the tree are not in it.
- Those tree ids are also how outcomes are found later: a commit whose tree
  equals an observation's `tree_after` came from that call, and can be linked
  as an `observed` `landmark` annotation.
- Take the exit code and duration from the process, not from the harness.
- A hook must never print anything the harness would put in the model's
  context. On failure it exits 0 and logs the gap, so the agent keeps working
  and the missing data stays visible.

## 6. Check against the raw files

Validation proves the output is well-formed, not that it is right. Do both.

```sh
wadachi validate <store>
python -m pytest            # in the wadachi repository: schemas, ids, conformance
```

Then audit: have a second agent, one that did not write the converter, compare
the converter's view of a real, live session with the raw records, event by
event. Give it this list of failures seen in real converters:

- durations or costs of two turns merged when prompts were queued
- a timestamp carried over to events that had none
- failed calls shown as successful
- only the first path of a multi-path call kept
- a mid-turn message counted as a new prompt
- several tool calls in one record collapsed into one event

Each disagreement becomes a fixture: a small, scrubbed copy of the real source
and the expected wadachi output, checked by a test. A real session the
converter's author never saw is the best fixture there is.

## 7. Document the adapter

`adapters/<harness>.md` keeps:

- where the records are, their formats and the versions you checked
- the record-to-event table and the tool-to-kind table
- the rules named in any `how` value
- what the harness does not record, and which hook fills it
- known quirks, each with the harness version it was seen in

When the harness changes its format, the converter's version changes, and
every session is converted again. The raw files stay the truth throughout.
