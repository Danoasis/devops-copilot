# Azure DevOps service connection expired / pipeline auth failures

**Category:** ci_cd | **Severity:** high | **Id:** KB-008

## Symptoms

Previously green pipeline stages fail on Azure tasks with errors like
`AADSTS7000222: The provided client secret keys are expired`, `Failed to obtain the JWT`, or
`The service connection ... could not be found or is not authorized`. Terraform/az steps fail
to log in while unit-test stages still pass.

## Diagnosis

1. Identify the service connection used by the failing task (pipeline YAML
   `azureSubscription:` input) → Project Settings → Service connections.
2. Service connections backed by an App Registration use a client secret with an expiry
   (default 6–24 months). Check the app's Certificates & secrets blade for expired secrets.
3. Also check authorization: a connection restricted to specific pipelines will fail for a
   new pipeline until granted ("not authorized" rather than "expired").

## Resolution

- Secret-based: create a new client secret on the App Registration, then edit the service
  connection → update the secret → Verify. Or use the "Convert" flow.
- Strongly preferred fix: convert the connection to **Workload Identity Federation** — no
  secret at all; Azure trusts tokens issued by Azure DevOps via OIDC. Nothing to expire or
  rotate, and it removes a credential from the estate.
- For "not authorized": open the connection → Security → grant the pipeline, or (carefully)
  allow all pipelines for non-production connections.

## Prevention

Adopt workload identity federation for all Azure connections; where secrets remain, alert 30
days before expiry and record owners for every service connection.
