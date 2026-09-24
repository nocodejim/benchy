## PLAT-455: deploy microblog to our Rancher-managed clusters

We deploy with Rancher Fleet (GitOps). Create:

1. A Helm chart at `deploy/helm/microblog` for the web app (container port 5000):
   - `Deployment`, `Service` (port 80 → the app) and `Ingress` (`networking.k8s.io/v1`, host and
     ingress class configurable through values).
   - Image repository and tag configurable through values.
   - CPU and memory requests **and** limits.
   - Readiness and liveness probes.
   - Hardened security context: run as non-root, no privilege escalation, read-only root
     filesystem, drop all capabilities.
   - `DATABASE_URL` and `SECRET_KEY` come from an existing Kubernetes Secret (name configurable);
     the chart must not create a Secret with data or put these values in plain text.
2. A Fleet bundle at `deploy/fleet.yaml` that deploys the chart into the `microblog` namespace on
   clusters labelled `env: staging` and `env: production`, with 3 replicas in production.

There is no cluster here: the chart must pass `helm lint` and its rendered output must validate
with `kubeconform -strict`.
