#!/bin/sh
# Container entrypoint: logins in, the command, then transcripts and refreshed logins out.
#
#   /auth      (read-only) auth.tgz holding the login files of auth-files.txt,
#              relative to HOME, or the same files as a directory tree
#   /handback  (optional, writable) the login files as they are after the
#              run, as auth.tgz: tokens rotate, so copy them back to where the
#              login lives, or the copy outside goes stale
#   /store     (optional, writable) `wadachi dump --keep-raw` of every
#              transcript in HOME
#   CLIAUTH_HOLD=N  wait N seconds after the run (time to `kubectl cp` /handback)
set -eu
FILES=/etc/wadachi-sandbox/auth-files.txt

if [ -f /auth/auth.tgz ]; then
  tar -xzf /auth/auth.tgz -C "$HOME"
elif [ -d /auth ]; then
  cp -R /auth/. "$HOME/"
fi

set +e
"$@"
rc=$?
set -e

if [ -d /store ] && [ -w /store ]; then
  wadachi dump --keep-raw --store /store >&2 || echo "wadachi-sandbox: dump failed" >&2
fi
if [ -d /handback ] && [ -w /handback ]; then
  present=""
  for f in $(awk '!/^#/ { for (i = 2; i <= NF; i++) print $i }' "$FILES"); do
    [ -f "$HOME/$f" ] && present="$present $f"
  done
  # shellcheck disable=SC2086  # paths from auth-files.txt have no spaces
  [ -n "$present" ] && (umask 077; tar -czf /handback/auth.tgz -C "$HOME" $present)
fi
echo "wadachi-sandbox: exit=$rc" >&2
[ "${CLIAUTH_HOLD:-0}" -gt 0 ] && sleep "$CLIAUTH_HOLD"
exit "$rc"
