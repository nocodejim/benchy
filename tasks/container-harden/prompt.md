## PLAT-402: make the microblog image production-ready

Security review flagged our container setup. Update it to meet the platform container standard.
It must work for developers on Docker Desktop **and** Podman:

1. `Dockerfile`
   - Multi-stage build: dependencies are installed in a build stage; the runtime stage
     contains only what the app needs to run.
   - Base images are pinned to a specific version tag or digest (no floating `python:slim`/`latest`).
   - The container runs as a non-root user (use a numeric UID so Kubernetes `runAsNonRoot` can verify it).
   - A `HEALTHCHECK` is defined.
   - `hadolint --failure-threshold warning Dockerfile` passes.
2. `.dockerignore` keeps the build context clean and secret-free: at least `.git`, `.env`,
   `.venv` and `__pycache__` are excluded.
3. `compose.yaml` for local development runs the app with a PostgreSQL database:
   - valid against the Compose specification;
   - no passwords or secret keys written in the file (read them from the environment / a
     local `.env`, and provide a `.env.example` with placeholders);
   - the web service waits until the database is healthy before starting;
   - use fully-qualified image names (e.g. `docker.io/library/...`) so Podman doesn't prompt.

There is no container runtime in this environment, so validate statically.
