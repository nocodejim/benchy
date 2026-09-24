# Running benchy at work: a checklist

This is a self-contained checklist for setting benchy up on a work laptop (Windows + WSL +
Docker Desktop) with a **Copilot Business** seat, and running the first comparison. Every step
says what you should see and what to do if you don't. Section numbers such as "(manual 4.2)"
refer to [user-manual.md](user-manual.md).

Allow about half a day: 1 hour for setup, then the batch runs unattended.

---

## Before you start: get the approvals (on paper)

benchy sends the repository it works on to the AI model vendors through GitHub Copilot, exactly
as Copilot does in your IDE. The starter tasks only use a public open-source app (microblog), so
**no company code leaves the building unless you add your own tasks.**

Confirm with your Copilot org/enterprise admin:

- [ ] **Copilot CLI is enabled** in your org's Copilot policy.
- [ ] **The models you want are enabled** for your org (Settings → Copilot → Models). As of
      2026-09-23 the example uses: *MAI-Code-1.1-Flash*, *GPT-5.6 Terra*, *Gemini 3.8 Flash*,
      *Claude Sonnet 5*.
- [ ] **Budget.** Your plan bills AI Credits (1 credit = $0.01). A first pilot (8 contenders ×
      6 tasks × 1 repeat = 48 runs) is the thing to budget for; see step 8 to estimate the full run.
- [ ] Docker Desktop is allowed on your laptop (and licensed, if your company needs a paid
      Docker subscription).

## 1. Install prerequisites (once)

- [ ] **WSL 2 with Ubuntu**: in PowerShell, `wsl --install -d Ubuntu`, reboot, create a user.
- [ ] **Docker Desktop**: Settings → General → *Use the WSL 2 based engine* ✓; Settings →
      Resources → WSL integration → enable **Ubuntu**.
- [ ] Docker Desktop → Settings → Resources: at least **8 GB memory**, 4+ CPUs.
- [ ] In Windows power settings, stop the laptop from sleeping while plugged in (batches run for
      hours).

Check, in an **Ubuntu (WSL)** terminal:

```bash
docker version        # shows both Client and Server
```

If "Cannot connect to the Docker daemon": Docker Desktop isn't running, or WSL integration for
Ubuntu is off.

## 2. Corporate network (skip if you're not behind a proxy)

If your company uses a web proxy or inspects TLS, add these to `~/.bashrc` in WSL and open a new
terminal. Ask IT for the values and the root CA file.

```bash
export HTTPS_PROXY=http://proxy.example.corp:8080
export HTTP_PROXY=$HTTPS_PROXY
export NO_PROXY=localhost,127.0.0.1
export BENCHY_CA_BUNDLE=$HOME/corp-root-ca.pem     # PEM file of the company root CA
```

Docker Desktop itself may also need the proxy (Settings → Resources → Proxies) so that
`./bench build` can download base images.

## 3. Get the code

```bash
cd ~                                   # inside WSL, NOT /mnt/c/...
git clone https://github.com/nocodejim/benchy.git
cd benchy
./bench doctor
```

Expected: engine version, "image missing" for both images (normal for now), "no stored logins
yet", "create contenders.yaml from contenders.example.yaml".

If `git clone` is blocked by the network: download the repo as a ZIP from GitHub in the browser,
then in WSL `unzip /mnt/c/Users/<you>/Downloads/benchy-main.zip -d ~ && mv ~/benchy-main ~/benchy`
and run `chmod +x ~/benchy/bench`.

## 4. Build and self-test (no AI, no cost)

```bash
./bench build         # ~5-10 min the first time
./bench test          # expect: 77 passed
./bench selftest      # expect, at the end: "[selftest] N runs checked, 0 problem(s)"
```

The self-test needs internet access to github.com and PyPI (it clones microblog and installs its
dependencies), but it never calls an AI model.

If it fails:

| Message | Fix |
|---|---|
| `build` fails downloading | Proxy (step 2); make sure Docker Desktop's proxy is set too. |
| `setup failed` / `dependency install failed` | Proxy or CA bundle not reaching the containers: check step 2, then `rm -rf out/cache` and retry. |
| `certificate verify failed` | `BENCHY_CA_BUNDLE` missing or wrong file. |
| `golden solution did not pass` for `gha-ci-add` `real-shas` | github.com not reachable during setup. |

**Do not continue until the self-test shows 0 problems.** Everything after this costs money.

## 5. Sign in to Copilot (device code, no PAT)

```bash
./bench login copilot
```

It prints a URL (`https://github.com/login/device`) and an 8-character code. Open the URL in your
normal Windows browser, sign in with your work GitHub account (SSO), enter the code, approve.
Expected at the end: `copilot login stored in Docker volume 'benchy-auth'`.

`./bench doctor` should now say `login stored: copilot`.

## 6. Confirm the exact model IDs (the one step benchy can't do for you)

GitHub's documentation lists models by display name (e.g. "MAI-Code-1.1-Flash"). The CLI needs
the ID, which is usually the same name in lowercase (`mai-code-1.1-flash`). Check it:

```bash
docker run --rm -it --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
  --tmpfs /tmp:rw,exec -v benchy-auth:/auth:ro benchy-agent:local \
  bash -c 'mkdir -p /tmp/ch && cp -r /auth/copilot/. /tmp/ch/ && COPILOT_HOME=/tmp/ch copilot'
```

In the Copilot screen that opens, type `/model` and press Enter. For each of the four models,
write down:

