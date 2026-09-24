#!/usr/bin/env bash
# Download pinned static binaries, verify sha256, install into /usr/local/bin.
# Usage: install-tools.sh actionlint hadolint ...   (versions/sums come from build-arg env)
set -euo pipefail

BIN=/usr/local/bin
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fetch() { # url sha256 dest
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c --quiet -
}

for tool in "$@"; do
  case "$tool" in
    actionlint)
      fetch "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" \
        "$ACTIONLINT_SHA256" "$TMP/a.tgz"
      tar -xzf "$TMP/a.tgz" -C "$BIN" actionlint ;;
    hadolint)
      fetch "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-linux-x86_64" \
        "$HADOLINT_SHA256" "$BIN/hadolint" ;;
    kubeconform)
      fetch "https://github.com/yannh/kubeconform/releases/download/v${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" \
        "$KUBECONFORM_SHA256" "$TMP/k.tgz"
      tar -xzf "$TMP/k.tgz" -C "$BIN" kubeconform ;;
    helm)
      fetch "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" "$HELM_SHA256" "$TMP/h.tgz"
      tar -xzf "$TMP/h.tgz" -C "$TMP" && mv "$TMP/linux-amd64/helm" "$BIN/helm" ;;
    shellcheck)
      fetch "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" \
        "$SHELLCHECK_SHA256" "$TMP/s.txz"
      tar -xJf "$TMP/s.txz" -C "$TMP" && mv "$TMP/shellcheck-v${SHELLCHECK_VERSION}/shellcheck" "$BIN/shellcheck" ;;
    gitleaks)
      fetch "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
        "$GITLEAKS_SHA256" "$TMP/g.tgz"
      tar -xzf "$TMP/g.tgz" -C "$BIN" gitleaks ;;
    jf)
      fetch "https://releases.jfrog.io/artifactory/jfrog-cli/v2-jf/${JF_VERSION}/jfrog-cli-linux-amd64/jf" \
        "$JF_SHA256" "$BIN/jf" ;;
    *) echo "unknown tool: $tool" >&2; exit 2 ;;
  esac
done
chmod 0755 "$BIN"/*
