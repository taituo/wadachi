#!/usr/bin/env bash
# k8s-check: does each CLI's login work in a Kubernetes pod with only its login files?
# One pod per CLI from the sandbox image: the login files from a Secret, HOME
# empty otherwise, no tty, one headless prompt. Refreshed login files are copied
# back to $CLIAUTH_ROOT/auth/ through /handback, so the login outside stays valid.
#
#   k8s-check.sh IMAGE [cli...]   IMAGE from build-image.sh (--k3s imports it into k3s)
#   NS=wadachi-sandbox            namespace, created if missing
#   POD_DNS=1.1.1.1               bypass cluster DNS with this nameserver
#   HOSTNET=1                     use the node's network (a cluster without pod egress)
# Needs: bash, kubectl, tar.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

IMAGE=${1:?usage: k8s-check.sh IMAGE [cli...]}; shift
ROOT="${CLIAUTH_ROOT:-$HOME/cliauth}"
NS="${NS:-wadachi-sandbox}"
Q="Reply with just the word OK."
clis=("$@"); [ ${#clis[@]} -eq 0 ] && clis=($CLIS)
refuse_git_root "$(dirname "$ROOT")"

yaml_list() {  # argv as a YAML flow sequence of single-quoted strings
  local out="" a
  for a in "$@"; do out+="'${a//\'/\'\'}', "; done
  echo "[${out%, }]"
}

kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null
for cli in "${clis[@]}"; do
  for f in $(auth_files "$cli"); do
    [ -f "$ROOT/auth/$cli/$f" ] || { echo "$cli: no $ROOT/auth/$cli/$f (cliauth.sh collect $cli)"; continue 2; }
  done
  pod="check-$cli"
  kubectl -n "$NS" delete pod "$pod" --ignore-not-found --wait=true >/dev/null
  kubectl -n "$NS" delete secret "login-$cli" --ignore-not-found >/dev/null
  tmp=$(mktemp -d)
  (cd "$ROOT/auth/$cli" && tar -czf "$tmp/auth.tgz" $(auth_files "$cli"))
  kubectl -n "$NS" create secret generic "login-$cli" --from-file=auth.tgz="$tmp/auth.tgz" >/dev/null
  rm -rf "$tmp"
  mapfile -d '' argv < <(headless "$cli" "$Q")
  kubectl -n "$NS" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata: {name: $pod}
spec:
  restartPolicy: Never
$([ "${HOSTNET:-0}" = 1 ] && echo '  hostNetwork: true')
$([ -n "${POD_DNS:-}" ] && printf '  dnsPolicy: "None"\n  dnsConfig: {nameservers: [%s]}\n' "$POD_DNS")
  securityContext: {runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000}
  containers:
  - name: cli
    image: $IMAGE
    imagePullPolicy: IfNotPresent
    args: $(yaml_list "${argv[@]}")
    env: [{name: CLIAUTH_HOLD, value: "120"}]
    volumeMounts:
    - {name: login, mountPath: /auth, readOnly: true}
    - {name: handback, mountPath: /handback}
  volumes:
  - {name: login, secret: {secretName: login-$cli, defaultMode: 0440}}
  - {name: handback, emptyDir: {}}
EOF
done

for cli in "${clis[@]}"; do
  pod="check-$cli"
  kubectl -n "$NS" get pod "$pod" >/dev/null 2>&1 || continue
  for _ in $(seq 150); do
    kubectl -n "$NS" logs "$pod" 2>/dev/null | grep -q '^wadachi-sandbox: exit=' && break
    [ "$(kubectl -n "$NS" get pod "$pod" -o jsonpath='{.status.phase}')" = Failed ] && break
    sleep 2
  done
  out=$(kubectl -n "$NS" logs "$pod" 2>&1 | tail -c 3000)
  tmp=$(mktemp -d)
  if kubectl -n "$NS" cp "$pod:/handback/auth.tgz" "$tmp/auth.tgz" >/dev/null 2>&1; then
    mkdir "$tmp/home"; tar -xzf "$tmp/auth.tgz" -C "$tmp/home"
    for f in $(auth_files "$cli"); do sync_one "$cli" "$tmp/home/$f" "$ROOT/auth/$cli/$f"; done
  fi
  rm -rf "$tmp"
  kubectl -n "$NS" delete pod "$pod" --wait=false >/dev/null
  kubectl -n "$NS" delete secret "login-$cli" >/dev/null
  if grep -q '^wadachi-sandbox: exit=0' <<<"$out" && grep -q -w OK <<<"$out"; then
    echo "$cli: OK in a pod (login files only)"
  else
    echo "$cli: FAILED"; grep -v '^wadachi-sandbox:' <<<"$out" | tail -3 | cut -c1-200 | sed 's/^/    /'
  fi
done