| Vendor | Model (display) | ID shown in `/model` | Thinking levels offered |
|---|---|---|---|
| Microsoft | MAI-Code-1.1-Flash | | |
| OpenAI | GPT-5.6 Terra | | |
| Google | Gemini 3.8 Flash | | |
| Anthropic | Claude Sonnet 5 | | |

Exit with `/exit` (or Ctrl+C twice). Nothing is billed for opening the picker.

If a model is **missing** from the picker, it isn't enabled for your org (go back to your admin)
or your plan doesn't include it. If the picker doesn't show IDs, use the one-run test in step 7:
it reports the ID Copilot actually used.

## 7. Create `contenders.yaml` and smoke-test it (small cost)

```bash
cp contenders.example.yaml contenders.yaml
nano contenders.yaml         # or: code contenders.yaml  (VS Code with the WSL extension)
```

- Replace each `model:` with the ID from step 6 if it's different.
- Each `effort:` must be a level that model offers. Allowed values: `none`, `minimal`, `low`,
  `medium`, `high`, `xhigh`, `max`.
- `name:` is just the label in the report.

Then run **one cheap task once per contender**:

```bash
./bench run --tasks gha-ci-add --repeats 1
```

Check the result for each contender:

```bash
for f in out/runs/*gha-ci-add*/metrics.json; do
  jq -r '[.contender, .outcome.exit_status, .model_requested, (.models_reported|join(",")), .cost.ai_credits, (.warnings|join(" | "))] | @tsv' "$f"
done
```

`jq` is not always installed in WSL; if it's missing, run the loop inside the grader image
instead: `./bench shell grader`, then `cd /out` and run the same loop with `runs/…` paths.

For each contender, expect:

- `exit_status` = `ok` (or a normal failure). **`error` on every run** means login, policy or
  a wrong model ID: read `out/runs/<id>/raw/stderr.txt`.
- `models_reported` matches `model_requested`. If not, fix the ID.
- `ai_credits` is a number. If it's empty or there are warnings like `no Copilot usage artifacts
  found` or `token totals disagree`, see step 10.

Open `out/report/latest.html` from WSL with
`explorer.exe "$(wslpath -w out/report/latest.html)"` and look it over.

## 8. Estimate the cost of the real batch

From the smoke-test report, read **Total cost** per contender. That was 1 task × 1 repeat. For
the full starter suite:

    estimated cost ≈ (smoke-test total for all contenders) × 6 tasks × repeats × 1.5

(The ×1.5 is headroom: other tasks are bigger than `gha-ci-add`, and failed runs often cost more.)
A better estimate is to run the full pilot first, `./bench run --repeats 1`, and multiply its
total by the number of repeats you want.

Optional safety cap per run: add `max_ai_credits: 300` to **every** contender (minimum 30). It
changes how agents behave, so use it for all contenders or none.

## 9. Run the comparison

```bash
tmux new -s bench            # keeps running if the terminal closes; reattach: tmux attach -t bench
./bench run --repeats 3
```

Time: roughly (number of runs) × (a few minutes). 144 runs is most of a working day. Keep the
laptop awake and on the network (VPN drops will show up as harness errors).

When it finishes, the report is at `out/report/latest.html`, with `summary.png` (for slides),
`summary.md` (for a wiki) and `results.csv` (for Excel) in `out/report/<batch>/`.

To rebuild a report later: `./bench report` (latest batch) or `./bench report --batch <id>`.

## 10. First real run: sanity checks (do this once)

benchy's Copilot usage parsers have been tested against sample files, not yet against a real
run of this Copilot CLI version. Before sharing results, spend 10 minutes on:

- [ ] Open two or three `out/runs/<id>/metrics.json` files. `sources` should show where each
      number came from (ideally `usage.json` for tokens and credits). `warnings` should be empty
      or harmless.
- [ ] Compare the batch's total cost in the report with **GitHub → your org → Settings →
      Billing → Copilot usage** for the same day. They should be close.
- [ ] Read one `raw/transcript.md` and one `diff.html` to see that the agent really did the work.

If credits or tokens are empty for every run, the report's resolve rate, time and per-task
results are still valid; only the cost columns are affected. Save one run's `raw/` folder (it is
redacted, but check it for anything internal) so the parser can be fixed later.

## 11. Sharing the results

- Share `summary.png` and the per-task table, with the batch date and the Copilot CLI version
  (shown in the report's *Environment* section).
- For non-technical readers, send [overview-for-leaders.md](overview-for-leaders.md) alongside.
- Remember the limits: 6 tasks on one small app is a first signal, not a verdict. Differences
  within the min–max ranges are noise.

## 12. Clean up

```bash
./bench logout               # deletes the stored Copilot token from Docker
```

Then revoke it on GitHub: Settings → Applications → Authorized OAuth Apps → GitHub Copilot CLI.
`out/` holds all results; delete it when you no longer need them (`rm -rf out`).

## Quick reference

| I want to… | Command |
|---|---|
| Check my setup | `./bench doctor` |
| Run a subset | `./bench run --tasks gha-ci-add,rancher-deploy --repeats 3` |
| Give slow models more time (for everyone) | `./bench run --timeout-scale 1.5` |
| Keep the agent's working folder | `./bench run --keep-workspaces` |
| Look at an agent's work as a git branch | `git clone out/repos/microblog.git /tmp/mb && git -C /tmp/mb log --oneline --all` |
| Add a model | add a line to `contenders.yaml`; if its cost shows "—", add its rates to `pricing.yaml` from GitHub's [models and pricing](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing) page |
| Add a task for my team's stack | [user-manual.md §9](user-manual.md#9-adding-a-task-for-a-new-stack) |
