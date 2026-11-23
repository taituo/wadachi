# Examples

`store/` is a small wadachi store. The sessions are written by hand to show
the format; their ids, order, turns and digests are derived exactly as SPEC.md
requires, and the tests check that they stay so.

| Session | What it shows |
|---|---|
| `s_e6468e8dce041668` | Claude Code, interactive. Several tool calls in one record (JSON Pointers in `src`), a hook log as a second source, a steer, a permission asked and granted, an interrupt, usage, a subagent, and a secret marked for masking |
| `s_43f053b752338e0a` | the subagent that session started: `mode: "subagent"`, `parent`, a prompt from a `caller`, and a native id formed from the parent's |
| `s_1ff57620c40ebc02` | Kiro CLI, driven over ACP by an orchestrator: `middleware`, an inferred value in `how`, a shell call recorded as successful that exited with 1, a timestamp without a zone kept in `raw` instead of `t` |

Annotation layers: `digest` (computed), `irreversibility` and `secrets`
(computed by named rules), `landmark` (a ticket linked by hand), `summary`
(written by a model, so `synthetic`).

The source paths and hashes in the headers are illustrative; the raw files are
not included.
