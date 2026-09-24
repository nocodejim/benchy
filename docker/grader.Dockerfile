# benchy-grader: workspace setup, grading (hidden checks), diff screenshots, reports.
# The agent never runs in this image.
ARG PLAYWRIGHT_IMAGE
ARG NODE_IMAGE
FROM ${NODE_IMAGE} AS node

FROM ${PLAYWRIGHT_IMAGE}
ARG DIFF2HTML_CLI_VERSION
ARG ACTIONLINT_VERSION ACTIONLINT_SHA256 HADOLINT_VERSION HADOLINT_SHA256 \
    KUBECONFORM_VERSION KUBECONFORM_SHA256 HELM_VERSION HELM_SHA256 \
    SHELLCHECK_VERSION SHELLCHECK_SHA256 GITLEAKS_VERSION GITLEAKS_SHA256 JF_VERSION JF_SHA256 \
    K8S_SCHEMA_COMMIT K8S_SCHEMA_VERSION COMPOSE_SPEC_COMMIT

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3-venv xz-utils yamllint \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && npm install -g --no-fund --no-audit --ignore-scripts "diff2html-cli@${DIFF2HTML_CLI_VERSION}" \
 && npm cache clean --force

COPY docker/install-tools.sh /tmp/install-tools.sh
RUN bash /tmp/install-tools.sh actionlint hadolint kubeconform helm shellcheck gitleaks jf \
 && rm /tmp/install-tools.sh

COPY docker/schemas.sha256 /opt/schemas/SHA256SUMS
WORKDIR /opt/schemas
RUN base="https://raw.githubusercontent.com/yannh/kubernetes-json-schema/${K8S_SCHEMA_COMMIT}/${K8S_SCHEMA_VERSION}" \
 && awk '{print $2}' SHA256SUMS | grep -v compose-spec | while read -r f; do \
      curl -fsSL --retry 3 -o "$f" "$base/$f"; done \
 && curl -fsSL --retry 3 -o compose-spec.json \
      "https://raw.githubusercontent.com/compose-spec/compose-spec/${COMPOSE_SPEC_COMMIT}/schema/compose-spec.json" \
 && sha256sum -c --quiet SHA256SUMS

COPY docker/requirements-grader.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/bench/src \
    PYTHONDONTWRITEBYTECODE=1 \
    K8S_SCHEMA_DIR=/opt/schemas \
    HOME=/tmp/home
WORKDIR /bench
USER pwuser
