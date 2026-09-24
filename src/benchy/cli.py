"""benchy command line (runs inside the containers; ./bench is the host front-end).

Agent-image commands (stdlib only): agent, login
Grader-image commands:               plan, setup, finalize, report, validate, verify-selftest
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def cmd_plan(a):
    from .setup_ws import plan
    tasks = [t for t in (a.tasks or "").split(",") if t] or None
    data = plan(Path(a.contenders), a.suite, tasks, a.repeats, a.timeout_scale)
    # TSV consumed by ./bench: run_id, task, harness, timeout
    for r in data["runs"]:
        print(f"{r['run_id']}\t{r['task']}\t{r['contender']['harness']}\t{r['timeout_s']}")


def cmd_setup(a):
    from .setup_ws import setup
    info = setup(a.run_id)
    print(f"[setup] {info['run_id']} baseline={info['baseline_commit'][:10]}", file=sys.stderr)


def cmd_agent(a):
    from .agent_step import main
    return main()


def cmd_login(a):
    from . import harness
    h = harness.get(a.harness)
    cmd, env = h.login_command(Path("/auth"))
    for v in env.values():
        Path(v).mkdir(parents=True, exist_ok=True)
    os.execvpe(cmd[0], cmd, {**os.environ, **env})


def cmd_finalize(a):
    from .finalize import finalize
    finalize(a.run_id, keep_workspace=a.keep_workspace, screenshots=not a.no_screenshots)


def cmd_report(a):
    from .report.render import build_report
    from .setup_ws import OUT
    rdir = build_report(OUT, a.batch, screenshot=not a.no_screenshot)
    print(f"[report] {rdir}/index.html")


def cmd_validate(a):
    from . import config
    ids = config.all_task_ids()
    for t in ids:
        task = config.load_task(t)
        config.load_repo(task["repo"])
        if not task["solution_path"].exists():
            raise SystemExit(f"task {t}: missing golden solution {task['solution_path']}")
    for suite in sorted((config.ROOT / "suites").glob("*.yaml")):
        for t in config.load_suite(suite.stem):
            if t not in ids:
                raise SystemExit(f"suite {suite.stem}: unknown task {t}")
    for f in a.contenders or []:
        config.load_contenders(Path(f))
    print(f"[validate] {len(ids)} tasks OK")


def cmd_verify_selftest(a):
    from .selftest import verify
    return verify(a.batch, a.probe_batch)


def main(argv=None):
    p = argparse.ArgumentParser(prog="benchy")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("plan")
    s.add_argument("--contenders", required=True)
    s.add_argument("--suite", default="starter")
    s.add_argument("--tasks", help="comma-separated task ids (overrides --suite)")
    s.add_argument("--repeats", type=int, default=3)
    s.add_argument("--timeout-scale", type=float, default=1.0)
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("setup")
    s.add_argument("run_id")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("agent")
    s.set_defaults(fn=cmd_agent)

    s = sub.add_parser("login")
    s.add_argument("harness")
    s.set_defaults(fn=cmd_login)

    s = sub.add_parser("finalize")
    s.add_argument("run_id")
    s.add_argument("--keep-workspace", action="store_true")
    s.add_argument("--no-screenshots", action="store_true")
    s.set_defaults(fn=cmd_finalize)

    s = sub.add_parser("report")
    s.add_argument("--batch", default="latest")
    s.add_argument("--no-screenshot", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("validate")
    s.add_argument("--contenders", nargs="*")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("verify-selftest")
    s.add_argument("batch")
    s.add_argument("--probe-batch")
    s.set_defaults(fn=cmd_verify_selftest)

    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
