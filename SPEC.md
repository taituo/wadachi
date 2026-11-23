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
   recorded, character for character, with one exception (section 2: invalid
   Unicode). Only enumerated values (`type`, `actor`, `kind`, `mode` and the
   like) are fixed lowercase words, and times have one form (section 4.5).
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

Session and annotation files are named after the session's id, with the
extension `.jsonl`, or `.jsonl.zst` when compressed with zstd. Other files in
`sessions/` and `annotations/` are not part of the store.

Every file:

- MUST be UTF-8 without a byte order mark, with one JSON object per line,
  lines ending in LF, and a final LF.
- MUST serialise every line canonically, as defined by RFC 8785 (JSON
  Canonicalization Scheme): sorted keys, no insignificant whitespace, fixed
  number and string forms. Two conversions can then be compared with `diff`.

Two rules keep canonical form exact in every language:

- **Strings are valid Unicode.** RFC 8785 rejects lone surrogates. A converter
  that finds one in a source (for example text cut in the middle of an emoji)
  replaces it with U+FFFD; the raw file keeps the original.
- **Numbers fit a double exactly.** JSON numbers are read as IEEE 754 doubles,
  so any number whose magnitude exceeds 2^53 − 1 MUST be written as a string
  of its decimal digits, anywhere in the file, `raw` and `x` included. Numeric
  fields this specification defines hold integers; a source value that is not
  an integer goes to `raw`.

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
| `native_id` | the harness's own session id (section 7) |
| `binary` | path of the harness executable |
| `middleware` | list of `{"name", "version"}`, outermost first: everything between the caller and the harness binary, such as a protocol client or a proxy |
| `mode` | `interactive`, `headless`, `protocol` (a client drives the harness over a protocol such as ACP) or `subagent` |
| `parent` | `{"session", "event", "relation"}`: the session this one came from. `relation` is `subagent`, `fork`, `resume` or `continuation` (a new session after compaction or a restart). `event` is left out if not recorded |
| `invoked_by` | `{"kind", "ref"}`. `kind` is `human`, `agent`, `orchestrator`, `schedule` or `hook`; `ref` is free text, such as a session id |
| `agent` | `{"name", "definition"}`: the agent profile and the path of its definition |
| `model` | the model id as recorded at the start; later changes are `setting` events |
| `cwd`, `repo_commit` | where the session ran |
| `started_at`, `ended_at` | times, in the form of section 4.5 |
| `end_reason` | as recorded |
| `how` | see section 8 |
| `raw` | session-level source fields the converter did not map, such as a start time without a zone |
| `x` | extensions, see section 9 |

### 3.3 Sources

`files` maps keys to the sources the record was read from:

