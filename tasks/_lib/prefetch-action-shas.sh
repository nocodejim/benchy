#!/usr/bin/env bash
# Grader-only: record the commit SHAs of every release tag of commonly used
# GitHub Actions, so checks can tell a real pinned SHA from a hallucinated one.
# Output: $AUX/action-shas.txt  ("owner/repo sha" per line). Runs during setup.
set -uo pipefail
repos=(
  actions/checkout actions/setup-python actions/cache actions/setup-node
  actions/upload-artifact actions/download-artifact
  docker/setup-buildx-action docker/setup-qemu-action docker/login-action
  docker/build-push-action docker/metadata-action
  jfrog/setup-jfrog-cli azure/setup-helm github/codeql-action
)
out="$AUX/action-shas.txt.tmp"
: > "$out"
for r in "${repos[@]}"; do
  git ls-remote --tags "https://github.com/$r.git" 2>/dev/null \
    | awk -v r="$r" '{print r, $1}' >> "$out" || true
done
[ -s "$out" ] && mv "$out" "$AUX/action-shas.txt"
wc -l "$AUX/action-shas.txt" 2>/dev/null || echo "no network: SHA reference list not created"
