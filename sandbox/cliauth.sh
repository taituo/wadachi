#!/usr/bin/env bash
# cliauth: run a coding-agent CLI in bubblewrap with a fresh, throwaway home.
# Logins live only in $CLIAUTH_ROOT/auth/<cli>/ (default ~/cliauth, never in a
# repository); each run copies them in and syncs refreshed tokens back. After a
# run, the transcripts in the run home go into a wadachi store.
#
#   cliauth.sh collect [cli...]          copy logins from your home into auth/
#   cliauth.sh versions                  installed versions against versions.lock
#   cliauth.sh run <cli> [--work DIR] [-- cli args...]
#   cliauth.sh shell <cli> [--work DIR]  a shell in the same sandbox
#   cliauth.sh check [cli...]            empty home + login files only, no tty, one headless prompt
#
#   CLIAUTH_RO="name=/path ..."   extra paths read-only at /mnt/<name>
#   CLIAUTH_BIND="/path ..."      extra install directories, read-only at the same path
#   CLIAUTH_ALLOW_UNPINNED=1      run a CLI whose version differs from versions.lock
# Needs: bash, bwrap, coreutils; wadachi for the transcript dump (optional).
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

ROOT="${CLIAUTH_ROOT:-$HOME/cliauth}"
AUTH="$ROOT/auth"
RUNS="$ROOT/runs"
STORE="${WADACHI_STORE:-$ROOT/store}"
WADACHI="${WADACHI_BIN:-wadachi}"

# Settings copied in read-only, never synced back. Missing ones are skipped.
settings_files() {
  case "$1" in
    claude)   echo ".claude/settings.json" ;;
    codex)    echo ".codex/config.toml" ;;
    opencode) echo ".config/opencode/opencode.jsonc" ;;
    agy)      echo ".gemini/antigravity-cli/settings.json .gemini/antigravity-cli/cache/onboarding.json" ;;
    grok)     echo ".grok/config.toml" ;;
  esac
}

# Directories with the CLIs' binaries and runtimes, bound read-only at the same path,
# since the fresh home hides everything else under $HOME. Not ~/.local/share: data.
install_dirs() {
  local d
  for d in "$HOME/.npm-global" "$HOME/.nvm" "$HOME/.local/bin" "$HOME/.bun" \
           "$HOME/.grok/bin" "$HOME/.grok/downloads" ${CLIAUTH_BIND:-}; do
    [ -d "$d" ] && echo "$d"
  done
}

