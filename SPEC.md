# Wadachi format, version 0.1 (draft)

轍 *wadachi*: the ruts a wheel leaves in a road. The route that was actually
taken, not the one that was planned.

Wadachi is a neutral record format for coding agent sessions. Any harness's
session files (Claude Code, Codex, OpenCode, Antigravity, Kiro and others)
convert into it, so tools and agents can read every harness the same way. It
records what happened and where each fact came from. It summarises nothing.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be read as
described in RFC 2119 and RFC 8174 when they appear in capitals.

## 1. Principles

1. **The raw files are the truth.** A wadachi record is a derived view of a
   harness's own session files. It can be thrown away and rebuilt from them at
   any time, and a rebuild with the same converter version gives the same
   bytes.
2. **Never invent.** A value the source did not record is left out. A
   timestamp is never copied from a neighbouring event, a missing time zone is
   never guessed, and a path is never completed.
3. **One event, one source.** Every event points to the one source it was read
   from. Facts about the same thing from different sources, such as the
   harness's record and a hook's log, are separate events linked with `of`.
4. **Read unless said otherwise.** Every value is read from its source, or
   derived by a rule this specification defines. Anything else, such as a
   value an adapter infers, is marked in `how`.
5. **Content is never normalised.** Text, paths, commands and arguments stay as
   recorded, character for character. Only enumerated values (`type`, `actor`,
   `kind`, `mode` and the like) are fixed lowercase words.
6. **Annotations never touch the base.** Interpretation, classification and
   summaries live in separate annotation layers that point at events.
7. **Boring on purpose.** A small required core, a fixed set of optional fields
   with agreed names, and a namespace for everything else.

## 2. Files

A wadachi store is a directory:

```
sessions/<session-id>.jsonl              one session: a header line, then events
annotations/<layer>/<session-id>.jsonl   one annotation layer for one session
index/                                   derived search indexes; not part of the format
```

Every `.jsonl` file:

- MUST be UTF-8 without a byte order mark, with one JSON object per line,
  lines ending in LF, and a final LF.
- MUST serialise every line canonically, as defined by RFC 8785 (JSON
  Canonicalization Scheme): sorted keys, no insignificant whitespace, fixed
  number and string forms. Two conversions can then be compared with `diff`.
- MAY be compressed with zstd, as `.jsonl.zst`.

Numbers in fields this specification defines are integers. A non-integer value
in a defined field is written as a string. Extensions (`x`), `raw` and
annotation values may hold any JSON, and RFC 8785 fixes their form.

## 3. The header

The first line of a session file is its header, and no other line is a header.

### 3.1 Required fields

| Field | Value |
|---|---|
| `type` | `"session"` |
| `format` | `"wadachi/0.1"` |
| `id` | the session id (section 7) |
| `harness` | `{"name": "…", "version": "…"}`; `version` is left out if not recorded |
| `files` | the sources this record was read from (section 3.3) |
| `converter` | `{"name": "…", "version": "…"}` |

### 3.2 Optional fields

| Field | Value |
|---|---|
| `native_id` | the harness's own session id |
| `binary` | path of the harness executable |
| `middleware` | list of `{"name", "version"}`, outermost first: everything between the caller and the harness binary, such as a protocol client or a proxy |
| `mode` | `interactive`, `headless`, `protocol` (a client drives the harness over a protocol such as ACP) or `subagent` |
| `parent` | `{"session", "event", "relation"}`: the session this one came from. `relation` is `subagent`, `fork`, `resume` or `continuation` (a new session after compaction or a restart). `event` is left out if not recorded |
| `invoked_by` | `{"kind", "ref"}`. `kind` is `human`, `agent`, `orchestrator`, `schedule` or `hook`; `ref` is free text, such as a session id |
| `agent` | `{"name", "definition"}`: the agent profile and the path of its definition |
| `model` | the model id as recorded at the start; later changes are `setting` events |
| `cwd`, `repo_commit` | where the session ran |
| `started_at`, `ended_at` | RFC 3339 timestamps, as recorded |
| `end_reason` | as recorded |
| `how` | see section 8 |
| `x` | extensions, see section 9 |

### 3.3 Sources

`files` maps short keys (`f1`, `f2`, …) to the sources the record was read
from:

