# Terraform apply fails: state blob is locked / leased

**Category:** infrastructure | **Severity:** medium | **Id:** KB-005

## Symptoms

`terraform plan` or `apply` fails with `Error acquiring the state lock` /
`state blob is already locked` (azurerm backend: the blob has an active lease). Often appears
after a CI job was cancelled mid-apply or two pipelines ran concurrently.

## Diagnosis

1. The lock is a feature: it prevents two writers from corrupting state. First question is
   always "is another apply legitimately running right now?" Check running pipeline jobs and
   teammates before touching anything.
2. Read the lock info in the error: it includes the lock ID, who created it, and when.
3. If the holder is a job that was cancelled/crashed, the lease was orphaned.

## Resolution

- Preferred: `terraform force-unlock <LOCK_ID>` from the same working directory/backend
  config. It refuses if the ID doesn't match — that safety check is the point.
- Azure-specific fallback: break the blob lease on the state file container
  (Storage account → container → state blob → Break lease, or
  `az storage blob lease break`).
- NEVER delete or hand-edit the state blob. If state is genuinely damaged, restore the
  previous blob version (enable blob versioning on the state storage account).

## Prevention

Serialize applies in CI (one environment = one pipeline concurrency group), always let
`apply` finish or fail cleanly, enable blob versioning + soft delete on the state account.