cmd_collect() {
  local clis=("$@"); [ ${#clis[@]} -eq 0 ] && clis=($CLIS)
  umask 077; mkdir -p "$AUTH"; chmod 700 "$ROOT" "$AUTH"
  for cli in "${clis[@]}"; do
    for f in $(auth_files "$cli"); do
      if [ -f "$HOME/$f" ]; then
        mkdir -p "$AUTH/$cli/$(dirname "$f")"; cp -p "$HOME/$f" "$AUTH/$cli/$f"; chmod 600 "$AUTH/$cli/$f"
        echo "$cli: $f"
      else
        echo "$cli: $f missing in your home, skipped" >&2
      fi
    done
  done
}

cmd_versions() {
  for cli in $CLIS; do
    command -v "$cli" >/dev/null || { echo "$cli: not installed"; continue; }
    local have want; have=$(version_of "$cli"); want=$(pinned "$cli")
    echo "$cli: installed=$have pinned=${want:-none}$([ -n "$want" ] && [ "$want" != "$have" ] && echo '  MISMATCH')"
  done
}

check_pin() {
  local cli=$1 want have; want=$(pinned "$cli"); have=$(version_of "$cli")
  if [ -n "$want" ] && [ "$want" != "$have" ]; then
    echo "cliauth: $cli is $have, pinned $want in versions.lock; refusing (CLIAUTH_ALLOW_UNPINNED=1 runs anyway)" >&2
    [ "${CLIAUTH_ALLOW_UNPINNED:-0}" = 1 ] || exit 3
  fi
}

sandbox() {  # sandbox <runhome> <workdir> <command...>
  local home=$1 work=$2; shift 2
  local args=(--ro-bind / / --dev /dev --proc /proc --tmpfs /tmp
              --bind "$home" "$HOME" --bind "$work" "$work" --chdir "$work"
              --setenv HOME "$HOME" --die-with-parent --unshare-pid --unshare-ipc --unshare-uts)
  while read -r d; do [ -n "$d" ] && args+=(--ro-bind "$d" "$d"); done < <(install_dirs)
  if [ -n "${CLIAUTH_RO:-}" ]; then
    args+=(--tmpfs /mnt)
    for pair in $CLIAUTH_RO; do args+=(--ro-bind "${pair#*=}" "/mnt/${pair%%=*}"); done
  fi
  # A timed run has no controlling tty (setsid), like a pod; some CLIs stop
  # (SIGTTOU) when they touch a terminal from a background process group.
  ${CLIAUTH_TIMEOUT:+setsid -w timeout -k 10 "$CLIAUTH_TIMEOUT"} bwrap "${args[@]}" "$@"
}

prepare_home() {  # prepare_home <cli> <runhome> [settings: 1|0]
  local cli=$1 home=$2 f
  mkdir -p "$home"; chmod 700 "$home"
  for f in $(auth_files "$cli"); do
    # Logins rotate refresh tokens: start from the newest copy, yours or auth/'s.
    if [ -f "$HOME/$f" ] && { [ ! -f "$AUTH/$cli/$f" ] || [ "$HOME/$f" -nt "$AUTH/$cli/$f" ]; }; then
      mkdir -p "$AUTH/$cli/$(dirname "$f")"; cp -p "$HOME/$f" "$AUTH/$cli/$f"; chmod 600 "$AUTH/$cli/$f"
    fi
    [ -f "$AUTH/$cli/$f" ] || { echo "no $AUTH/$cli/$f: run '$0 collect $cli' first" >&2; exit 1; }
    mkdir -p "$home/$(dirname "$f")"; cp -p "$AUTH/$cli/$f" "$home/$f"
    cp -p "$AUTH/$cli/$f" "$home/.cliauth-start-$(echo "$f" | tr / _)"
  done
  [ "${3:-1}" = 1 ] || return 0
  for f in $(settings_files "$cli"); do
    [ -f "$HOME/$f" ] && { mkdir -p "$home/$(dirname "$f")"; cp -p "$HOME/$f" "$home/$f"; }
  done
}

sync_back() {  # refreshed tokens back to auth/, and to your home if it did not change meanwhile
  local cli=$1 home=$2 f start
  for f in $(auth_files "$cli"); do
    start="$home/.cliauth-start-$(echo "$f" | tr / _)"
    # One rotation chain: if your own copy is still what the run started from,
    # update it too, so the CLI outside the sandbox stays logged in.
    if [ -f "$HOME/$f" ] && [ -f "$start" ] && cmp -s "$HOME/$f" "$start"; then
      sync_one "$cli" "$home/$f" "$HOME/$f"
    fi
    sync_one "$cli" "$home/$f" "$AUTH/$cli/$f"
    rm -f "$home/$f" "$start"
  done
}

dump_run() {  # every harness's transcripts in the run home, into the store, raw kept
  local home=$1
  command -v "$WADACHI" >/dev/null || { echo "cliauth: no wadachi; transcripts stay in the run home" >&2; return 0; }
  CLAUDE_CONFIG_DIR="$home/.claude" CODEX_HOME="$home/.codex" XDG_DATA_HOME="$home/.local/share" \
  GROK_HOME="$home/.grok" WADACHI_ANTIGRAVITY_HOME="$home/.gemini/antigravity-cli" \
  WADACHI_STORE="$STORE" "$WADACHI" dump --keep-raw
}

cmd_check() {
  local clis=("$@"); [ ${#clis[@]} -eq 0 ] && clis=($CLIS)
  local q="Reply with just the word OK." cli run rc argv
  for cli in "${clis[@]}"; do
    run="$RUNS/$(date -u +%Y%m%dT%H%M%SZ)-check-$cli"
    umask 077; mkdir -p "$run/work"
    prepare_home "$cli" "$run/home" 0
    mapfile -d '' argv < <(headless "$cli" "$q")
    set +e
    CLIAUTH_TIMEOUT=180 sandbox "$run/home" "$run/work" "${argv[@]}" > "$run/out.txt" 2>&1 < /dev/null
    rc=$?
    set -e
    sync_back "$cli" "$run/home"
    if [ $rc = 0 ] && grep -q -w OK "$run/out.txt"; then echo "$cli: OK (login files only: $(auth_files "$cli"))"
    else echo "$cli: FAILED rc=$rc, see $run/out.txt"; tail -3 "$run/out.txt" | sed 's/^/    /'; fi
  done
}

cmd_run() {
  local cli=$1; shift; local work=$PWD shell=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --work) work=$(realpath "$2"); shift 2 ;;
      --shell) shell=1; shift ;;
      --) shift; break ;;
      *) break ;;
    esac
  done
  auth_files "$cli" >/dev/null
  check_pin "$cli"
  local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)
  local run="$RUNS/$stamp-$cli"; local home="$run/home"
  umask 077; mkdir -p "$run"
  prepare_home "$cli" "$home"
  printf 'cli=%s\nversion=%s\nwork=%s\nstarted=%s\n' "$cli" "$(version_of "$cli")" "$work" "$stamp" > "$run/run.info"
  trap 'sync_back "$cli" "$home"' EXIT
  set +e
  if [ $shell = 1 ]; then sandbox "$home" "$work" bash -l
  else sandbox "$home" "$work" "$cli" "$@"; fi
  local rc=$?
  set -e
  sync_back "$cli" "$home"; trap - EXIT
  echo "exit=$rc" >> "$run/run.info"
  dump_run "$home" | sed 's/^/wadachi: /' >&2 || echo "cliauth: wadachi dump failed; the run home is kept" >&2
  echo "cliauth: run kept in $run, store $STORE" >&2
  return $rc
}

refuse_git_root "$(dirname "$ROOT")"
case "${1:-}" in
  collect) shift; cmd_collect "$@" ;;
  versions) cmd_versions ;;
  run) shift; cmd_run "$@" ;;
  check) shift; cmd_check "$@" ;;
  shell) shift; cli=$1; shift; cmd_run "$cli" --shell "$@" ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
