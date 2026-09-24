# Third-party software

benchy's own code is MIT licensed. The container images it builds download and run the
following tools as separate programs (nothing below is vendored into this repository):

| Component | License | Used in |
|---|---|---|
| GitHub Copilot CLI (`@github/copilot`) | GitHub terms of service | agent image |
| Claude Code (`@anthropic-ai/claude-code`) | Anthropic commercial terms | agent image |
| Node.js | MIT | both images |
| Playwright + Chromium | Apache-2.0 / BSD-3-Clause | grader image |
| diff2html-cli | MIT | grader image |
| actionlint | MIT | both images |
| hadolint | GPL-3.0 | both images (invoked as a separate binary) |
| ShellCheck | GPL-3.0 | both images (invoked as a separate binary) |
| yamllint | GPL-3.0 | both images (invoked as a separate binary) |
| kubeconform | Apache-2.0 | both images |
| Helm | Apache-2.0 | both images |
| gitleaks | MIT | grader image |
| JFrog CLI (`jf`) | Apache-2.0 | both images |
| Kubernetes JSON schemas (yannh/kubernetes-json-schema) | derived from Kubernetes OpenAPI, Apache-2.0 | grader image |
| Compose specification schema | Apache-2.0 | grader image |
| PyYAML, Jinja2, jsonschema, pytest | MIT / BSD-3-Clause | grader image |

The default benchmark target, [miguelgrinberg/microblog](https://github.com/miguelgrinberg/microblog),
is MIT licensed and is cloned at run time; it is not redistributed here. The small patches
under `repos/` and `tasks/` that modify it are part of benchy (MIT).

If you publish the built images, the GPL-3.0 tools come along as unmodified binaries; include
their license texts and source pointers alongside the image.
