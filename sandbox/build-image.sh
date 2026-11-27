#!/usr/bin/env bash
# Build the sandbox image from one commit with the pins in versions.lock.
#
#   build-image.sh [--k3s] [commit]   default commit HEAD; --k3s imports into k3s's containerd
# Needs: git, podman or docker; sudo and k3s for --k3s. Prints the image name.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

k3s=0; [ "${1:-}" = --k3s ] && { k3s=1; shift; }
repo=$(git -C "$SANDBOX_DIR" rev-parse --show-toplevel)
commit=$(git -C "$repo" rev-parse "${1:-HEAD}")
engine=$(command -v podman || command -v docker || { echo "need podman or docker" >&2; exit 2; })
image="localhost/wadachi-sandbox:${commit:0:12}"

ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
# Only tracked files of that commit: nothing untracked or ignored (logins, .private) can get in.
git -C "$repo" archive --format=tar "$commit" | tar -x -C "$ctx"
lock="$ctx/sandbox/versions.lock"
pin() { CLIAUTH_LOCK="$lock" pinned "$@"; }

"$engine" build -f "$ctx/sandbox/Containerfile" -t "$image" \
  --build-arg NODE_IMAGE="$(pin node 3 | sed 's/^image://')" \
  --build-arg CLAUDE_VERSION="$(pin claude)" \
  --build-arg CODEX_VERSION="$(pin codex)" \
  --build-arg OPENCODE_VERSION="$(pin opencode)" \
  --build-arg AGY_URL="$(pin agy 3)" --build-arg AGY_SHA512="$(pin agy 4 | sed 's/^sha512://')" \
  --build-arg GROK_URL="$(pin grok 3)" --build-arg GROK_SHA256="$(pin grok 4 | sed 's/^sha256://')" \
  --build-arg WADACHI_COMMIT="$commit" \
  "$ctx" >&2

# The image must hold exactly the pinned versions.
for cli in $CLIS; do
  have=$("$engine" run --rm --entrypoint bash "$image" -c "$(declare -f version_of); version_of $cli")
  [ "$have" = "$(pin "$cli")" ] || { echo "$cli in the image is '$have', pinned $(pin "$cli")" >&2; exit 1; }
done

if [ $k3s = 1 ]; then
  "$engine" save "$image" | sudo k3s ctr images import - >&2
fi
echo "$image"
