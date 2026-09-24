"""The hidden checks must reject plausible-but-wrong answers, not just accept the golden one."""
import os
import subprocess
import sys
import textwrap

import pytest

from conftest import ROOT

LIB = ROOT / "tasks" / "_lib" / "checklib.py"
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"


def check(cwd, *args, aux=None):
    env = {**os.environ, "SCHEMAS": os.environ.get("K8S_SCHEMA_DIR", "/opt/schemas")}
    if aux:
        env["AUX"] = str(aux)
    return subprocess.run([sys.executable, str(LIB), *args], cwd=cwd, env=env,
                          capture_output=True, text=True).returncode == 0


def put(tmp, name, text):
    p = tmp / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))
    return name


def wf(tmp, body):
    return put(tmp, ".github/workflows/ci.yml", body)


GOOD_CI = f"""
    on:
      pull_request: {{branches: [main]}}
      push: {{branches: [main]}}
    permissions: {{contents: read}}
    jobs:
      test:
        runs-on: ubuntu-24.04
        timeout-minutes: 10
        steps:
          - uses: {CHECKOUT}
          - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
            with: {{python-version: "3.12", cache: pip}}
          - run: python -m unittest tests
    """


def test_gha_good(tmp_path):
    f = wf(tmp_path, GOOD_CI)
    for a in ("gha-triggers", "gha-permissions-read", "gha-runs-tests", "gha-pinned", "gha-cache", "gha-timeouts"):
        assert check(tmp_path, a, f), a
    assert check(tmp_path, "gha-python", f, "3.12")


@pytest.mark.parametrize("mutation,assertion", [
    (lambda s: s.replace("permissions: {contents: read}", ""), "gha-permissions-read"),
    (lambda s: s.replace("{contents: read}", "{contents: write}"), "gha-permissions-read"),
    (lambda s: s.replace(CHECKOUT, "actions/checkout@v7"), "gha-pinned"),
    (lambda s: s.replace("python -m unittest tests", "echo skip"), "gha-runs-tests"),
    (lambda s: s.replace("pull_request: {branches: [main]}", "workflow_dispatch: {}"), "gha-triggers"),
    (lambda s: s.replace("timeout-minutes: 10", ""), "gha-timeouts"),
    (lambda s: s.replace(", cache: pip", ""), "gha-cache"),
])
def test_gha_mutations_fail(tmp_path, mutation, assertion):
    f = wf(tmp_path, mutation(GOOD_CI))
    assert not check(tmp_path, assertion, f)


def test_hallucinated_sha_detected(tmp_path):
    aux = tmp_path / "aux"
    aux.mkdir()
    (aux / "action-shas.txt").write_text(f"actions/checkout {CHECKOUT.split('@')[1]}\n")
    f = wf(tmp_path, GOOD_CI)
    assert check(tmp_path, "gha-known-shas", f, aux=aux)
    f = wf(tmp_path, GOOD_CI.replace(CHECKOUT, "actions/checkout@" + "1234567890" * 4))
    assert not check(tmp_path, "gha-known-shas", f, aux=aux)
    assert check(tmp_path, "gha-known-shas", f)            # no reference list -> skipped, not failed


def test_least_privilege_publish(tmp_path):
    body = """
    on: {push: {tags: ["v*"]}}
    permissions: {contents: read}
    jobs:
      build: {runs-on: x, steps: [{run: echo}]}
      publish:
        needs: build
        runs-on: x
        permissions: {contents: read, packages: write}
        steps: [{run: echo}]
    """
    f = wf(tmp_path, body)
    assert check(tmp_path, "gha-only-write", f, "publish", "packages")
    f = wf(tmp_path, body.replace("permissions: {contents: read}\n    jobs", "permissions: write-all\n    jobs"))
    assert not check(tmp_path, "gha-only-write", f, "publish", "packages")
    f = wf(tmp_path, body.replace("build: {runs-on: x,", "build: {runs-on: x, permissions: {packages: write},"))
    assert not check(tmp_path, "gha-only-write", f, "publish", "packages")


GOOD_DOCKER = """
    FROM docker.io/library/python:3.12-slim AS build
    RUN --mount=type=secret,id=pip,env=PIP_INDEX_URL pip install -r requirements.txt
    FROM docker.io/library/python:3.12-slim
    COPY --from=build /opt /opt
    USER 10001
    HEALTHCHECK CMD true
    """


