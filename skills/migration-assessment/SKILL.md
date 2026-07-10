---
name: migration-assessment
description: Score an EKS estate's readiness for migration to GKE and produce a graded readiness report with named blockers, risk ratings per workload, a phased migration plan, and a costed effort estimate. Consumes the inventory.json produced by eks-discovery. Use after discovery to answer "is this ready to migrate?", "what will it take?", "what blocks us?", "what's our migration plan?".
---

# Migration Assessment

You are a migration architect. Read the discovery inventory and produce a graded, opinionated readiness report. Your output is the document a PSO consultant would have written after week 1.

## Purpose

Convert raw inventory into a decision-ready document: scorecard, blockers, per-workload risk, phased plan, effort estimate.

## When to use this skill

- Immediately after `eks-discovery`.
- When the user asks "are we ready to migrate?" or "what's blocking the migration?".
- When the user wants an effort estimate before committing budget.
- To produce a board-ready summary slide of migration risk.

## Prerequisites

- `01-discovery/inventory.json` exists.
- The orchestrator's `00-orchestrator-state.json` contains the user's constraints (compliance, SLOs, window, cost ceiling).

## Procedure

### Step 1 — Load inputs

Read `inventory.json` and `00-orchestrator-state.json`. Build an in-memory model: clusters → namespaces → workloads → dependencies.

### Step 2 — Score each workload

For each workload, score on four axes (0–3 where 3 = lowest risk):

| Axis                    | 3 (low risk)                                | 2                                          | 1                                          | 0 (blocker)                                  |
|-------------------------|---------------------------------------------|--------------------------------------------|--------------------------------------------|----------------------------------------------|
| **Stateless-ness**      | Pure stateless                              | Stateless + non-PVC config                 | Has PVC, not RWX                           | Has RWX PVC or local hostPath                |
| **Identity portability**| No IRSA / generic SA                        | IRSA with policy fully covered by GCP IAM  | IRSA with one IAM gap                      | IRSA touches AWS-only services (KMS, STS heavily) |
| **Network portability** | ClusterIP only                              | Service of type LoadBalancer (NLB)         | Ingress via ALB                            | Uses VPC CNI features (ENI per pod), hostNetwork, custom CNI |
| **Data dependencies**   | None                                        | Same-region GCP data sink possible (Cloud SQL homogeneous) | Heterogeneous data sink (DynamoDB, Aurora) | On-prem-pinned dep, or cross-account RDS without replica path |

Composite score = sum / 12. Buckets:
- **Ready** (>= 0.75): low risk, fits standard pattern.
- **Tractable** (0.50–0.74): translatable with explicit plan, no rewrite.
- **High-risk** (0.25–0.49): plan + dry-run + extra validation; consider re-platforming sub-components.
- **Blocked** (< 0.25): cannot be migrated as-is; needs design work or stays on EKS / re-platforms.

### Step 3 — Cluster-level scoring

Aggregate workload scores per cluster, plus add cluster-level signals:

- Control plane version drift from latest GKE-supported (e.g., EKS 1.27 → GKE supports up to 1.31, no drift; EKS 1.24 → drift, plan a K8s version bump pre- or post-migration).
- Number of custom CRDs / operators in use (more = more translation work).
- Number of platform-level DaemonSets (more = more parallel translation).
- Whether the cluster authentication mode is `CONFIG_MAP` (legacy) — needs `aws-auth` translation to GKE IAM.
- Whether secrets-at-rest encryption is enabled and which KMS key — required for GKE parity.

### Step 4 — Identify blockers

Walk the inventory's `escalations.md` and the workload scoring. Categorize blockers:

| Blocker                                               | Resolution path                                         |
|-------------------------------------------------------|---------------------------------------------------------|
| Custom CNI (non-VPC-CNI) in production use            | Decide GKE CNI: Dataplane V2 default; Cilium-on-GKE if you need eBPF API parity. Plan migration test. |
| `hostNetwork: true` workloads outside known catalog   | Reproduce on GKE with same node-host tolerations; many will work, validate via canary. |
| RWX PVC not on EFS                                    | Identify backing CSI; map to Filestore Enterprise or NetApp Volumes. |
| Karpenter custom NodePools with provisioner-specific taints | Rebuild as GKE node pools or NAP rules; capture taints and labels. |
| App Mesh in use                                       | Re-platform to Anthos Service Mesh (managed Istio). Non-trivial. |
| SDK calls to AWS-only services (DynamoDB, Kinesis, …) | Either keep service in AWS during co-existence (with cross-cloud connectivity) or re-platform to GCP equivalent. |
| Cross-account ECR pulls                               | Plan dual-tag strategy or pull-through cache during co-existence. |
| Federated SSO via AWS IAM Identity Center             | Target Workforce Identity Federation; produce identity-provider plan. |
| Compliance scope (FedRAMP, HIPAA, PCI)                | Verify GCP service mappings are in scope; flag any outliers. |

### Step 5 — Effort estimate

For each cluster, compute effort using:

