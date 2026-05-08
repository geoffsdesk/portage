# Runbook 01 — Discovery & Assessment

This is the human-readable companion to `portage-orchestrator` Phase 1. Use this when you want to drive discovery yourself rather than letting the agent run end-to-end.

## Goal

Produce `inventory.json`, `readiness-report.md`, and `blockers.md`. Walk away knowing exactly what's in your EKS estate and how hard the migration will be.

## Pre-flight

- Read-only AWS credentials in scope (see `eks-discovery` SKILL for the exact IAM permissions).
- `aws`, `kubectl`, `jq`, `yq` installed.
- A run directory: `mkdir -p portage-output/$(date +%F)-discovery`.

## Execute

1. **Kick off discovery.**

   In the agent: "Use the eks-discovery skill against AWS account 123456789012 in regions us-east-1, us-west-2. Output to ./portage-output/2026-05-06-discovery/."

   The agent walks every cluster, captures inventories, builds `inventory.json`, and writes raw evidence under `01-discovery/raw/`.

   Time: 30 min – 4 h depending on estate size.

2. **Spot-check the inventory.**

   ```bash
   jq '.clusters | length' inventory.json
   jq '[.clusters[].workloads.namespaces[].deployments] | add' inventory.json
   jq '.clusters[].workloads.host_network' inventory.json   # any flagged?
   jq '.clusters[].workloads.irsa_bindings | length' inventory.json
   ```

   Confirm the numbers match your expectation. If any are surprisingly low, the discovery scope was probably wrong.

3. **Read the escalations.**

   ```bash
   cat 01-discovery/escalations.md
   ```

   Each line is a hard problem the agent flagged. Triage now — most can be answered in minutes by the original team.

4. **Run the assessment.**

   "Use the migration-assessment skill against the discovery output in ./portage-output/.../01-discovery/."

   The agent scores every workload, identifies blockers, computes effort, and writes `02-assessment/readiness-report.md`.

5. **Read the report.**

   Skim Section 1 (executive summary) and Section 4 (blockers). If the overall grade is `blocked` or `high-risk`, **stop**. Don't proceed to Phase 2 until blockers have an owner and a target close date.

   If `tractable` or `ready`, continue.

6. **Confirm scope and constraints.**

   Section 8 of the report has open questions for you. Answer them in `00-orchestrator-state.json`:

   - Compliance regimes
   - Cost ceiling
   - Cutover strategy preference
   - Co-existence period
   - Identity provider
   - Tier-0 list

## Exit gate

- [ ] `inventory.json` exists with > 0 clusters and > 0 workloads.
- [ ] `readiness-report.md` overall grade is `tractable` or better.
- [ ] All blockers have owner + close date.
- [ ] Open questions answered in orchestrator state.

When all four ticked, proceed to `runbooks/02-landing-zone.md`.
