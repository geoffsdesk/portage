# Runbook 04 — Data Migration & Traffic Cutover

The Phase 4 runbook. Move data, then move traffic, with explicit gates at every step.

## Goal

End the phase with: every cohort cut over to GKE, every cutover at 100% with a green 24-hour soak, no open auto-rollbacks.

## Pre-flight

- Phase 3 complete (`03-translation.md`).
- Per-cohort runbooks generated under `11-cutover/per-workload-runbooks/`.
- For each stateful workload: data-migration plan reviewed; replication tooling provisioned; lag baseline established.
- Stakeholder comms: maintenance windows confirmed.

## Per-cohort execute

For each cohort (start with the lowest-tier or most-tested cohort):

1. **Data sync.**

   For each stateful system in the cohort:

   - "Use the data-migration skill to begin replication for `prod-payments-db`."
   - The agent surfaces the runbook. Confirm.
   - The agent kicks off DMS / pg_logical / STS / MM2 / equivalent.
   - Monitor `replication lag`, `error count`, `target health`. Do not proceed until lag < target SLA for ≥ 5 min.

2. **Pre-cutover smoke test.**

   On the GKE target (with traffic still 0%):

   ```bash
   kubectl -n payments rollout status deploy/payments-api
   curl -sS https://gke-only.payments.example.com/healthz | jq .
   ```

   Run the workload's own smoke test suite against the GKE-only hostname.

3. **Configure gates.**

   Open `11-cutover/gates/<workload>-gates.yaml`. Confirm thresholds match readiness-report values.

4. **Begin ramp.**

   "Use the traffic-cutover skill for `payments-api` with the default 1/10/50/100 ramp."

   The agent updates DNS (or mesh / proxy), polls metrics, soaks per spec, advances on green, pauses on yellow, rolls back on red.

5. **Monitor mid-ramp.**

   Watch the dashboards from `09-observability-translation/dashboards/` and the per-cutover view. The agent surfaces ramp progress every 15 min.

6. **At 100%, soak 24 h.**

   No new cutovers in this cohort during the soak window. Re-check gates at 1 h, 6 h, 24 h.

7. **Confirm final cutover.**

   - Update DNS to remove EKS targets.
   - Scale EKS Deployment to 0.
   - Mark `traffic-cutover` complete in orchestrator state.
   - Set source data system to read-only.

## If a gate trips

- Auto-rollback fires (backend health) → see `rollback-playbook`. Capture evidence within 30 min. Open postmortem.
- SLO gate trips → cutover pauses. Investigate. If fix is < 60 min, fix and resume; otherwise revert and reschedule.
- Two trips in a single cohort → stop the cohort; review with team before resuming.

## Exit gate

- [ ] Every cohort: 100% on GKE; 24-hour soak green.
- [ ] Source DNS records reverted (no traces of EKS targets).
- [ ] EKS Deployments scaled to 0.
- [ ] All replication paused or in read-only-from-source mode for the cool-down.
- [ ] No open auto-rollbacks; all postmortems closed or with action items dated.

Proceed to `runbooks/05-post-migration.md`.
