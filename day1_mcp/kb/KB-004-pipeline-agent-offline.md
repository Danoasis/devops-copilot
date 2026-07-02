# Azure DevOps pipeline stuck: self-hosted agent offline

**Category:** ci_cd | **Severity:** medium | **Id:** KB-004

## Symptoms

Pipeline run sits in "Queued" forever with the message
`The agent request is not running because all potential agents are running other requests or
are offline`. Jobs targeting a self-hosted pool never start; Microsoft-hosted pools are fine.

## Diagnosis

1. In Azure DevOps: Project Settings → Agent pools → select the pool → Agents tab. Check the
   agent's status (Online/Offline) and last activity.
2. On the agent machine, check the agent service/process:
   - Linux: `systemctl status vsts.agent.*` or look for the `Agent.Listener` process; logs in
     `_diag/` inside the agent directory.
   - The agent maintains an outbound HTTPS long-poll to dev.azure.com — it needs no inbound
     ports, but egress to `https://dev.azure.com` and `*.visualstudio.com` must be open.
3. Common causes: machine rebooted and the agent was run interactively (not as a service),
   expired PAT used at registration, or corporate proxy/VPN changes breaking egress.
4. Check "capabilities & demands": a job demanding a capability (e.g. `docker`) that the agent
   does not advertise will also queue forever even with the agent online.

## Resolution

- Restart the agent: `./svc.sh restart` (Linux service install) or re-run `./run.sh`.
- If the PAT expired, reconfigure: `./config.sh remove` then `./config.sh` with a fresh PAT
  scoped to Agent Pools (Read & manage).
- Install as a service so it survives reboots: `./svc.sh install && ./svc.sh start`.
- For demand mismatches, install the missing tool on the agent or drop the demand.

## Prevention

Run agents as services, monitor pool online-count with an alert, and document PAT rotation.
