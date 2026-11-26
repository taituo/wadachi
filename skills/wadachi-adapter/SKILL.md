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

Use `src/wadachi/convert/base.py` for the parts every converter shares. The
template is a thin example on top of it. Do not copy these parts into adapters:

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

Supply `HARNESS`, `SOURCE_FORMAT`, `CONVERTER`, `KINDS`, `native_id(records)`,
`map_record(position, record)` and `discover()`. `map_hook` is optional; the
default reads `wadachi-hook/0.1`. Register the module in
`src/wadachi/convert/__init__.py`. The CLI uses it for `wadachi convert`.

When mapping needs session context, `prepare(records)` may return a fresh
adapter for that conversion. The records come from the same complete snapshot
that the base hashes. Its optional `session_header()` returns recorded header
metadata. Keep turn matching and duplicate-view rules in the adapter; ids,
ordering and canonical output still belong to the base.

Several discovered sessions may share a database path. Implement
`selected_sessions(discovered)` so dump keeps selected native ids through
conversion. `DiscoveredSession` may carry recorded cwd and update time. An
optional `select_self(discovered, cwd)` returns descriptors for a reported
fallback; it must not guess values into events.
`caller_present()` may identify the calling harness from its actual process
environment when no session id is exported. Unqualified `--self` selects one
harness, not a fallback session from every registered harness. Ambiguous
callers require `--harness`.

For more than one record file, implement `sessions(paths)` returning
`base.SessionInput` items. It also handles discovery when paths is empty.
Each `base.Source` has a fixed key, path, role and format. Reserve missing
keys; never assign keys by counting present files. Reserve `hook_key` after
all record keys and before aux keys. Mark a truncated duplicate with
`truncated=True, events=False`; read events from its complete copy. Metadata
sources also use `events=False`. Session header metadata can carry `parent`;
each child has its own SessionInput and globally unique native id.

`Source.reader` defaults to `read_jsonl`. Other readers return a `Snapshot`
containing the bytes hashed and records read from those same bytes. For SQLite,
use `read_sqlite(path, rows)`: it reads rows from a consistent physical backup
and hashes that backup's bytes (SPEC.md 3.3). The rows callback supplies a
fixed SQL order and positions `"@" + escape_key(row_key)`. Never hash a JSON
dump of rows or just the live database file while its WAL can change.

For a large database, `sqlite_backup(path)` supplies a consistent temporary
copy without loading its full image into memory. A converter may copy selected
rows and required context into a per-session SQLite snapshot. Document its
selection and insertion order, preserve row values and foreign keys, read
from that snapshot, and hash its physical bytes. The OpenCode adapter is the
working example. Do not replace the source hash with a JSON row digest.

Event specs use `pos`, `type`, `actor`, `data` and optional event fields.
`of_call` links to a record tool call; `of_src` links to a source position.
Unresolvable or forward references stay in `raw`. Give each part of a record
its own JSON Pointer in `pos`.

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
  repository is untouched. Never abbreviate it. Give it the repository's own
  ignore rules, including `.git/info/exclude` (for example through
  `core.excludesFile`), so the snapshot sees what a commit would. It covers
  what git sees in the working tree; ignored files and writes outside the tree
  are not in it.
- Those tree ids are also how outcomes are found later. SPEC.md section 10
  says exactly when a commit is proven to come from a session (the call
  changed the tree, the commit's tree and its parent's tree both match trees
  the session recorded, in the right order). Only then is the link an
  `observed` landmark; anything less is `synthetic`.
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

Each disagreement becomes a constructed fixture and expected wadachi output,
checked by a test. Follow the privacy rule below.

## Fixtures are constructed, never copied

This repository is public. Fixtures copy the structure of real records:
field names, nesting, types and record order. Every value is invented. Never
copy real prompts, code, paths, usernames, hostnames, ids, tokens or timestamps.
Use `/home/user` for home. This applies to inline test data as well as files.

As WHY.md's “Forge” says, mark constructed sessions in their header, converter
and sources. Use a header extension such as
`x.fixture.constructed: true`, a converter name that says `constructed`, and
source formats or names that say `constructed`. Label input-only fixtures in
their test or accompanying text too. Do not change a real record to make a
fixture; build a new one from invented values.

If raw copies are needed during work, `.private/` is the only place inside
this repository where they may sit. It is ignored by git. Never commit them.

## 7. Document the adapter

`adapters/<harness>.md` keeps:

- where the records are, their formats and the versions you checked
- the record-to-event table and the tool-to-kind table
- the rules named in any `how` value
- what the harness does not record, and which hook fills it
- known quirks, each with the harness version it was seen in

When the harness changes its format, the converter's version changes, and
every session is converted again. The raw files stay the truth throughout.