def test_docker_good(tmp_path):
    put(tmp_path, "Dockerfile", GOOD_DOCKER)
    for a in ("docker-base-pinned", "docker-multistage", "docker-nonroot", "docker-numeric-user",
              "docker-healthcheck", "docker-pip-uses-secret", "docker-no-cred-args"):
        assert check(tmp_path, a), a


@pytest.mark.parametrize("mutation,assertion", [
    (lambda s: s.replace("python:3.12-slim\n    COPY", "python:slim\n    COPY"), "docker-base-pinned"),
    (lambda s: s.replace("python:3.12-slim AS build", "python:latest AS build"), "docker-base-pinned"),
    (lambda s: s.replace("USER 10001", "USER root"), "docker-nonroot"),
    (lambda s: s.replace("USER 10001", "USER app"), "docker-numeric-user"),
    (lambda s: s.replace("    USER 10001\n", ""), "docker-nonroot"),
    (lambda s: s.replace("HEALTHCHECK CMD true", "HEALTHCHECK NONE"), "docker-healthcheck"),
    (lambda s: s.replace("--mount=type=secret,id=pip,env=PIP_INDEX_URL ", ""), "docker-pip-uses-secret"),
    (lambda s: s.replace("USER 10001", "ARG ARTIFACTORY_TOKEN\n    USER 10001"), "docker-no-cred-args"),
    (lambda s: s.replace("pip install", "pip install -i https://u:p4ss@artifactory.example.com/x"),
     "docker-no-cred-args"),
])
def test_docker_mutations_fail(tmp_path, mutation, assertion):
    put(tmp_path, "Dockerfile", mutation(GOOD_DOCKER))
    assert not check(tmp_path, assertion)


def test_user_in_build_stage_only_is_root(tmp_path):
    put(tmp_path, "Dockerfile", "FROM python:3.12 AS b\nUSER 1000\nFROM python:3.12\nCMD x\n")
    assert not check(tmp_path, "docker-nonroot")


def test_docker_registry_prefix(tmp_path):
    put(tmp_path, "Dockerfile", "FROM artifactory.example.com/docker-remote/library/python:3.12 AS b\nFROM b\n")
    assert check(tmp_path, "docker-from-registry", "artifactory.example.com/docker-remote/")
    put(tmp_path, "Dockerfile", "FROM artifactory.example.com/docker-remote/python:3.12 AS b\nFROM python:3.12\n")
    assert not check(tmp_path, "docker-from-registry", "artifactory.example.com/docker-remote/")


COMPOSE = """
    services:
      web:
        image: localhost/app:dev
        environment:
          DATABASE_URL: "postgresql://app:${PGPASS}@db/app"
        depends_on: {db: {condition: service_healthy}}
      db:
        image: docker.io/library/postgres:17
        environment: {POSTGRES_PASSWORD: "${PGPASS}"}
        healthcheck: {test: ["CMD", "pg_isready"]}
    """


@pytest.mark.skipif(not os.path.exists("/opt/schemas/compose-spec.json"), reason="grader image only")
def test_compose(tmp_path):
    put(tmp_path, "compose.yaml", COMPOSE)
    assert check(tmp_path, "compose-valid")
    assert check(tmp_path, "compose-db-secret-not-literal")
    assert check(tmp_path, "compose-depends-healthy")
    put(tmp_path, "compose.yaml", COMPOSE.replace('"${PGPASS}"}', '"hunter2"}'))
    assert not check(tmp_path, "compose-db-secret-not-literal")
    put(tmp_path, "compose.yaml", COMPOSE.replace("app:${PGPASS}@", "app:hunter2@"))
    assert not check(tmp_path, "compose-db-secret-not-literal")
    put(tmp_path, "compose.yaml", COMPOSE.replace("image: localhost/app:dev", "image: [not, valid]"))
    assert not check(tmp_path, "compose-valid")
    put(tmp_path, "compose.yaml", COMPOSE.replace('        healthcheck: {test: ["CMD", "pg_isready"]}\n', ""))
    assert not check(tmp_path, "compose-depends-healthy")


