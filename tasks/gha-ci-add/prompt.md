## PLAT-318: add CI for microblog

This service has no continuous integration. Add a GitHub Actions workflow at
`.github/workflows/ci.yml` that follows our platform standards:

- Runs on pull requests targeting `main` and on pushes to `main`.
- Uses Python 3.12, installs `requirements.txt`, and runs the unit tests
  (`python -m unittest tests`).
- Caches pip downloads between runs.
- Least privilege: the workflow token is read-only (`contents: read`).
- Every third-party action is pinned to a full-length commit SHA of a released
  version (put the version in a trailing comment), per our supply-chain policy.
- A newer push to the same PR cancels the in-progress run, and every job has a timeout.

The workflow must pass `actionlint` with no findings.
