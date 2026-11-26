# Capturing transcripts from sandboxes and containers

An agent that runs in a container or a sandbox writes its transcript inside
it. When the container goes away, so does the record. Three things keep it:

1. **Give the harness a home you keep.** Every converter finds sessions
   through the harness's own home variable, so the transcript directory can
   live anywhere:

   | Harness | Variable | Default |
   |---|---|---|
   | Claude Code | `CLAUDE_CONFIG_DIR` | `~/.claude` |
   | Codex | `CODEX_HOME` | `~/.codex` |
   | OpenCode | `XDG_DATA_HOME` | `~/.local/share` |
   | Grok CLI | `GROK_HOME` | `~/.grok` |
   | Antigravity CLI | `WADACHI_ANTIGRAVITY_HOME` (wadachi's own; the CLI documents none) | `~/.gemini/antigravity-cli` |

   Session and event ids come from the harness's own session ids, not from
   paths, so a store built from a mounted copy has the same ids as one built
   on the machine that ran the session.

2. **Dump when the run ends.** Run `wadachi dump --keep-raw` with the same
   variables pointing at the run's home, into a store outside the container
   (`WADACHI_STORE`). `--keep-raw` copies every source and every file listed
   as `unread` by its SHA-256, so the raw files outlive the container too.

3. **Pin versions.** Install the harness at a fixed version and wadachi at a
   fixed commit. Each converter lists the harness versions it was checked
   against in `converter.measured`; `dump` prints `unmeasured=N` for sessions
   from other versions, which still convert (nothing is left out) but should
   be checked before their output is relied on.

## Example: bubblewrap with separate logins

Logins stay outside the sandbox and are copied into a throwaway home for one
run; tokens a harness refreshes are copied back afterwards and removed from
the run home.

```sh
run=$(mktemp -d)                      # the run's home
cp -p ~/logins/grok/.grok/auth.json "$run/.grok/auth.json"   # after mkdir -p
bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp \
      --bind "$run" "$HOME" --bind "$PWD" "$PWD" --chdir "$PWD" \
      --ro-bind "$HOME/.grok/downloads" "$HOME/.grok/downloads" \
      --ro-bind "$HOME/.grok/bin" "$HOME/.grok/bin" \
      --die-with-parent --unshare-pid \
      grok -p "..."
cmp -s "$run/.grok/auth.json" ~/logins/grok/.grok/auth.json || cp -p "$run/.grok/auth.json" ~/logins/grok/.grok/
rm -f "$run/.grok/auth.json"
GROK_HOME="$run/.grok" WADACHI_STORE=~/wadachi-store wadachi dump --keep-raw
```

Bind the harness's install directories read-only at their usual paths (an
npm prefix, a version manager's node, the harness's own download directory),
since the fresh home hides everything else under `$HOME`.

## Example: a container

```sh
docker run --rm -v "$PWD:/work" -v "$HOME/agent-homes/run1:/home/agent" \
  -e HOME=/home/agent pinned-agent-image:1.2.3 claude -p "..."
CLAUDE_CONFIG_DIR="$HOME/agent-homes/run1/.claude" wadachi dump --keep-raw
```

The mounted home is the record. Do not put the store or the homes inside a
git working tree; `dump` refuses that unless told otherwise.
