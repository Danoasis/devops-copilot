# ImagePullBackOff / ErrImagePull

**Category:** kubernetes | **Severity:** high | **Id:** KB-002

## Symptoms

Pod STATUS shows `ErrImagePull` then `ImagePullBackOff`. The container never starts.
`kubectl describe pod <pod>` shows events like `Failed to pull image "...": not found` or
`unauthorized: authentication required`.

## Diagnosis

1. `kubectl describe pod <pod>` and read the exact Failed event message — it names the image
   reference and the reason.
2. Three root causes cover nearly every case:
   - **Typo / nonexistent tag**: the image tag was never pushed (e.g. `nginx:1.99-nonexistent`).
     Verify with `docker pull <image:tag>` or check the registry UI.
   - **Auth failure**: private registry (e.g. ACR) without an imagePullSecret, or an expired
     service principal / token. Event says `unauthorized` or `403`.
   - **Registry unreachable**: DNS or egress problem from the node; event shows i/o timeout.
3. In local kind clusters, images built on the host are NOT visible to the cluster unless
   loaded explicitly: `kind load docker-image <image:tag>`.

## Resolution

- Fix the tag in the Deployment (prefer immutable tags: the git commit SHA, never `latest`)
  and `kubectl apply`. The kubelet retries automatically once the reference is pullable.
- Auth: create/rotate the pull secret:
  `kubectl create secret docker-registry regcred --docker-server=... --docker-username=...`
  and reference it under `spec.imagePullSecrets`. For AKS+ACR prefer the managed identity
  AcrPull role assignment instead of secrets.
- kind: run `kind load docker-image <image:tag>` (our CI pipeline does this in the CD stage).

## Prevention

CI publishes the image before manifests reference it; deployments only reference SHA tags that
CI produced; registry credentials owned by workload identity, not long-lived secrets.
