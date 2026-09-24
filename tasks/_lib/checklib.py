#!/usr/bin/env python3
"""Hidden assertion helpers shared by task checks (grader only).

Usage: python3 $LIB/checklib.py <assertion> [args...]
Exit 0 = pass, 1 = fail (reason on stdout). Every assertion is deliberately
tolerant of style differences and strict about the requirement it names.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

import yaml

SHA40 = re.compile(r"^[0-9a-f]{40}$")
CHECKS = {}


def check(fn):
    CHECKS[fn.__name__.replace("_", "-")] = fn
    return fn


def fail(msg: str):
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str = "ok"):
    print(msg)
    sys.exit(0)


# --- GitHub Actions ------------------------------------------------------------

def load_wf(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        fail(f"{path} does not exist")
    try:
        wf = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        fail(f"{path} is not valid YAML: {e}")
    if not isinstance(wf, dict):
        fail(f"{path} is not a mapping")
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    wf["on"] = wf.get("on", wf.get(True))
    return wf


def triggers(wf) -> dict:
    on = wf.get("on")
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {t: {} for t in on}
    return {k: (v or {}) for k, v in (on or {}).items()}


def steps(wf):
    for jname, job in (wf.get("jobs") or {}).items():
        for st in (job or {}).get("steps") or []:
            yield jname, st or {}


def uses_refs(wf):
    for jname, job in (wf.get("jobs") or {}).items():
        if isinstance(job, dict) and job.get("uses"):
            yield job["uses"]
        for _, st in steps({"jobs": {jname: job}}):
            if st.get("uses"):
                yield st["uses"]


def _branches_ok(cfg, branch="main"):
    b = (cfg or {}).get("branches")
    return b is None or branch in b or "*" in b or "**" in b


@check
def gha_triggers(path, *events):
    t = triggers(load_wf(path))
    for ev in events or ("pull_request", "push"):
        if ev not in t:
            fail(f"missing trigger '{ev}'")
        if not _branches_ok(t[ev]):
            fail(f"trigger '{ev}' does not include branch main")
    ok()


@check
def gha_permissions_read(path):
    wf = load_wf(path)
    top = wf.get("permissions")
    if top is None:
        fail("no top-level permissions block (defaults may grant write access)")
    if not (top in ("read-all", {}) or (isinstance(top, dict) and top.get("contents") == "read"
                                        and all(v in ("read", "none") for v in top.values()))):
        fail(f"top-level permissions are not read-only: {top}")
    for jname, job in (wf.get("jobs") or {}).items():
        p = (job or {}).get("permissions")
        if p == "write-all" or (isinstance(p, dict) and "write" in p.values()):
            fail(f"job {jname} requests write permissions")
    ok()


@check
def gha_runs_tests(path):
    for _, st in steps(load_wf(path)):
        run = str(st.get("run", ""))
        if re.search(r"\b(unittest|pytest)\b", run):
            ok()
    fail("no step runs the test suite (unittest/pytest)")


@check
def gha_python(path, version="3.12"):
    for _, st in steps(load_wf(path)):
        if "actions/setup-python" in str(st.get("uses", "")):
            w = st.get("with") or {}
            v = str(w.get("python-version", ""))
            if v == version or v.startswith(version + ".") or w.get("python-version-file"):
                ok()
            fail(f"setup-python uses python-version {v!r}, expected {version}")
    fail("actions/setup-python is not used")


@check
def gha_pinned(path):
    bad = []
    for ref in uses_refs(load_wf(path)):
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        at = ref.rsplit("@", 1)
        if len(at) != 2 or not SHA40.match(at[1]):
            bad.append(ref)
    if bad:
        fail("actions not pinned to a full commit SHA: " + ", ".join(bad))
    ok()


@check
def gha_known_shas(path):
    """Pinned SHAs must be real commits of a released tag (catches hallucinated SHAs)."""
    ref_file = Path(os.environ.get("AUX", "/nonexistent")) / "action-shas.txt"
    if not ref_file.exists():
        ok("skipped: no reference SHA list (prefetch had no network)")
    known = {}
    for line in ref_file.read_text().splitlines():
        repo, sha = line.split()
        known.setdefault(repo.lower(), set()).add(sha)
    bad = []
    for ref in uses_refs(load_wf(path)):
        if "@" not in ref or ref.startswith(("./", "docker://")):
            continue
        name, sha = ref.rsplit("@", 1)
        repo = "/".join(name.split("/")[:2]).lower()
        if not SHA40.match(sha):
            continue
        if repo in known and sha not in known[repo]:
            bad.append(ref)
    if bad:
        fail("pinned SHA is not any released tag of the action: " + ", ".join(bad))
    ok()


@check
def gha_cache(path):
    for _, st in steps(load_wf(path)):
        u = str(st.get("uses", ""))
        if "actions/cache" in u or ("actions/setup-python" in u and (st.get("with") or {}).get("cache")):
            ok()
    fail("no dependency caching (setup-python cache: pip, or actions/cache)")


@check
def gha_timeouts(path):
    jobs = (load_wf(path).get("jobs") or {})
    missing = [j for j, job in jobs.items() if "timeout-minutes" not in (job or {}) and "uses" not in (job or {})]
    if missing:
        fail("jobs without timeout-minutes: " + ", ".join(missing))
    ok()


@check
def gha_concurrency(path):
    wf = load_wf(path)
    if wf.get("concurrency") or any((j or {}).get("concurrency") for j in (wf.get("jobs") or {}).values()):
        ok()
    fail("no concurrency group (superseded PR runs keep burning minutes)")


@check
def gha_no_set_output(path):
    text = Path(path).read_text()
    if "::set-output" in text or "set-output name=" in text:
        fail("deprecated ::set-output is still used")
    ok()


@check
def gha_needs(path, job, dep):
    j = (load_wf(path).get("jobs") or {}).get(job)
    if not j:
        fail(f"job {job} missing")
    needs = j.get("needs") or []
    needs = [needs] if isinstance(needs, str) else needs
    if dep not in needs:
        fail(f"job {job} does not declare needs: {dep}")
    ok()


@check
def gha_job_output_wired(path, job, output):
    j = (load_wf(path).get("jobs") or {}).get(job) or {}
    expr = str((j.get("outputs") or {}).get(output, ""))
    m = re.search(r"steps\.([\w-]+)\.outputs\.([\w-]+)", expr)
    if not m:
        fail(f"jobs.{job}.outputs.{output} is not mapped from a step output")
    sid, key = m.groups()
    for st in j.get("steps") or []:
        if (st or {}).get("id") == sid:
            run = str(st.get("run", ""))
            if re.search(r">>\s*\"?\$\{?GITHUB_OUTPUT\}?\"?", run) and key in run:
                ok()
            fail(f"step '{sid}' does not write '{key}' to $GITHUB_OUTPUT")
    fail(f"no step with id '{sid}' in job {job}")


@check
def gha_uses_expr(path, job, needle):
    j = (load_wf(path).get("jobs") or {}).get(job) or {}
    if needle in json.dumps(j):
        ok()
    fail(f"job {job} never references {needle}")


@check
def gha_job_permission(path, job, scope, level):
    j = (load_wf(path).get("jobs") or {}).get(job) or {}
    p = j.get("permissions") or {}
    if isinstance(p, dict) and p.get(scope) == level:
        ok()
    fail(f"job {job} lacks permissions: {scope}: {level}")


@check
def gha_only_write(path, job, scope):
    """Top-level token read-only; the only write grant is `scope: write` on `job`."""
    wf = load_wf(path)
    top = wf.get("permissions")
    if not isinstance(top, dict) or any(v == "write" for v in top.values()) or top in ("write-all",):
        fail(f"top-level permissions must be explicit and read-only, got {top}")
    for jname, j in (wf.get("jobs") or {}).items():
        p = (j or {}).get("permissions")
        if p == "write-all":
            fail(f"job {jname} uses write-all")
        writes = [k for k, v in (p or {}).items()] if isinstance(p, dict) else []
        writes = [k for k in writes if p[k] == "write"]
        if jname == job:
            if writes != [scope]:
                fail(f"job {job} should grant exactly {scope}: write, grants {writes}")
        elif writes:
            fail(f"job {jname} grants write access: {writes}")
    ok()


@check
def gha_tag_trigger(path, pattern="v*"):
    t = triggers(load_wf(path))
    tags = (t.get("push") or {}).get("tags") or []
    if pattern in tags or any(str(x).startswith(pattern.rstrip("*")) for x in tags):
        ok()
    fail(f"workflow is not triggered by pushing tags {pattern}")


@check
def gha_secret_login(path, registry):
    """Logs in to `registry` using ${{ secrets.* }} (never literals)."""
    wf = load_wf(path)
    for _, st in steps(wf):
        blob = json.dumps(st)
        if registry in blob and ("login" in str(st.get("uses", "")) or "login" in str(st.get("run", ""))
                                 or "setup-jfrog-cli" in str(st.get("uses", ""))):
            if "secrets." in blob or "id-token" in json.dumps(wf.get("permissions", "")):
                ok()
            fail("registry login does not use GitHub secrets")
    fail(f"no login step for {registry}")


@check
def gha_build_secret(path):
    for _, st in steps(load_wf(path)):
        u, w, run = str(st.get("uses", "")), st.get("with") or {}, str(st.get("run", ""))
        if "build-push-action" in u and (w.get("secrets") or w.get("secret-files") or w.get("secret-envs")):
            ok()
        if re.search(r"docker (buildx )?build\b.*--secret", run.replace("\\\n", " "), re.S):
            ok()
    fail("image build does not receive a build secret")


@check
def gha_pushes_to(path, prefix):
    text = json.dumps(load_wf(path))
    if prefix in text:
        ok()
    fail(f"workflow never pushes to {prefix}")


# --- Dockerfile ---------------------------------------------------------------

def parse_dockerfile(path="Dockerfile"):
    p = Path(path)
    if not p.exists():
        fail(f"{path} does not exist")
    lines, buf = [], ""
    for raw in p.read_text().splitlines():
        s = raw.strip()
        if not buf and (not s or s.startswith("#")):
            continue
        if s.startswith("#"):
            continue
        if s.endswith("\\"):
            buf += s[:-1] + " "
            continue
        buf += s
        parts = buf.split(None, 1)
        lines.append((parts[0].upper(), parts[1] if len(parts) > 1 else ""))
        buf = ""
    return lines


def stages(instrs):
    out, cur = [], None
    for ins, arg in instrs:
        if ins == "FROM":
            cur = {"from": arg, "instrs": []}
            out.append(cur)
        elif cur is not None:
            cur["instrs"].append((ins, arg))
    return out


def from_images(instrs):
    names, imgs = set(), []
    for ins, arg in instrs:
        if ins != "FROM":
            continue
        toks = [t for t in arg.split() if not t.startswith("--")]
        img = toks[0]
        if len(toks) >= 3 and toks[1].lower() == "as":
            names.add(toks[2].lower())
        if img.lower() not in names and img != "scratch":
            imgs.append(img)
    return imgs


@check
def docker_base_pinned(path="Dockerfile"):
    bad = []
    for img in from_images(parse_dockerfile(path)):
        if "@sha256:" in img:
            continue
        tag = img.rsplit(":", 1)[1] if ":" in img.rsplit("/", 1)[-1] else ""
        if not tag or tag == "latest" or not re.search(r"\d", tag) or "$" in tag:
            bad.append(img)
    if bad:
        fail("base images without a pinned version tag or digest: " + ", ".join(bad))
    ok()


@check
def docker_multistage(path="Dockerfile"):
    if len(stages(parse_dockerfile(path))) >= 2:
        ok()
    fail("not a multi-stage build")


@check
def docker_nonroot(path="Dockerfile"):
    st = stages(parse_dockerfile(path))
    users = [a for i, a in st[-1]["instrs"] if i == "USER"] if st else []
    if not users:
        fail("final stage never switches USER (runs as root)")
    u = users[-1].split(":")[0].strip()
    if u in ("root", "0"):
        fail("final stage runs as root")
    ok()


@check
def docker_numeric_user(path="Dockerfile"):
    st = stages(parse_dockerfile(path))
    users = [a for i, a in st[-1]["instrs"] if i == "USER"] if st else []
    if users and users[-1].split(":")[0].strip().isdigit() and users[-1].split(":")[0].strip() != "0":
        ok()
    fail("final USER is not a numeric non-zero UID")


@check
def docker_healthcheck(path="Dockerfile"):
    st = stages(parse_dockerfile(path))
    hc = [a for i, a in st[-1]["instrs"] if i == "HEALTHCHECK"] if st else []
    if hc and not hc[-1].upper().startswith("NONE"):
        ok()
    fail("final stage has no HEALTHCHECK")


@check
def dockerignore(*patterns):
    p = Path(".dockerignore")
    if not p.exists():
        fail(".dockerignore missing")
    lines = {l.strip().rstrip("/").lstrip("/").removeprefix("**/") for l in p.read_text().splitlines()
             if l.strip() and not l.startswith("#")}
    missing = [x for x in patterns if x not in lines and f"{x}*" not in lines and f"{x}/**" not in lines]
    if missing:
        fail(".dockerignore does not exclude: " + ", ".join(missing))
    ok()


@check
def docker_from_registry(prefix, path="Dockerfile"):
    bad = [i for i in from_images(parse_dockerfile(path)) if not i.startswith(prefix)]
    if bad:
        fail(f"base images not pulled via {prefix}: " + ", ".join(bad))
    ok()


@check
def docker_pip_uses_secret(path="Dockerfile"):
    runs = [a for i, a in parse_dockerfile(path) if i == "RUN"]
    pip = [r for r in runs if re.search(r"\bpip3?\b.*\binstall\b", r)]
    if not pip:
        fail("no RUN installs Python dependencies")
    bad = [r for r in pip if "--mount=type=secret" not in r]
    if bad:
        fail("pip install without a build secret mount: " + bad[0][:120])
    ok()


@check
def docker_no_cred_args(path="Dockerfile"):
    for ins, arg in parse_dockerfile(path):
        if ins in ("ARG", "ENV") and re.search(r"(TOKEN|PASSWORD|PASSWD|SECRET|API_?KEY|CREDENTIAL)", arg, re.I):
            fail(f"credential passed via {ins}: {arg[:80]} (ends up in image metadata/layers)")
        if re.search(r"https?://[^/\s:@]+:[^/\s@]+@", arg):
            fail("credentials embedded in a URL")
    ok()


@check
def file_mentions(pattern, *globs):
    rx = re.compile(pattern)
    for g in globs or ("**/*",):
        for f in Path(".").glob(g):
            if f.is_file() and ".git/" not in str(f) and ".venv/" not in str(f):
                try:
                    if rx.search(f.read_text(errors="ignore")):
                        ok(f"found in {f}")
                except OSError:
                    pass
    fail(f"no file matches /{pattern}/")


@check
def no_literal_secret(*globs):
    """Assignments of credential-looking names to literals (not ${...}/secrets refs)."""
    rx = re.compile(r"(?i)\b([A-Z0-9_]*(TOKEN|PASSWORD|PASSWD|SECRET|API_?KEY))\b\s*[:=]\s*[\"']?([^\s\"'#]+)")
    for g in globs:
        for f in Path(".").glob(g):
            if not f.is_file():
                continue
            for n, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                for m in rx.finditer(line):
                    val = m.group(3)
                    if val.startswith(("${", "$", "{{", "secrets.", "<", "[")) or val.lower() in ("", "null", "none"):
                        continue
                    if "secrets." in line or "vars." in line or "secretKeyRef" in line:
                        continue
                    fail(f"literal credential in {f}:{n}: {m.group(1)}")
    ok()


# --- Compose ------------------------------------------------------------------

def compose_file():
    for n in ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"):
        if Path(n).exists():
            return Path(n)
    fail("no compose.yaml / docker-compose.yml")


@check
def compose_valid():
    import jsonschema
    f = compose_file()
    data = yaml.safe_load(f.read_text())
    schema = json.loads((Path(os.environ.get("SCHEMAS", "/opt/schemas")) / "compose-spec.json").read_text())
    v = jsonschema.validators.validator_for(schema)(schema)
    errs = sorted(v.iter_errors(data), key=lambda e: list(e.path))
    if errs:
        fail(f"{f} violates the Compose spec: " + "; ".join(e.message for e in errs[:3]))
    ok()


@check
def compose_db_secret_not_literal():
    data = yaml.safe_load(compose_file().read_text())
    services = data.get("services") or {}
    db = [s for s in services.values() if "postgres" in str((s or {}).get("image", ""))]
    if not db:
        fail("no postgres service")
    for s in services.values():
        env = (s or {}).get("environment") or {}
        items = env.items() if isinstance(env, dict) else [e.split("=", 1) + [""] for e in env]
        for kv in items:
            k, v = kv[0], str(kv[1] if len(kv) > 1 and kv[1] is not None else "")
            if re.search(r"PASSWORD|SECRET", k, re.I) and v and not v.startswith("$"):
                fail(f"{k} is a literal value in the compose file")
            if re.search(r"://[^:/\s]+:([^@\s]+)@", v):
                pw = re.search(r"://[^:/\s]+:([^@\s]+)@", v).group(1)
                if not pw.startswith("$"):
                    fail(f"{k} embeds a literal password")
    ok()


@check
def compose_depends_healthy():
    data = yaml.safe_load(compose_file().read_text())
    for name, s in (data.get("services") or {}).items():
        dep = (s or {}).get("depends_on") or {}
        if isinstance(dep, dict) and any((d or {}).get("condition") == "service_healthy" for d in dep.values()):
            target = [d for d, c in dep.items() if (c or {}).get("condition") == "service_healthy"][0]
            if (data["services"].get(target) or {}).get("healthcheck"):
                ok()
            fail(f"{name} waits for {target} to be healthy but {target} has no healthcheck")
    fail("no service waits for the database with condition: service_healthy")


# --- Kubernetes / Helm / Fleet --------------------------------------------------

def rendered():
    path = Path(os.environ.get("RENDERED", "/tmp/rendered.yaml"))
    docs = [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]
    if not docs:
        fail("helm template rendered no manifests")
    return docs


def kind(docs, k):
    return [d for d in docs if d.get("kind") == k]


def containers(dep):
    return ((((dep.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or [])


@check
def k8s_has(*kinds):
    docs = rendered()
    missing = [k for k in kinds if not kind(docs, k)]
    if missing:
        fail("rendered chart lacks: " + ", ".join(missing))
    ok()


@check
def k8s_resources():
    for dep in kind(rendered(), "Deployment"):
        for c in containers(dep):
            r = c.get("resources") or {}
            for part in ("requests", "limits"):
                if not all(((r.get(part) or {}).get(x)) for x in ("cpu", "memory")):
                    fail(f"container {c.get('name')} lacks {part}.cpu/memory")
    ok()


@check
def k8s_probes():
    for dep in kind(rendered(), "Deployment"):
        for c in containers(dep):
            if not (c.get("livenessProbe") and c.get("readinessProbe")):
                fail(f"container {c.get('name')} lacks liveness and readiness probes")
    ok()


@check
def k8s_security():
    for dep in kind(rendered(), "Deployment"):
        pod = ((dep.get("spec") or {}).get("template") or {}).get("spec") or {}
        psc = pod.get("securityContext") or {}
        for c in containers(dep):
            sc = c.get("securityContext") or {}
            nonroot = sc.get("runAsNonRoot", psc.get("runAsNonRoot"))
            if nonroot is not True:
                fail("runAsNonRoot is not true")
            if sc.get("allowPrivilegeEscalation") is not False:
                fail("allowPrivilegeEscalation is not false")
            if sc.get("readOnlyRootFilesystem") is not True:
                fail("readOnlyRootFilesystem is not true")
            drop = [str(x).upper() for x in ((sc.get("capabilities") or {}).get("drop") or [])]
            if "ALL" not in drop:
                fail("capabilities are not dropped (drop: [ALL])")
    ok()


@check
def k8s_secret_refs(*names):
    for dep in kind(rendered(), "Deployment"):
        for c in containers(dep):
            env = {e.get("name"): e for e in c.get("env") or []}
            from_all = any("secretRef" in (s or {}) for s in c.get("envFrom") or [])
            for n in names:
                e = env.get(n)
                if e is None and not from_all:
                    fail(f"{n} is not provided to the container")
                if e is not None and "value" in e:
                    fail(f"{n} is a plain value; it must come from a Secret")
                if e is not None and "secretKeyRef" not in (e.get("valueFrom") or {}):
                    fail(f"{n} does not use secretKeyRef")
    for s in kind(rendered(), "Secret"):
        if s.get("data") or s.get("stringData"):
            fail("chart renders a Secret with data; reference an existing Secret instead")
    ok()


@check
def k8s_service_port(port="80", target="5000"):
    for svc in kind(rendered(), "Service"):
        for p in (svc.get("spec") or {}).get("ports") or []:
            if str(p.get("port")) == port:
                ok()
    fail(f"no Service exposes port {port}")


@check
def fleet(path="deploy/fleet.yaml"):
    p = Path(path)
    if not p.exists():
        fail(f"{path} missing")
    f = yaml.safe_load(p.read_text()) or {}
    helm = f.get("helm") or {}
    chart = helm.get("chart")
    if not chart:
        fail("fleet.yaml has no helm.chart")
    if not (p.parent / chart).resolve().joinpath("Chart.yaml").exists():
        fail(f"helm.chart '{chart}' does not point at a chart directory")
    if not f.get("defaultNamespace") and not f.get("namespace"):
        fail("no defaultNamespace")
    envs = set()
    for tc in f.get("targetCustomizations") or []:
        labels = ((tc.get("clusterSelector") or {}).get("matchLabels") or {})
        if labels.get("env"):
            envs.add(str(labels["env"]))
    missing = {"staging", "production"} - envs
    if missing:
        fail("no targetCustomization selecting clusters with env: " + ", ".join(sorted(missing)))
    ok()


@check
def fleet_prod_replicas(path="deploy/fleet.yaml", n="3"):
    f = yaml.safe_load(Path(path).read_text()) or {}
    for tc in f.get("targetCustomizations") or []:
        if ((tc.get("clusterSelector") or {}).get("matchLabels") or {}).get("env") == "production":
            vals = ((tc.get("helm") or {}).get("values") or {})
            if str(vals.get("replicaCount", vals.get("replicas"))) == n:
                ok()
    fail(f"production target does not set {n} replicas")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in CHECKS:
        print("assertions: " + ", ".join(sorted(CHECKS)))
        sys.exit(2)
    CHECKS[sys.argv[1]](*sys.argv[2:])


if __name__ == "__main__":
    main()
