# benchy-agent: where the AI coding agent runs. Contains the harness CLIs and the
# everyday tools a developer would reach for. Never contains tasks/ or hidden checks.
ARG UBUNTU_IMAGE
ARG NODE_IMAGE
FROM ${NODE_IMAGE} AS node

FROM ${UBUNTU_IMAGE}
ARG COPILOT_CLI_VERSION
ARG CLAUDE_CODE_VERSION
ARG ACTIONLINT_VERSION ACTIONLINT_SHA256 HADOLINT_VERSION HADOLINT_SHA256 \
    KUBECONFORM_VERSION KUBECONFORM_SHA256 HELM_VERSION HELM_SHA256 \
    SHELLCHECK_VERSION SHELLCHECK_SHA256 JF_VERSION JF_SHA256

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git jq less \
      python3 python3-venv python3-pip ripgrep xz-utils yamllint \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && npm install -g --no-fund --no-audit \
      "@github/copilot@${COPILOT_CLI_VERSION}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force

COPY docker/install-tools.sh /tmp/install-tools.sh
RUN bash /tmp/install-tools.sh actionlint hadolint kubeconform helm shellcheck jf \
 && rm /tmp/install-tools.sh

# Harness CLIs must never self-update mid-benchmark.
ENV COPILOT_AUTO_UPDATE=false \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    PYTHONPATH=/opt/benchy \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp/home

# benchy source is bind-mounted read-only at /opt/benchy at run time.
WORKDIR /work/repo
USER 65534:65534