| Field | Value |
|---|---|
| `path` | where the source was, with the home directory written as `~` |
| `role` | `record` (the harness's own session record), `hook` (a log written by wadachi hooks) or `aux` (anything else read, such as an index file) |
| `format` | the source's format and version as the adapter names it, such as `claude-code-jsonl` or `kiro-v3` |
| `sha256` | hex SHA-256 of the bytes that were converted |
| `truncated` | `true` if the source is known to cut content short (optional) |

A live session's file keeps growing, so its hash will differ later; that is how
a reader knows a conversion is out of date. When a harness keeps both a
truncated and a complete copy of the same session, events MUST be read from the
complete copy.

## 4. Events

Every line after the header is one event.

### 4.1 Fields

Required:

| Field | Value |
|---|---|
| `id` | the event id (section 7) |
| `seq` | position in the session, from 0, without gaps |
| `turn` | turn number (section 4.3) |
| `type` | one of the types in section 4.2 |
| `actor` | who produced the event: `human`, `caller` (a program or another agent driving this session), `agent`, `harness`, `tool` or `hook` |
| `src` | where in which source the event was read (section 6) |
| `data` | the event's content; its fields depend on the type, and every one is optional except `kind` in a `tool_call` |

Optional:

| Field | Value |
|---|---|
| `t` | RFC 3339 timestamp, only if the source recorded one for this event |
| `of` | the id of the event this one answers or observes: a result to its call, a permission decision to its request, a hook's observation to the call it watched |
| `how` | see section 8 |
| `raw` | source fields the converter did not map, kept verbatim so nothing is lost |
| `x` | extensions, see section 9 |

A timestamp without a time zone MUST NOT be given one: `t` is left out and the
original value is kept in `raw`. A timestamp in Unix time converts exactly and
is written in UTC.

### 4.2 Types

| Type | Actors | `data` fields |
|---|---|---|
| `prompt` | human, caller | `text`, `text_truncated` |
| `assistant_text` | agent | `text`, `text_truncated` |
| `reasoning` | agent | `text`, `text_truncated`, `redacted` (the harness kept only an opaque or summarised form) |
| `tool_call` | agent | `tool`, `kind`, `call_id`, `args`, `paths` |
| `tool_result` | tool | `tool`, `kind`, `call_id`, `exit_code`, `status_as_recorded`, `text`, `text_truncated`, `paths` |
| `steer` | human, caller | `text`: a message sent while the agent was working |
| `interrupt` | human, caller, harness | `reason` |
| `permission` | human, caller, harness, hook | `decision` (`asked`, `allowed`, `denied`), `rule` |
| `compaction` | harness | `before_tokens`, `after_tokens`, `text` (the summary the harness wrote) |
| `subagent_start` | agent, harness | `session` (the child's session id), `agent` |
| `subagent_end` | agent, harness | `session`, `reason` |
| `setting` | harness | `model`, `cwd`, `effort`: a change during the session |
| `usage` | harness | `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` |
| `observation` | hook | `tree_before`, `tree_after`, `exit_code`, `duration_ms`, `cwd` |
| `manifest` | hook, harness | `sha256`, `path`, `context_tokens`, `window_tokens`: what the model was given at the start |
| `error` | harness, tool | `code`, `text` |
| `session_end` | harness | `reason` |

Notes:

- `text_truncated: true` means the source itself recorded the text cut short.
- `exit_code` and `status_as_recorded` are both kept. Harnesses have been seen
  to record a shell call as successful when it exited with 1; when the two
  disagree, the disagreement stays visible, and `exit_code` decides.
- `compaction.text` is written by a model, so it is a claim, not a fact.
- `paths` is always a list, and holds every path the call names, in the order
  given, not only the first.
- A `tool_call` and its `tool_result` share a `call_id` when the source records
  one, and the result's `of` points at the call.

### 4.3 Turns

Turns are numbered by this rule, not read from the source: the first `prompt`
event starts turn 1, and every later `prompt` starts the next turn. Events
before the first prompt are in turn 0. `steer` and `interrupt` events do not
start turns. A secondary event placed after its target (section 5) takes its
target's turn. A turn number the harness records itself MAY be kept in `raw`.

### 4.4 Tool kinds

`tool` and `args` keep the tool's own name and arguments as recorded. `kind` is
a fixed category:

| Kind | Meaning |
|---|---|
| `read` | reads files or directories |
| `write` | creates or overwrites a file |
| `edit` | changes part of a file |
| `shell` | runs a command |
| `search` | searches file names or contents |
| `fetch` | reads from the network |
| `subagent` | starts another agent |
| `mcp` | calls a tool on an MCP server |
| `other` | anything else, including planning and to-do tools |

Each adapter maps its harness's tools to kinds with a fixed, versioned table
(see `adapters/`), keyed on the tool's name and, where one tool does several
things, on one named argument (a file tool whose `command` is `create` writes,
and whose `command` is `str_replace` edits). A kind is never chosen by a model.
A call to a tool on an MCP server is `mcp`, whatever the tool does. Any other
tool the table does not list is `other`.

## 5. Order

Events are ordered deterministically:

1. Events from `record` sources, by file key (`f1` before `f2`), then in source
   order.
2. Each event from a `hook` or `aux` source that has `of` is placed after its
   target and after every `record` event whose `of` is that target, so a
   hook's observation of a call follows the call's own result. Several such
   events for one target keep their source order.
3. Events from `hook` or `aux` sources without `of` follow at the end, by file
   key, then in source order.

`seq` is assigned after ordering. A hook event about the start of a session,
such as a `manifest`, uses `of` to point at the session's first record event.

## 6. Sources and positions

`src` names a source and a position in it:

```
src      = file-key ":" position [ "#" pointer ]
file-key = "f" 1*DIGIT                    ; a key in the header's files
position = 1*DIGIT                        ; byte offset of the source record
         / "@" key                        ; a stable key the source gives the record
pointer  = JSON Pointer (RFC 6901) into the source record
```

Examples:

- `f1:88123`: the record starting at byte 88,123 of `f1`
- `f1:@4f1c2a90-77e1-4b9e-9d07-0b8c4e2f1a33`: the line whose own id is that UUID
- `f1:@part/prt_01JD8K2W`: a row of the `part` table in a database source
- `f1:@4f1c2a90-77e1-4b9e-9d07-0b8c4e2f1a33#/message/content/2`: the third
  content block of that line

Adapters SHOULD use stable keys (`@`) whenever the source gives records their
own ids, because byte offsets move if a harness rewrites its file. When one
source record yields several events, each MUST carry a pointer to its own
part.

## 7. Identifiers

Ids are derived, so a rebuild gives the same ids and annotations stay attached.
`H(s)` is the first 16 hex digits of the SHA-256 of the UTF-8 bytes of `s`, and
`\n` is a line feed.

- **Session id:** `"s_" + H(harness.name + "\n" + native_id)`. Without a native
  id: `"s_" + H(harness.name + "\n" + "path:" + path)`, where `path` is the
  first `record` source's path as written in `files`.
- **Event id:** `"e_" + H(session id + "\n" + source path + "\n" + position and
  pointer + "\n" + type)`, where the source path is the `path` of the file the
  event's `src` names, and the position and pointer are the part of `src` after
  the file key and colon.

Event ids MUST be unique within their session. They are not unique across
sessions, so a reference to another session's event always carries that
session's id, as `parent` does.

## 8. Inference

`how` maps a field to the rule that inferred it, for values that are neither
read from the source nor derived by this specification:

```json
"how": {"mode": "inferred:no-human-prompts", "data.paths": "inferred:parsed-from-command"}
```

Keys are field names, dotted for nested fields. Values are `inferred:` and a
kebab-case rule name the adapter documents. A value that is not in `how` was
read from the source. An inferred value MUST NOT be presented as recorded.

## 9. Extensions

Fields a harness records that this specification does not define go under `x`,
namespaced by whoever defined them:

```json
"x": {"kiro": {"credits": "0.42"}, "cockpit": {"pane": "w1:p2"}}
```

Namespace names are lowercase. Readers ignore namespaces they do not know. A
field that several harnesses record in the same way is a candidate for a later
version of this specification.

## 10. Annotations

Interpretations live in annotation layers, one file per layer and session:

```json
{"by":{"kind":"rule","ref":"wadachi-irreversibility/1"},"layer":"irreversibility","on":"e_3d0f51c8a9b70c21","origin":"observed","v":"local"}
```

| Field | Value |
|---|---|
| `on` | an event id, or the session id for the whole session |
| `layer` | the layer name, the same as the directory name |
| `v` | the value; its shape is defined by the layer |
| `by` | `{"kind", "ref"}`: `kind` is `rule`, `model` or `human`; `ref` names the rule and its version, the model id, or the person |
| `origin` | `observed` (a deterministic rule over recorded data), `human` (a person's judgement) or `synthetic` (anything a model produced) |
| `at` | when the annotation was made (optional) |

An annotation made by a model MUST have origin `synthetic`, whatever it says.
Several annotations of one layer may point at the same event; unless a layer
says otherwise, the last line wins.

Layers defined by this specification:

| Layer | `v` |
|---|---|
| `digest` | the turn's digest line (section 11), on the turn's `prompt` event |
| `irreversibility` | `read`, `local`, `local-outside` or `external` |
| `turn_role` | `intent`, `continue`, `refine` or `interrupt` |
| `noise` | `true`: content to leave out of views given to a model, such as venting |
| `secrets` | a list of JSON Pointers into the event whose values must be masked |
| `dreaming` | `confirmed`, `contradicted`, `stale` or `unverifiable`, for a note checked against the record |
| `summary` | a summary, always `synthetic` |

Any other layer name is allowed. Its definition lives with whoever uses it.

## 11. Digests

A digest is a one-line account of a turn, computed from the base by the rule
below. It is the cheapest overview of a session, and since every character is
counted, it cannot tell a story. The rule's reference is `wadachi-digest/1`.

```
t7 h120 r5 e2 s1!1 ^1 4m12s src/a.rs src/b.rs
```

Tokens, separated by single spaces, in this order:

1. `t` and the turn number.
2. The prompt: `h` and the length of its text in Unicode code points when the
   actor is `human`, `p` and the length when it is `caller`; `h?` or `p?` when
   the text was not recorded.
3. Calls per kind, in the order `r` read, `w` write, `e` edit, `s` shell, `q`
   search, `f` fetch, `a` subagent, `m` mcp, `o` other; each as the letter and
   the number of `tool_call` events of that kind, followed by `!` and the
   number that failed when any did. Kinds with no calls are left out. A call
   failed if an event whose `of` is the call is a `tool_result` or
   `observation` with a non-zero `exit_code`, or an `error`.
4. `^` and the number of `steer` events, when there were any.
5. `x` when the turn had an `interrupt` event.
6. `c` when the turn had a `compaction` event.
7. The duration from the prompt's `t` to the latest `t` recorded in the turn,
   when the prompt has one and the difference is at least one second: whole
   seconds rounded down, written with the larger units that are needed: `45s`,
   `4m12s`, `1h0m5s`. When later events have no time, this is a lower bound.
8. The paths of the turn's `write` and `edit` calls, in order of first
   appearance, without repeats, at most five; then `+` and the number left out.
   In paths, `%` is written `%25`, space `%20`, tab `%09` and line feed `%0A`.

The digest annotation is `on` the turn's `prompt` event, with `by.kind` `rule`,
`by.ref` `wadachi-digest/1` and origin `observed`. Turn 0 has no digest.

## 12. Export

OpenTelemetry, Langfuse and similar systems are export targets, not the base. A
span needs a start and an end time, and a wadachi event may have neither. An
exporter MUST NOT invent times: an event without `t` is exported only as an
attribute or span event of an enclosing span that has times, and is otherwise
left out and counted.

## 13. Privacy and security

- A wadachi store holds whatever the raw files hold, secrets included. Treat it
  like the raw files.
- Views given to a model or exported outside the machine MUST apply the
  `secrets` layer.
- Event text MUST NOT be injected into a model's context by a harness, a hook
  or a tool in a way that gives it the harness's authority. Agents read wadachi
  records as data.
- Hook data is recorded for people and tools, not shown to the agent being
  observed.

## 14. Conformance

A converter conforms when every file it writes:

- validates against the schemas in `src/wadachi/schemas/`
- has its header on the first line and only there
- numbers `seq` from 0 without gaps
- has unique event ids, and every `of` names an event in the same session
- uses only file keys that its header defines
- is serialised canonically
- has, for every annotation, a target that exists and a layer name matching its
  directory.

`wadachi validate` checks all of these, and `conformance/` holds files that a
validator must accept or reject.

## 15. Versions

`format` is `wadachi/MAJOR.MINOR`. Within a major version, a new minor version
only adds optional fields, event types, kinds and layers, and a reader MUST
ignore what it does not know when the file's minor version is newer than its
own. Before 1.0, any version may change anything.

## 16. Open questions

- How should two harnesses' sessions be linked when one calls the other, with
  neither knowing the other's session id?
- Does middleware that rewrites prompts need events of its own?
- Should a hash chain over the base lines be part of the format, or left to the
  store that keeps the raw files?
- Snapshots a harness takes by itself, such as Codex's `ghost_snapshot`, have
  no event type: `observation` is reserved for hooks. Should there be one?
