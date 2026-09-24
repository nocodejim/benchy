import pytest
import yaml

from benchy import config, setup_ws
from conftest import ROOT


def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data))
    return p


def test_all_shipped_tasks_load():
    ids = config.all_task_ids(ROOT)
    assert set(config.load_suite("starter", ROOT)) <= set(ids)
    for t in ids:
        task = config.load_task(t, ROOT)
        assert task["solution_path"].exists(), t
        assert task["prompt_path"].exists(), t
        config.load_repo(task["repo"], ROOT)


def test_prompts_do_not_leak_hidden_details():
    for t in config.all_task_ids(ROOT):
        prompt = config.build_prompt(config.load_task(t, ROOT), ROOT)
        for leak in ("hidden/", "checklib", "solution.patch", "$HIDDEN", "$LIB"):
            assert leak not in prompt, (t, leak)


def test_contenders_validation(tmp_path):
    ok = write(tmp_path / "c.yaml", {"contenders": [
        {"name": "A", "harness": "copilot", "model": "gpt-5.6-luna", "effort": "xhigh"},
        {"name": "B", "harness": "copilot", "model": "claude-sonnet-5", "effort": "high"}]})
    cs = config.load_contenders(ok)
    assert cs[0]["slug"] == "copilot-gpt-5.6-luna-xhigh"

    for bad in (
        {"name": "A", "harness": "nope"},
        {"name": "A", "harness": "copilot", "model": "x; rm -rf /"},
        {"name": "A", "harness": "copilot", "effort": "ludicrous"},
        {"name": "A", "harness": "copilot", "extra_args": ["--flag", "$(whoami)"]},
    ):
        with pytest.raises(SystemExit):
            config.load_contenders(write(tmp_path / "bad.yaml", {"contenders": [bad]}))
    dup = write(tmp_path / "dup.yaml", {"contenders": [
        {"name": "A", "harness": "copilot", "model": "m"}, {"name": "B", "harness": "copilot", "model": "m"}]})
    with pytest.raises(SystemExit):
        config.load_contenders(dup)


def test_task_paths_cannot_escape(tmp_path):
    (tmp_path / "tasks" / "evil").mkdir(parents=True)
    (tmp_path / "tasks" / "evil" / "prompt.md").write_text("x")
    write(tmp_path / "tasks" / "evil" / "task.yaml", {
        "title": "t", "repo": "r", "setup": [{"patch": "../../../etc/passwd"}],
        "checks": [{"id": "c", "run": "true"}]})
    with pytest.raises(SystemExit, match="escapes"):
        config.load_task("evil", tmp_path)


def test_repo_must_be_pinned(tmp_path):
    write(tmp_path / "repos" / "r.yaml", {"url": "https://example.com/r.git", "sha": "main"})
    with pytest.raises(SystemExit, match="40-char"):
        config.load_repo("r", tmp_path)
    write(tmp_path / "repos" / "r.yaml", {"url": "http://example.com/r.git", "sha": "a" * 40})
    with pytest.raises(SystemExit, match="https"):
        config.load_repo("r", tmp_path)


def test_plan_interleaves_and_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_ws, "OUT", tmp_path)
    c = write(tmp_path / "c.yaml", {"contenders": [
        {"name": "A", "harness": "mock", "model": "a"}, {"name": "B", "harness": "mock", "model": "b"}]})
    data = setup_ws.plan(c, None, ["bugfix-unit", "gha-ci-add"], 2)
    order = [(r["repeat"], r["task"], r["contender"]["name"]) for r in data["runs"]]
    assert order == [
        (1, "bugfix-unit", "A"), (1, "bugfix-unit", "B"), (1, "gha-ci-add", "A"), (1, "gha-ci-add", "B"),
        (2, "bugfix-unit", "B"), (2, "bugfix-unit", "A"), (2, "gha-ci-add", "B"), (2, "gha-ci-add", "A")]
    ids = [r["run_id"] for r in data["runs"]]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith(data["batch"] + "-") and len(i) < 120 for i in ids)
    assert (tmp_path / "batches" / f"{data['batch']}.json").exists()