| Field | Value |
|---|---|
| `path` | the source's absolute path as the adapter found it, without resolving symbolic links, with `/` as the separator and the user's home directory written as `~` |
| `role` | `record` (the harness's own session record), `hook` (a log written by wadachi hooks) or `aux` (anything else read, such as an index file) |
| `format` | the source's format and version as the adapter names it, such as `claude-code-jsonl` or `kiro-v3` |
| `sha256` | hex SHA-256 of the bytes that were converted |
| `truncated` | `true` if the source is known to cut content short (optional) |

Keys are `f1`, `f2`, … without gaps: `record` sources first, then `hook`, then
`aux`, in an order the adapter documents and keeps for a given converter
version. Keys are always compared by their number, so `f2` comes before `f10`.

A live session's file keeps growing. A converter reads up to the last complete
line (one ending in LF); `sha256` covers exactly those bytes, so it shows later
whether the conversion is out of date. When a harness keeps both a truncated
and a complete copy of the same session, events MUST be read from the complete
copy.

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
| `src` | where in which source the event was read (section 6); unique within the session |
| `data` | the event's content; its fields depend on the type, and every one is optional except `kind` in a `tool_call` |

Optional:

| Field | Value |
|---|---|
| `t` | the time the source recorded for this event, in the form of section 4.5 |
| `of` | the id of an earlier event this one answers or observes: a result to its call, a permission decision to its request, a hook's observation to the call it watched |
| `how` | see section 8 |
| `raw` | source fields the converter did not map, kept as recorded |
| `x` | extensions, see section 9 |

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
- `args` holds the arguments as recorded. Arguments the harness recorded as a
  JSON-encoded string stay a string.
- `paths` is always a list, and holds every path the call names, in the order
  given, not only the first.
- `exit_code` is the exit status of a process. `status_as_recorded` is the
  value of the field the harness uses for success or failure, as a string: a
  string as it is, any other value as its canonical JSON (`true`, `0`). The
  adapter documents which field it reads. Harnesses have been seen to record
  a shell call as successful when it exited with 1; both values are kept, and
  `exit_code` decides.
- `compaction.text` is written by a model, so it is a claim, not a fact.
- A `tool_call` and its `tool_result` share a `call_id` when the source records
  one, and the result's `of` points at the call.
- In `observation`, `tree_before` and `tree_after` are full git tree ids,
  written `git-tree:` and 40 or 64 hex digits.

### 4.3 Turns

Turns are numbered by this rule, not read from the source: an event's turn is
the number of `prompt` events at or before it, in `seq` order. The first
prompt starts turn 1, and events before it are in turn 0. `steer` and
`interrupt` events do not start turns.

Because hook events are placed after a call's results (section 5), a hook's
observation can land in a later turn than the call it observes. Its turn is
still the turn it lands in; `of` keeps the link. A turn number the harness
records itself MAY be kept in `raw`.

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

### 4.5 Times

`t`, `started_at`, `ended_at` and an annotation's `at` are written in one form:

```
YYYY-MM-DDTHH:MM:SS[.fraction]Z
```

in UTC, with an uppercase `T` and `Z`, and a fraction of one to nine digits
without trailing zeros, left out when it is zero: `2026-11-23T18:02:11.204Z`,
`2026-11-23T18:02:11Z`.

- A source time with a zone offset, a lowercase `t` or `z`, or a space between
  date and time is converted exactly to this form; the raw file keeps the
  original. Unix times convert exactly.
- A source time without a zone MUST NOT be given one. It is not written as `t`;
  the original value is kept in `raw`.
- A leap second (`:60`) is kept as written. In arithmetic, such as a digest's
  duration, it counts as the second after `:59`.
- A time that does not exist, such as February 31st, is not a time; it is kept
  in `raw`.

## 5. Order

Events are ordered deterministically:

1. Events from `record` sources: by file key, then in source order.
2. Events from `hook` and `aux` sources are then placed one at a time, by file
   key, then in source order. One with `of` goes directly after the last
   already-placed event that is its target or has the same `of`, so a hook's
   observation of a call follows the call's own results. Its target is a
   `record` event, or a `hook` or `aux` event placed before it.
3. Events from `hook` and `aux` sources without `of`, or whose target was not
   placed, follow at the end, by file key, then in source order.

`seq` is assigned after ordering. A hook event about the start of a session,
such as a `manifest`, uses `of` to point at the session's first record event.

## 6. Sources and positions

`src` names a source and a position in it:

```
src      = file-key ":" position [ "#" pointer ]
file-key = "f" %x31-39 *DIGIT        ; a key in the header's files
position = "0" / %x31-39 *DIGIT      ; byte offset of the source record, without leading zeros
         / "@" key                   ; a stable key the source gives the record
key      = 1*key-char                ; see below
pointer  = JSON Pointer (RFC 6901), in its string form, starting with "/"
```

In a key, `%`, `#` and every whitespace or control character are written as
`%` and two uppercase hex digits per UTF-8 byte; all other characters are
written as they are. The pointer is the plain RFC 6901 string, not the
percent-encoded URI fragment form.

Examples:

- `f1:88123`: the record starting at byte 88,123 of `f1`
- `f1:@4f1c2a90-77e1-4b9e-9d07-0b8c4e2f1a33`: the line whose own id is that UUID
- `f1:@part/prt_01JD8K2W`: a row of the `part` table in a database source
- `f1:@4f1c2a90-77e1-4b9e-9d07-0b8c4e2f1a33#/message/content/2`: the third
  content block of that line

Adapters SHOULD use stable keys (`@`) whenever the source gives records their
own ids, because byte offsets move if a harness rewrites its file. `src` MUST
be unique within a session, so when one source record yields several events,
each carries a pointer to its own part.

## 7. Identifiers

Ids are derived, so a rebuild gives the same ids and annotations stay attached.
`H(s)` is the first 16 hex digits of the SHA-256 of the UTF-8 bytes of `s`, and
`\n` is a line feed.

- **Session id:** `"s_" + H(harness.name + "\n" + native_id)`. Without a native
  id: `"s_" + H(harness.name + "\n" + "path:" + path)`, where `path` is the
  `path` of `f1` as written in `files`.
- **Event id:** `"e_" + H(session id + "\n" + src)`.

The native id MUST identify the session among all of the harness's sessions on
the machine. When a harness's own id is unique only within a parent session,
as some subagent ids are, the adapter writes `native_id` as the parent's native
id, `/`, and the child's id.

An event id does not depend on where the source file lives, so moving or
archiving the raw files changes no ids. Event ids are unique within their
session, because `src` is. They are not unique across sessions, so a reference
to another session's event always carries that session's id, as `parent` does.

## 8. Inference

`how` maps a field to the rule that inferred it, for values that are neither
read from the source nor derived by this specification:

```json
"how": {"mode": "inferred:no-human-prompts", "data.paths": "inferred:parsed-from-command"}
```

Keys are field names, dotted for nested fields, matching
`^[a-z_]+(\.[a-z0-9_-]+)*$`. Values are `inferred:` and a kebab-case rule name
the adapter documents. A value that is not in `how` was read from the source.
An inferred value MUST NOT be presented as recorded.

## 9. Extensions

Fields a harness records that this specification does not define go under `x`,
namespaced by whoever defined them:

```json
"x": {"kiro": {"credits": "0.42"}, "cockpit": {"pane": "w1:p2"}}
```

Namespace names match `^[a-z][a-z0-9_-]*$`. Readers ignore namespaces they do
not know. A field that several harnesses record in the same way is a candidate
for a later version of this specification.

## 10. Annotations

Interpretations live in annotation layers, one file per layer and session:

```json
{"by":{"kind":"rule","ref":"wadachi-irreversibility/1"},"layer":"irreversibility","on":"e_3d0f51c8a9b70c21","origin":"observed","v":"local"}
```

| Field | Value |
|---|---|
| `on` | an event id, or the session id for the whole session |
| `layer` | the layer name, matching `^[a-z][a-z0-9_]*$`, the same as the directory name |
| `v` | the value; its shape is defined by the layer |
| `by` | `{"kind", "ref"}`: `kind` is `rule`, `model` or `human`; `ref` names the rule and its version, the model id, or the person |
| `origin` | follows from `by.kind`: `observed` for a deterministic rule over recorded data, `human` for a person's judgement, `synthetic` for anything a model produced |
| `at` | when the annotation was made, in the form of section 4.5 (optional) |

`origin` repeats what `by.kind` implies so that a reader cannot miss it. A
model's annotation is `synthetic`, whatever it says. Several annotations of
one layer may point at the same event; unless a layer says otherwise, the last
line wins.

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
| `landmark` | `{"kind", "ref", "state"}`: something outside the session that this event or session led to or belongs to. `kind` is `commit`, `branch`, `pr`, `ci`, `ticket`, `milestone`, `release` or `revert`; `ref` is its identifier as the system names it (a commit id, a pull request number, a run id); `state`, optional, is its state as recorded there, such as `merged` or `failed` |

Any other layer name that matches the pattern is allowed. Its definition
lives with whoever uses it.

Landmarks are how a session's outcome is told without anyone's opinion: the
commit it made, whether the commit passed CI, whether its pull request was
merged or later reverted. They are usually discovered afterwards, when the
outcome is known, and added like any other layer:

- A link a rule can prove is `observed`: a hook observation's `tree_after` is
  exactly the tree of a later commit, or a revert names a commit already linked
  to the session.
- A link a person makes by hand is `human`.
- A model's guess at a cause, such as which session most likely introduced a
  bug, is `synthetic`. It points at the events it rests on, and stays a
  hypothesis until a rule or a person confirms it.

## 11. Digests

A digest is a one-line account of a turn, computed from the base by the rule
below. It is the cheapest overview of a session, and since every character is
counted, it cannot tell a story. The rule's reference is `wadachi-digest/1`.

```
t7 h120 r5 e2 s1!1 ^1 4m12s @src/a.rs @src/b.rs
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
   `observation` with a non-zero `exit_code`, or an `error`. A call with no
   recorded outcome is not counted as failed.
4. `^` and the number of `steer` events, when there were any.
5. `x` when the turn had an `interrupt` event.
6. `c` when the turn had a `compaction` event.
7. The duration from the prompt's `t` to the latest `t` recorded in the turn,
   when the prompt has one and the difference is at least one second: computed
   exactly from the times as written, rounded down to whole seconds, and
   written with the larger units that are needed: `45s`, `4m12s`, `1h0m5s`.
   When later events have no time, this is a lower bound.
8. The paths named by the turn's `write` and `edit` calls, whether or not the
   calls succeeded: in order of first appearance, without repeats or empty
   paths, at most five, each written as `@` and the path; then `+` and the
   number left out. In a path, `%` and every whitespace or control character
   are written as `%` and two uppercase hex digits per UTF-8 byte.

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

A converter conforms when every file it writes passes every check below.
`wadachi validate` reports each failure with its code, and `conformance/` holds
files a validator must accept, and files it must reject with exactly the codes
its manifest lists.

| Code | Check |
|---|---|
| `path` | the path given to the validator exists |
| `store` | a directory given as a store has `sessions/` or `annotations/` |
| `compression` | a `.jsonl.zst` file can be read |
| `encoding` | UTF-8 without a byte order mark, valid Unicode, LF line ends, a final LF, no blank lines (section 2) |
| `json` | every line is a JSON object |
| `canonical` | every line is serialised as RFC 8785 defines, with no number beyond 2^53 − 1 (section 2) |
| `version` | the header's `format` is a version the validator knows (section 15) |
| `schema` | every line matches the JSON Schemas in `src/wadachi/schemas/` |
| `header` | the header is on the first line and only there |
| `session-id` | the header's id is the one section 7 derives, and a store's file is named after it |
| `seq` | `seq` counts from 0 without gaps |
| `turn` | `turn` follows section 4.3 |
| `time` | every time exists (section 4.5) |
| `unknown-source` | every `src` names a file key the header defines |
| `duplicate-src` | no two events share a `src` (section 6) |
| `id` | every event id is the one section 7 derives |
| `duplicate-id` | no two events share an id |
| `dangling-of` | every `of` names an event in the session |
| `of-order` | every `of` names an earlier event |
| `order` | events from `hook` and `aux` sources are where section 5 puts them |
| `annotation-orphan` | every annotation file belongs to a session in the store |
| `annotation-layer` | every annotation's layer is its directory's name |
| `annotation-target` | every annotation's `on` exists in its session |
| `digest` | every digest annotation is on a turn's prompt and holds the line section 11 computes |

## 15. Versions

`format` is `wadachi/MAJOR.MINOR`. Before 1.0, any version may change anything,
and a reader handles only the versions it knows: a validator reports a file of
any other version with the code `version` and checks nothing else in it. From
1.0 on, a new minor version will only add optional fields, event types, kinds
and layers.

## 16. Open questions

- How should two harnesses' sessions be linked when one calls the other, with
  neither knowing the other's session id?
- Does middleware that rewrites prompts need events of its own?
- Should a hash chain over the base lines be part of the format, or left to the
  store that keeps the raw files?
- Snapshots a harness takes by itself, such as Codex's `ghost_snapshot`, have
  no event type: `observation` is reserved for hooks. Should there be one?
