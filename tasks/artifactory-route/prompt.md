## SEC-219: route all dependency downloads through Artifactory

Company policy: builds may not download from the public internet directly. Everything goes through
our Artifactory instance at `https://artifactory.example.com`:

| What | Artifactory repository |
|---|---|
| Docker base images (Docker Hub remote) | `artifactory.example.com/docker-remote/...` (Docker Hub path, e.g. `library/python`) |
| Python packages (PyPI virtual) | `https://artifactory.example.com/artifactory/api/pypi/pypi-virtual/simple` |
| Our built images (local) | `artifactory.example.com/docker-local/microblog` |

Do the following:

1. Update the `Dockerfile` so the base image is pulled through `docker-remote` and `pip` installs
   from the PyPI virtual repository. Artifactory requires authentication: the credentials must
   **not** end up in the image (no `ARG`/`ENV` holding credentials, nothing baked into a layer);
   use a BuildKit build secret.
2. Add a GitHub Actions workflow that, on pushes to `main`, logs in to Artifactory, builds the
   image (passing the pip credentials as a build secret) and pushes it to `docker-local` tagged
   with the commit SHA. Credentials are stored in the repository secrets `ARTIFACTORY_USER` and
   `ARTIFACTORY_TOKEN`. Keep the workflow token read-only and pin actions to commit SHAs.

Never write a real or example credential value into any file. `actionlint` must pass.
