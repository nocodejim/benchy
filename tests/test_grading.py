import pytest

from benchy.grade.engine import glob_to_regex, out_of_scope
from benchy.report.aggregate import aggregate, failure_mode


@pytest.mark.parametrize("pattern,path,ok", [
    ("app/**", "app/models.py", True),
    ("app/**", "app/api/users.py", True),
    ("app/**", "tests.py", False),
    (".github/**", ".github/workflows/ci.yml", True),
    ("Dockerfile", "Dockerfile", True),
    ("Dockerfile", "sub/Dockerfile", False),
    ("*.md", "README.md", True),
    ("*.md", "docs/a.md", False),
    ("**/*.md", "docs/a.md", True),
    ("**/*.md", "README.md", True),
    ("deploy/**", "deploy/helm/microblog/templates/x.yaml", True),
])
def test_glob(pattern, path, ok):
    assert bool(glob_to_regex(pattern).match(path)) is ok


def test_out_of_scope():
    assert out_of_scope(["app/x.py", "tests.py", "setup.cfg"], ["app/**", "tests.py"]) == ["setup.cfg"]


def run(contender, task, resolved, usd=1.0, wall=100, tokens=1000, exit_status="ok", regression=True, scope=0):
    return {"contender": contender, "task": task,
            "outcome": {"resolved": resolved, "score": 1.0 if resolved else 0.5, "exit_status": exit_status,
                        "regression_ok": regression, "scope_violations": scope, "secrets_found": 0},
            "cost": {"usd": usd, "ai_credits": usd * 100 if usd is not None else None},
            "time": {"wall_s": wall}, "tokens": {"total": tokens}, "activity": {"tool_calls": 5, "turns": 3},
            "diff": {"churn": 10}, "models_reported": ["m"], "harness_version": "v"}


def test_aggregate_cost_per_resolved_and_pass_k():
    runs = [
        run("A", "t1", True, usd=1.0), run("A", "t1", False, usd=3.0),   # t1 not solved every time
        run("A", "t2", True, usd=2.0), run("A", "t2", True, usd=2.0),
        run("B", "t1", True, usd=0.5), run("B", "t1", True, usd=0.5),
        run("B", "t2", False, usd=0.1, exit_status="timeout"), run("B", "t2", False, usd=None),
    ]
    agg = aggregate(runs, ["B", "A"])
    assert agg["contenders"] == ["B", "A"]
    a, b = agg["stats"]["A"], agg["stats"]["B"]
    assert a["resolve_rate"] == 0.75
    assert a["pass_all_k"] == 0.5
    assert a["usd_per_resolved"] == pytest.approx(8.0 / 3)      # failed attempt's spend included
    assert b["usd_per_resolved"] == pytest.approx(1.1 / 2)
    assert b["usd_complete"] is False                            # one run had no cost
    assert b["failures"] == {"timeout": 1, "checks failed": 1}
    assert agg["matrix"][("t1", "A")]["resolved"] == 1


def test_failure_modes():
    assert failure_mode(run("A", "t", True)) is None
    assert failure_mode(run("A", "t", False, regression=False)) == "broke existing tests"
    assert failure_mode(run("A", "t", False, scope=2)) == "out of scope"
    assert failure_mode(run("A", "t", False, exit_status="error")) == "harness error"
