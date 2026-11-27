# Shared by cliauth.sh and k8s-check.sh. Source it; it defines functions only.
SANDBOX_DIR="${SANDBOX_DIR:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")}"
CLIS="claude codex opencode agy grok"

auth_files() {  # the files carrying <cli>'s login, relative to $HOME
  local f; f=$(awk -v c="$1" '$1==c { $1=""; print }' "$SANDBOX_DIR/auth-files.txt")
  [ -n "$f" ] || { echo "unknown cli: $1" >&2; return 2; }
  echo $f
}

pinned() {  # pinned <name> [column]: a column of versions.lock (default 2, the version)
  awk -v c="$1" -v n="${2:-2}" '$1==c { print $n }' "${CLIAUTH_LOCK:-$SANDBOX_DIR/versions.lock}"
}

version_of() {  # the installed version, as the CLI prints it
  case "$1" in
    claude)   claude --version 2>/dev/null | awk '{print $1}' ;;
    codex)    codex --version 2>/dev/null | awk '{print $NF}' ;;
    opencode) opencode --version 2>/dev/null | tail -1 ;;
    agy)      agy --version 2>/dev/null | tail -1 ;;
    grok)     grok --version 2>/dev/null | awk '{print $2}' ;;
  esac
}

headless() {  # headless <cli> <prompt>: one non-interactive turn, as an argv
  case "$1" in
    claude)   printf '%s\0' claude -p "$2" ;;
    codex)    printf '%s\0' codex exec --skip-git-repo-check "$2" ;;
    opencode) printf '%s\0' opencode run "$2" ;;
    agy)      printf '%s\0' agy -p "$2" --output-format json ;;  # text mode hangs without a tty (1.5.18)
    grok)     printf '%s\0' grok -p "$2" ;;
  esac
}

# Copy one refreshed login file, unless the refresh lost its refresh token
# (a logged-out CLI must not overwrite a working login).
sync_one() {  # sync_one <cli> <from> <to>
  [ -f "$2" ] || return 0
  cmp -s "$2" "$3" && return 0
  if grep -q refreshToken "$3" 2>/dev/null && ! grep -q refreshToken "$2"; then
    echo "cliauth: $1 ${2##*/} lost its refresh token in the run; not synced back" >&2; return 0
  fi
  mkdir -p "$(dirname "$3")"; cp -p "$2" "$3"; chmod 600 "$3"
  echo "cliauth: $1 ${3} refreshed" >&2
}

refuse_git_root() {  # logins must never live in a repository
  if git -C "$1" rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "cliauth: $1 is inside a git working tree; keep logins outside any repository (set CLIAUTH_ROOT)" >&2
    exit 2
  fi
}
