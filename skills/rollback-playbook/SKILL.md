---
name: rollback-playbook
description: Roll back a workload from GKE to EKS when a cutover gate breaches or when a regression is found. Reverses traffic shifts, repoints data writers if applicable, restores config, captures evidence, and produces a postmortem-ready timeline. Use when a traffic-cutover gate trips, when "rollback service X to EKS", or when an incident requires returning traffic to the source.
---

# Rollback Playbook

You execute the reverse of a cutover safely and with evidence. Bring traffic back to EKS, restore data direction (if applicable), and produce a postmortem-ready timeline.

## Purpose

Provide a tested, fast, evidenced way to undo a cutover step (or the whole cutover) without making the situation worse. Rollback is a *first-class* operation, not a fire drill.

## When to use this skill

- A `traffic-cutover` gate trips or auto-rollback fires.
- The user identifies a regression after cutover and asks to roll back.
- A higher-tier dependency rolls back, and downstream workloads must follow.

Do NOT use to "delete the EKS cluster after rollback". That's `post-migration-ops` only after a stable, soaked GKE state.

## Prerequisites

- The EKS source still exists, with replicas > 0 (or scalable to > 0). Default cutover practice is to scale-to-zero, not delete, exactly to support this.
- The source data system still exists and is in read-write or rapidly switchable state per the data-migration plan.
- The DNS / routing layer is reversible by the same mechanism that did the cutover.

## Procedure

### Step 1 — Stop the bleed (within seconds)

If a gate auto-fires:

1. The cutover script aborts at its current step.
2. The DNS / routing weight that just changed is reverted to the previous step (e.g., 50% → 10%).
3. If the gate is *backend health* level (not just SLO drift), revert to **0% on GKE** immediately.

If a human invokes rollback:

```bash
# DNS-level immediate revert to 100% EKS
gcloud dns record-sets transaction start --zone=example-com
gcloud dns record-sets transaction remove api.example.com. --zone=example-com --type=A --ttl=60 || true
gcloud dns record-sets transaction add \
  --zone=example-com --name=api.example.com. --ttl=60 --type=A \
  --routing-policy-type=WRR \
  --routing-policy-data="100=$EKS_AS_IP;0=$GKE_TARGET"
gcloud dns record-sets transaction execute --zone=example-com

date "+%FT%TZ" >> $RUN_DIR/rollback.log
echo "Routing reverted to 100% EKS" >> $RUN_DIR/rollback.log
```

For a service-mesh routing rollback, set the `VirtualService` weights to (100, 0). For an L7-proxy front, push the previous config and reload.

### Step 2 — Capacity check on EKS side

```bash
kubectl --context eks -n <ns> get hpa
kubectl --context eks -n <ns> get deploy
# If replicas were scaled to 0, scale back up to the pre-cutover count.
kubectl --context eks -n <ns> scale deploy/<name> --replicas=<n>
kubectl --context eks rollout status deploy/<name>
```

If EKS was decommissioned beyond the rollback window: this skill cannot help. Open a P1 incident.

### Step 3 — Data direction

For workloads whose data system was already cut over:

- If the source data system is still read-write and synchronized (within the planned soak window): repoint app config to source DSN. Confirm replica direction is now reversed (target → source) or that the source is authoritative again.
- If the source is read-only: the rollback is *bounded* — the GKE-side writes since cutover will be lost on reversal. Surface this *before* executing the data-direction rollback. Do not silently lose writes.

For most workloads in the standard plan, the source is kept in read-only mode for a 14-day cool-down — meaning a rollback within that window incurs the loss of GKE-side writes. The rollback playbook makes this explicit and asks for confirmation.

### Step 4 — Identity rollback

The KSA → GSA bindings stay in place; they are no-ops on EKS. The IRSA bindings on the source remain live during the cool-down period exactly to support this.

If WI federation back to AWS was set up (cross-cloud federation in `identity-translation`), no change needed.

### Step 5 — Capture evidence

