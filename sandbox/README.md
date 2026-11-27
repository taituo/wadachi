# Sandboxed agent runs with portable logins

Run Claude Code, Codex, OpenCode, Antigravity (`agy`) and Grok CLI in a fresh
home, in bubblewrap or in a container, with logins kept outside the sandbox
and outside any repository, versions pinned, and every transcript dumped into
a wadachi store. Plain bash; no logins are ever in this directory or the image.

| File | What it is |
|---|---|
| `auth-files.txt` | the files that carry each CLI's login |
| `versions.lock` | every CLI, node and the image base, pinned (URLs and hashes for agy and grok) |
| `cliauth.sh` | bubblewrap runs with a throwaway home; `check` proves a login moves |
| `Containerfile`, `build-image.sh`, `entrypoint.sh` | one image with all CLIs at the pinned versions |
| `k8s-check.sh` | the same check in Kubernetes pods |

## Moving a login

A CLI's login is a few files under `HOME`. Copied into an empty home anywhere
(another path, a bwrap sandbox, a container, a pod), they are enough on their
own: measured with the pinned versions, no tty, one headless prompt each.

| CLI | Login files (relative to `HOME`) | Headless turn |
|---|---|---|
| claude | `.claude/.credentials.json`, `.claude.json` | `claude -p '…'` |
| codex | `.codex/auth.json` | `codex exec --skip-git-repo-check '…'` |
| opencode | `.local/share/opencode/auth.json` | `opencode run '…'` |
| agy | `.gemini/antigravity-cli/antigravity-oauth-token` | `agy -p '…' --output-format json` |
| grok | `.grok/auth.json` | `grok -p '…'` |

- **Keep them writable.** CLIs refresh tokens in place. Mount a Secret
  read-only and copy it into a writable `HOME` (the image's entrypoint does).
- **Tokens rotate.** A refresh can invalidate the copy you started from. Keep
  one live chain: copy refreshed files back (`cliauth.sh` does after each run,
  to `auth/` and to your own home if it did not change meanwhile; in a pod,
  `/handback` holds them). A refresh that lost its refresh token is never
  copied back. A long-lived pod is better off with its own login or an API key.
- **agy without a tty:** text mode hangs when stdin is not a terminal; use
  `--output-format json`. In a background process group it stops (SIGTTOU)
  when it touches the terminal, so timed runs use `setsid`.

## bubblewrap

    sandbox/cliauth.sh collect            # once: copy your logins to ~/cliauth/auth/
    sandbox/cliauth.sh versions           # installed against versions.lock
    sandbox/cliauth.sh check              # each CLI: empty home + login files, no tty, one prompt
    sandbox/cliauth.sh run claude --work ~/projects/x -- --dangerously-skip-permissions
    sandbox/cliauth.sh shell agy          # look around in the same sandbox

`/` is read-only, `HOME` is the run's home, the work directory is writable and
the CLIs' install directories (`~/.npm-global`, `~/.nvm`, `~/.local/bin`,
`~/.bun`, grok's `bin` and `downloads`, plus `CLIAUTH_BIND`) are bound
read-only. Network is shared. `run` refuses a CLI whose version is not the
pinned one (`CLIAUTH_ALLOW_UNPINNED=1` overrides). After a run, `wadachi dump
--keep-raw` puts the transcripts into `~/cliauth/store`. Layout under
`CLIAUTH_ROOT` (default `~/cliauth`, refused inside a git working tree):
`auth/` logins (700/600), `runs/<UTC time>-<cli>/` run homes, `store/`.

## Container and Kubernetes

    sandbox/build-image.sh            # prints localhost/wadachi-sandbox:<commit>
    sandbox/build-image.sh --k3s      # and imports it into k3s
    sandbox/k8s-check.sh localhost/wadachi-sandbox:<commit>

The image is built from `git archive` of one commit, so only tracked files go
in. It runs as user `agent` (uid 1000) with `HOME=/home/agent` and
`DISABLE_AUTOUPDATER=1`; `build-image.sh` fails unless every CLI in it reports
its pinned version. The entrypoint unpacks `/auth/auth.tgz` (or a tree) into
`HOME`, runs the command, then writes the transcripts to `/store` and the
login files to `/handback/auth.tgz` when those are mounted:

    tar -C ~/cliauth/auth/grok -czf auth.tgz .grok/auth.json
    podman run --rm -v "$PWD/auth.tgz:/auth/auth.tgz:ro" -v "$HOME/store:/store" \
      -v "$PWD/back:/handback" localhost/wadachi-sandbox:<commit> grok -p 'hello'

`k8s-check.sh` does the same with a Secret per CLI and copies `/handback` back
to `auth/`. `POD_DNS=1.1.1.1` and `HOSTNET=1` work around a cluster whose DNS
or pod egress is broken.

## Updating a pin

Install the new version, run `cliauth.sh check` and the converter tests
(`adapters/<harness>.md` lists the measured versions), then change
`versions.lock`. For agy, the release manifest is
`https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_amd64.json`
(its `url` and `sha512`); for grok, `https://x.ai/cli/grok-<version>-linux-x86_64`
and its SHA-256.
