---
name: agent-sandbox
description: Run coding-agent CLIs (Claude Code, Codex, OpenCode, Antigravity agy, Grok) in a sandbox, container or Kubernetes pod with a fresh home, logins moved in from outside, pinned versions and transcripts kept. Use when asked to sandbox an agent, move or reuse a CLI's login in another home, container or pod, build an image with the agent CLIs, or pin their versions.
---

# Agent sandbox

The tools are in `sandbox/` of the wadachi repository; its README.md is the
reference. This is what to know before using or changing them.

## Rules

- **Logins never go into a repository, an image or a log.** They live in
  `$CLIAUTH_ROOT/auth/<cli>/` (default `~/cliauth`; the scripts refuse a root
  inside a git working tree). Images are built from `git archive` of a commit.
  Never print a login file; check one only with `cmp`, `grep -q` or a hash.
- **A login is the files in `sandbox/auth-files.txt`.** Copy exactly those
  into an empty `HOME`, writable. Nothing else is needed.
- **One live chain per login.** Refresh tokens rotate. After a run, copy
  refreshed files back (the scripts do; a pod writes them to `/handback`). Two
  sandboxes using copies of one login at the same time can log each other out.
- **Versions are pinned in `sandbox/versions.lock`.** `cliauth.sh run`
  refuses other versions; `build-image.sh` fails unless the image has exactly
  them. To change a pin, see the README's last section.

## Doing it

1. Check the logins move: `sandbox/cliauth.sh collect`, then
   `sandbox/cliauth.sh check` (empty home, login files only, no tty, one
   headless prompt per CLI). Every line should say OK.
2. Run an agent: `sandbox/cliauth.sh run <cli> --work DIR -- <cli args>`.
   Read-only material for it: `CLIAUTH_RO="name=/path"` (at `/mnt/name`).
3. In a container: `sandbox/build-image.sh` (`--k3s` to import into k3s),
   then `sandbox/k8s-check.sh IMAGE`. Mount `/auth` (the login files as
   `auth.tgz`), and `/store` and `/handback` to keep transcripts and logins.

## When it fails

- `Not logged in` right after a run elsewhere: the copy was stale (rotation).
  Collect again from a home where the CLI works; `prepare_home` already takes
  the newer of your home's copy and `auth/`'s.
- A headless run hangs: no tty. agy needs `--output-format json`; a process
  stopped in state `T` touched the terminal from a background group (run it
  with `setsid`).
- A CLI writes to its own install directory (agy writes helpers next to
  itself): do not bind that directory read-only; let it live in the run home.
- A pod cannot reach the provider: check cluster DNS and egress before the
  login. `POD_DNS` and `HOSTNET=1` in `k8s-check.sh` tell the two apart.
- A new CLI version: run `check` and the converter tests before changing the
  pin, and record what changed in `adapters/<harness>.md`.
