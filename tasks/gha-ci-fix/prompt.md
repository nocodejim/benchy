## REL-77: tag releases stopped publishing images

Pushing a version tag (for example `v1.4.0`) used to build and publish the container image to
GHCR through `.github/workflows/release.yml`. It is broken:

- `actionlint` reports errors in the workflow.
- The `publish` job either doesn't run or pushes an image with an empty tag.
- When it did run last time, the push failed with
  `denied: permission_denied: write_package`.

Fix the workflow so that pushing a `v*` tag runs the tests in `build`, then `publish` pushes
`ghcr.io/<owner>/<repo>:<version>` where `<version>` is the tag without the leading `v`.

Constraints: keep the job names `build` and `publish`, keep the tag trigger, keep the workflow token
read-only except for what `publish` strictly needs, keep actions pinned to commit SHAs, and make
`actionlint` pass with no findings.