Within 30 minutes of rollback, capture:

- Cloud Monitoring screenshots of the SLO breach window.
- Cloud Logging slice of error log entries for the affected workload.
- The `traffic-cutover` execution log up to the rollback point.
- Output of the failing gate's check (`check-gates.sh` last invocation).
- Sample request traces showing the regression behavior.

Write to `<run-dir>/11-cutover/<workload>/rollback-evidence/`.

### Step 6 — Generate the postmortem template

Render `<run-dir>/11-cutover/<workload>/postmortem.md` from `templates/postmortem-template.md`, populated with:

- Timeline (from execution.log + rollback.log).
- Trigger (which gate, what value, what threshold).
- Action (rollback, when, by whom).
- Impact (estimated request loss / latency excess; user-facing minutes if applicable).
- Hypotheses for the regression (the agent emits 2–3; the human picks).

### Step 7 — Plan the next attempt

Do not silently retry. After a rollback:

1. The orchestrator marks the workload's cutover as `rolled-back` with timestamp.
2. The hypotheses must be addressed (load test, code change, config change) before re-attempting.
3. The next attempt requires explicit user confirmation and a written summary of what changed since the failed attempt.

## Decision points

| Decision                                | Default                       | When to deviate                       |
|-----------------------------------------|-------------------------------|---------------------------------------|
| Auto-revert vs pause-and-ask            | Auto-revert on backend-health gates; pause on SLO gates | All-pause if explicit user preference |
| Snap to 0% on GKE vs revert one step    | One step; full revert only on hard health failure | Full revert always for tier-0 |
| Capture evidence first vs revert first  | Revert first; evidence within 30 min | Capture-first only when revert would erase the evidence |
| Soft-revert (keep GKE up) vs scale-down | Keep GKE up; just don't route | Scale-down only after 24h of confirmed rollback |

## Outputs / Deliverables

```
11-cutover/<workload>/
├── rollback.log
├── rollback-evidence/
│   ├── monitoring-screenshots/
│   ├── log-slice.json
│   ├── traces/
│   └── gate-output.txt
├── postmortem.md
└── next-attempt-plan.md
```

## Validation

After rollback, the agent confirms:

- `kubectl get httproute / kubectl get virtualservice` shows the reverted weights.
- DNS query (`dig +short`) returns only EKS endpoints (or the configured weights).
- EKS replica health: pods Ready, error rate baseline.
- SLO returns to baseline within the next observation window.
- Postmortem template is filled in (no `TBD` in trigger / impact / next attempt).

## Escalation triggers

- Rollback executed but SLO does not recover within 15 minutes — there is a broader issue beyond the cutover; escalate to incident response, do not retry.
- Source EKS state has degraded beyond rollback (replica count truly zero with no scale-out path, decommissioning started). Surface immediately; this is an incident.
- Rollback would erase data writes that affect another workload's correctness. Do not auto-execute; require explicit user instruction.

## Common pitfalls

- **Rolling back without evidence.** The next attempt will fail the same way. Capture before retrying.
- **Forgetting that rollback != fix.** Rollback restores state; it doesn't fix the root cause. The orchestrator tracks both.
- **Not surfacing data loss.** A rollback after writes have happened on GKE *loses those writes* unless replication was bidirectional. State this in plain English before executing.
- **Re-attempting the same cutover with the same plan.** Don't. Address the hypothesis, document the change, and require sign-off.
- **Treating rollback as a failure.** It's not. It's a sign the gates worked.

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [SRE Workbook — Postmortem Culture](https://sre.google/workbook/postmortem-culture/).
- [SRE Workbook — Reliable Product Launches](https://sre.google/workbook/reliable-product-launches/).
- [traffic-cutover](../traffic-cutover/SKILL.md) — defines gates and ramp.
- [data-migration](../data-migration/SKILL.md) — defines source-vs-target data direction.
- [templates/postmortem-template.md](../../templates/postmortem-template.md)
