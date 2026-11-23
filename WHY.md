# Why wadachi

## We already have stories

Coding agents remember through stories: a summary written when the context
fills up, a handoff note, a memory file, a "summary.md" at the end of the
day. Each one is written by a model at the time, and each one decides what
mattered before anyone knows the question it will be asked.

A story only goes one way. Any summary can be made from the full record, later,
for the question at hand. The record can never be made back from a summary.
And the detail a summary drops is usually the one you need: the error behind
the revert, the reason an idea was abandoned, the sentence the human used when
the agent went wrong.

Wadachi keeps the record and lets the stories be made on demand. When a story
is made, it is filed as what it is: a model's account, marked `synthetic`,
next to the record and never in place of it.

## This is not observability

Observability tools, such as OpenTelemetry and Langfuse, are built for people
operating a running system. Wadachi is built for a different reader: the next
agent, and the person directing it, weeks or months later.

| | Observability | Wadachi |
|---|---|---|
| Reader | an operator watching dashboards and alerts | agents and the human who directs them |
| Source | the application instruments itself | the harness's own records, read afterwards, plus hooks |
| Unit | a span, which must have a start and an end time | an event, with a time only if one was recorded |
| Loss | sampling and short retention are normal | nothing is dropped; the raw files remain the truth |
| Provenance | the instrumentation's view | every event names the file and position it was read from |
| The human | a user id in the metadata | steering, interrupting and permitting are events of their own |
| Meaning | left to whoever looks | interpretations are layers, each marked computed, human or model |

Observability answers "is it healthy right now?". Wadachi answers "what
happened, who asked for it, where did it go wrong, and how do we know?". The
two meet at export: wadachi can feed an observability backend, but only with
what was actually recorded.

## Frankenstein

A model was given a session history stitched together from invented parts. It
checked the claims in it against the files on disk, carefully. It never once
questioned the history itself, and in 30 runs it never opened its own session
records to compare.

That is the lesson the whole format is built on: an agent trusts whatever
history it is handed. Whoever can write the history can steer the agent. So the
history has to live outside the agent's reach, every event has to point back
to its raw source, ids are derived rather than chosen, and the header carries
the hash of the raw bytes, so a record that was changed after the fact shows
it.

## Forge

Forged sessions are also a tool, as long as they are labelled. A fixture built
by hand, a session cut at turn N and run again on another model, a fork from a
point where the human had to step in: these are how converters, agents and
skills get tested. In wadachi a constructed session says so in its header, its
converter and its sources. It never mixes into the real record unmarked.

## Unpoison

Records hold things that should not reach the next agent: a frustrated
outburst at the end of a long evening, a prompt injection in a tool's output,
a secret printed to a terminal.

The instinct is to delete them. Wadachi does not edit the record. It marks
them: a `noise` layer keeps an event out of anything given to a model, and a
`secrets` layer names the fields to mask. The record stays complete, so it
stays evidence, and the next agent still gets a clean view.

## Learn

The most useful moments in a record are the ones where a human corrected the
agent: a message sent while it was working, an interruption, a prompt that
starts with "no". Each marks a spot where the agent's route left what the
human meant.

When the same correction appears across many sessions, a skill is missing.
Wadachi makes the corrections findable, citable and countable across every
harness. A proposed skill is a hypothesis until it is tested: fork a session
just before a correction, run it with the skill, and see whether the
correction is still needed. Sessions held back from the proposal are the
proof.

## Dreaming

Notes, memory files and skills go stale. Dreaming is a pass over the record
while nobody is working: each note is checked against what actually happened
and marked `confirmed`, `contradicted`, `stale` or `unverifiable`. A skill
that has not been used in weeks is dropped; a correction that keeps recurring
becomes a candidate for a new one. A note never becomes a fact by being
dreamed about: synthetic stays synthetic, however often it is confirmed.

## Paths that cross

Agents working in parallel, for different reasons, cross each other's paths:
the same file, the same failing test, the same dead end. With every harness's
sessions in one format, those crossings become visible, and one agent can
learn from where another stumbled without having to trust another's story.

Paths that many walk wear deep and become roads. Paths nobody walks grow
over. Nobody has to plan either; the record shows both.

## Further reading

- [SPEC.md](SPEC.md): the format
- [Components of agent memory](https://www.anthropic.com/research/components-of-agent-memory),
  Anthropic: transcripts as the ground truth for checking notes, and offline
  dreaming
