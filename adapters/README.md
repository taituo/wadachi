# Adapters

One adapter per harness: a converter from the harness's own session files to
wadachi, and hooks for what those files do not record. How to write one is in
[`skills/wadachi-adapter`](../skills/wadachi-adapter/SKILL.md).

Every fact in these notes says where it came from, because harnesses change
their formats without notice:

- **measured**: seen in real session files, with the harness version
- **documented**: from the harness's own documentation
- **reported**: from third-party write-ups or reverse engineering
- **unverified**: an expectation to check against real files before relying on it

| Harness | Records | Hooks | Status of these notes |
|---|---|---|---|
| [Kiro CLI](kiro-cli.md) | session files, three formats | per agent | measured on one machine; a reader exists (ksess) |
| [Claude Code](claude-code.md) | JSON Lines transcript, subagents in separate files | 30+ events, global or per project | measured on one machine (2.1.296); converter exists |
| [Codex CLI](codex.md) | JSON Lines rollouts | none for tool calls found yet; a `notify` setting to check | reported |
| [OpenCode](opencode.md) | SQLite, older versions JSON files | server plugins (v2 docs) | documented and reported |
| [Antigravity CLI](antigravity.md) | JSON Lines transcripts, truncated and full | SDK hooks; CLI hooks to check | measured on one machine (1.5.18); converter exists |
| [Grok CLI](grok.md) | JSON Lines chat history, timed telemetry | documented in its user guide | measured on one machine (1.0.92); converter exists |

None of these converters is finished. The tool-to-kind tables marked
unverified are a starting point: confirm every row against a real transcript
of the version you convert.