def test_literal_secret_scan(tmp_path):
    put(tmp_path, "a.yml", "password: ${{ secrets.ARTIFACTORY_TOKEN }}\nARTIFACTORY_TOKEN: ${TOKEN}\n")
    assert check(tmp_path, "no-literal-secret", "a.yml")
    put(tmp_path, "a.yml", "ARTIFACTORY_TOKEN: cmVmdGtuOjAxOjE3\n")
    assert not check(tmp_path, "no-literal-secret", "a.yml")


DEPLOY = """
    apiVersion: apps/v1
    kind: Deployment
    metadata: {name: web}
    spec:
      selector: {matchLabels: {app: web}}
      template:
        metadata: {labels: {app: web}}
        spec:
          containers:
            - name: web
              image: x:1
              env:
                - name: SECRET_KEY
                  valueFrom: {secretKeyRef: {name: s, key: SECRET_KEY}}
              resources: {requests: {cpu: 1, memory: 1Gi}, limits: {cpu: 1, memory: 1Gi}}
              livenessProbe: {httpGet: {path: /, port: 5000}}
              readinessProbe: {httpGet: {path: /, port: 5000}}
              securityContext:
                runAsNonRoot: true
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: {drop: [ALL]}
    """


def k8s(tmp_path, text):
    (tmp_path / "rendered.yaml").write_text(textwrap.dedent(text))
    env = {**os.environ, "RENDERED": str(tmp_path / "rendered.yaml")}
    return lambda *args: subprocess.run([sys.executable, str(LIB), *args], cwd=tmp_path, env=env,
                                        capture_output=True).returncode == 0


def test_k8s_good_and_mutations(tmp_path):
    run = k8s(tmp_path, DEPLOY)
    for a in ("k8s-resources", "k8s-probes", "k8s-security"):
        assert run(a), a
    assert run("k8s-secret-refs", "SECRET_KEY")
    for bad, a in [
        (DEPLOY.replace("readOnlyRootFilesystem: true", "readOnlyRootFilesystem: false"), "k8s-security"),
        (DEPLOY.replace("                capabilities: {drop: [ALL]}\n", ""), "k8s-security"),
        (DEPLOY.replace("              livenessProbe: {httpGet: {path: /, port: 5000}}\n", ""), "k8s-probes"),
        (DEPLOY.replace(", limits: {cpu: 1, memory: 1Gi}", ""), "k8s-resources"),
        (DEPLOY.replace("valueFrom: {secretKeyRef: {name: s, key: SECRET_KEY}}", "value: plain"), "k8s-secret-refs"),
    ]:
        assert not k8s(tmp_path, bad)(a, *(["SECRET_KEY"] if a == "k8s-secret-refs" else [])), a


@pytest.mark.skipif(not os.path.exists("/usr/local/bin/kubeconform"), reason="grader image only")
def test_kubeconform_uses_vendored_schemas(tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text(textwrap.dedent(DEPLOY))
    loc = "/opt/schemas/{{.ResourceKind}}{{.KindSuffix}}.json"
    r = subprocess.run(["kubeconform", "-strict", "-schema-location", loc, str(good)], capture_output=True)
    assert r.returncode == 0, r.stdout
    bad = tmp_path / "bad.yaml"
    bad.write_text(textwrap.dedent(DEPLOY).replace("replicas", "x").replace("selector:", "selectr:"))
    r = subprocess.run(["kubeconform", "-strict", "-schema-location", loc, str(bad)], capture_output=True)
    assert r.returncode != 0


def test_fleet(tmp_path):
    put(tmp_path, "deploy/helm/microblog/Chart.yaml", "apiVersion: v2\nname: m\nversion: 0.1.0\n")
    fleet = """
    defaultNamespace: microblog
    helm: {chart: ./helm/microblog}
    targetCustomizations:
      - {name: s, clusterSelector: {matchLabels: {env: staging}}}
      - {name: p, clusterSelector: {matchLabels: {env: production}}, helm: {values: {replicaCount: 3}}}
    """
    put(tmp_path, "deploy/fleet.yaml", fleet)
    assert check(tmp_path, "fleet")
    assert check(tmp_path, "fleet-prod-replicas", "deploy/fleet.yaml", "3")
    put(tmp_path, "deploy/fleet.yaml", fleet.replace("env: staging", "env: stage"))
    assert not check(tmp_path, "fleet")
    put(tmp_path, "deploy/fleet.yaml", fleet.replace("./helm/microblog", "./helm/missing"))
    assert not check(tmp_path, "fleet")