| Driver                                | Cost (engineer-days) |
|---------------------------------------|----------------------|
| Per workload, **Ready** bucket         | 0.5                  |
| Per workload, **Tractable** bucket     | 1.5                  |
| Per workload, **High-risk** bucket     | 4                    |
| Per workload, **Blocked** bucket       | quote separately     |
| Per ALB / NLB                          | 0.5                  |
| Per IRSA role                          | 0.25                 |
| Per RWX PV                             | 1                    |
| Per RDS to Cloud SQL homogeneous move  | 2                    |
| Per Aurora → AlloyDB engine-change     | 8 (and quote)        |
| Cluster baseline (landing zone, fleet) | 5                    |

Multiply by an organizational coefficient (0.8 if the team has prior GKE experience; 1.5 if no GCP experience). Express as a range (P50 / P90).

### Step 6 — Phased plan

Produce a recommended phasing:

1. **Foundation** (week 1–2): landing zone, identity, network plumbing, observability stack, registry mirroring.
2. **Tier-2 first wave** (week 3–4): stateless tractable workloads. Build the muscle.
3. **Stateful + tier-1** (week 5–8): one workload at a time, with full validation.
4. **Tier-0** (week 9–10): final, slowest cutovers, extended soak.
5. **Decommission** (week 11–12): EKS teardown, post-mortem, FinOps tune.

Adjust to the user's stated window. If the user has 30 days, phases collapse and risks tighten — surface that.

### Step 7 — Risks & guardrails

For each named risk, propose a guardrail:

- "RDS → Cloud SQL replication lag during cutover" → guardrail: replication-lag SLO, pause if > 30s for 5 minutes.
- "Cross-cloud egress cost during co-existence" → guardrail: budget alert, traffic dashboard, capped co-existence period.
- "Workload Identity binding drift" → guardrail: CI check that compares IRSA → WI map to live state daily.
- "GKE cluster cost overrun vs EKS baseline" → guardrail: monthly FinOps review; auto-scaler tuning playbook.

### Step 8 — Compose the report

Render `02-assessment/readiness-report.md` from the [readiness-report template](../../templates/readiness-report.md). Sections, in order:

1. Executive summary (1 page, 5 bullets, 1 chart-able scorecard table).
2. Scope (what was discovered).
3. Scorecard (per cluster, per workload class).
4. Blockers (named, categorized, with resolution paths).
5. Phased plan (Gantt-shaped table).
6. Effort estimate (P50 / P90 range, org-coefficient assumption stated).
7. Risks & guardrails.
8. Open questions for the user.

Also render `02-assessment/blockers.md` — a self-contained checklist of every blocker with owner and target close date.

## Decision points

- **What counts as tier-0?** Default to whatever the user said in `00-orchestrator-state.json`; if not stated, infer by SLO and revenue impact and surface for confirmation.
- **Engine change vs lift-and-shift for data.** Default to homogeneous moves (RDS→Cloud SQL same engine). Engine change is escalation-only.
- **GKE Autopilot vs Standard at the cluster level.** Default Autopilot for clusters where >80% of workloads are stateless and within Autopilot's resource constraints; otherwise Standard. Explicitly recommend in the report.

## Outputs / Deliverables

```
02-assessment/
├── readiness-report.md   # The headline document.
├── blockers.md           # Checklist of every blocker.
├── scorecard.json        # Machine-readable per-workload scoring.
└── phased-plan.md        # Standalone phased plan; copy of the section in the report.
```

## Validation

- Every workload in `inventory.json` appears in `scorecard.json` exactly once.
- Every blocker has a resolution path. None is left as "TBD".
- Effort estimate range is sane (no $0 estimates, no >2-year estimates without explicit reasoning).
- Phased plan fits within the user's stated window; if it doesn't, the report says so on page 1.

## Escalation triggers

- The user's stated window is impossible at the P90 estimate. Escalate before continuing.
- Compliance scope includes a regime where GKE has a different feature set than EKS for an in-scope workload. Surface explicitly.
- Effort estimate shows >50% of workloads in the "High-risk" or "Blocked" buckets — recommend the user revisit scope.

## Common pitfalls

- **Hand-waving the effort estimate.** Don't say "a few weeks". Use the per-driver cost table. Defend your number.
- **Treating IRSA as a 1:1 to WI.** It usually is; the few that aren't are exactly the ones that bite. Score each role.
- **Underestimating data moves.** Heterogeneous data store changes are projects of their own. If the user wants to migrate the K8s fleet but keep AWS RDS, that's a valid choice; surface it.
- **Listing risks without guardrails.** A risk without a guardrail is a guess. Every risk gets a measurable guardrail.
- **At PB scale, plan multi-week shadow-reads.** For data systems above ~1 TiB with strict consistency requirements, plan dual-write + shadow-read for weeks before switching reads. See [LFF-02](../../reference/lessons-from-the-field.md#lff-02--sifts-petabyte-awsgcp-move-dual-wrote-and-shadow-read-for-weeks).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Migrate from Amazon EKS to GKE — Plan and build your foundation](https://docs.cloud.google.com/architecture/migrate-amazon-eks-to-gke) — Google's matching planning phase.
- [Landing zone design in Google Cloud](https://cloud.google.com/architecture/landing-zones) — informs phasing.
- [eks-discovery](../eks-discovery/SKILL.md) — produces the input.
- [templates/readiness-report.md](../../templates/readiness-report.md) — the output template.
- [docs/glossary.md](../../docs/glossary.md) — service map for translation feasibility.
