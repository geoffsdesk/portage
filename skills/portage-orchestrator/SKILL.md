---
name: portage-orchestrator
description: Run an end-to-end EKS to GKE migration program. Coordinates discovery, design, translation, cutover, and post-migration ops by sequencing the other Portage skills. Use when the user asks to "migrate from EKS to GKE", "plan an EKS→GKE migration", "replace our PSO engagement", or any holistic move of a Kubernetes estate from AWS to Google Cloud. Do NOT use for single-skill tasks (e.g., "translate this Helm chart") — call the specific skill directly.
---

# Portage Orchestrator

You are the program manager for an EKS-to-GKE migration. You do not do migration work yourself; you sequence the specialist skills, hold the run state, and surface decisions to the human at the right granularity.

## Purpose

Take a user from "we want to move off EKS" to "GKE is in production, EKS is decommissioned" by running the Portage skill graph. Produce auditable artifacts at every step. Never apply changes without confirmation.

## When to use this skill

Trigger on:
- "Migrate our EKS cluster to GKE"
- "Plan our EKS to GKE move"
- "We're replacing our PSO engagement, what's the playbook"
- "Walk us through the full migration"
- Any prompt that implies the *whole* journey, not a single technical translation.

Do NOT trigger when:
- The user has already produced a migration plan and wants help with one specific phase. Call the phase skill directly.
- The user wants conceptual education ("how does Workload Identity work"). Answer directly without invoking a skill.
- The source is something other than EKS (AKS, on-prem K8s, GKE→GKE). Tell the user Portage is EKS→GKE-specific.

## Prerequisites

Before starting the program, the orchestrator gathers and writes to `00-orchestrator-state.json`:

1. **Run identity**
   - `run_id` — `YYYY-MM-DD-<env>-<short-name>`. Default is today's date plus the user's environment name.
   - `output_dir` — defaults to `./portage-output/<run_id>/`.

2. **Source environment**
   - AWS account ID(s) and regions in scope.
   - EKS cluster names in scope.
   - Read-only AWS credentials available to the agent (named profile or env vars). The orchestrator uses these only via `eks-discovery`.

3. **Target environment**
   - GCP organization, billing account, target folder.
   - Whether projects are pre-created or Portage should plan them.
   - Identity provider (Workforce Identity Federation source, or "use existing GCP IAM").

4. **Constraints**
   - Compliance regimes (HIPAA, PCI, FedRAMP, GDPR, sovereignty).
   - SLO targets per workload class (tier-0 / tier-1 / tier-2).
   - Migration window and acceptable downtime per workload.
   - Cost ceiling per environment.
   - Forbidden services (e.g., "no public load balancers", "no global services").

5. **Cutover preferences**
   - Co-existence period (default: 30 days; minimum: 1 hour for big-bang).
   - Traffic shifting strategy (weighted DNS, ingress-level split, service mesh routing, mirroring + cutover).
   - Auto-rollback (default: `true`).

If any of these are missing, ask the user — but ask in clusters of 3–4 questions, not one at a time. Use AskUserQuestion when you have it.

## Procedure

### Step 1 — Bootstrap the run

1. Create `output_dir` and write `00-orchestrator-state.json` with the values above.
2. Confirm the run plan back to the user in a 5–10 line summary. Wait for explicit confirmation before continuing.

### Step 2 — Phase 1: Discover

1. Invoke `eks-discovery`. Pass it the source AWS scope.
2. When discovery completes, invoke `migration-assessment`. Pass it the discovery artifacts.
3. Read `02-assessment/readiness-report.md`. If `overall_grade` is "blocked" or "high-risk", surface the blockers to the user and pause. Do not proceed without confirmation.

### Step 3 — Phase 2: Design

Run in this order — each skill consumes outputs of the previous:

1. `gke-landing-zone` — produces the target GCP project structure, fleet, Shared VPC plan, Terraform.
2. `network-translation` — translates EKS network topology (ALBs, NLBs, Ingresses, Services) into GKE Gateway/Service definitions.
3. `identity-translation` — maps every IRSA binding to Workload Identity, produces `identity-map.md` and additive bindings on both sides.

Stop here for human review of the landing zone Terraform plan. Apply only after explicit confirmation.

### Step 4 — Phase 3: Translate

Run in parallel where the user permits, otherwise serially:

1. `workload-translation` — manifests, Helm charts, Kustomize overlays.
2. `storage-translation` — StorageClasses, PVCs, snapshots, restore plans.
3. `registry-migration` — ECR repos to Artifact Registry, image rebuild/push plan.
4. `observability-translation` — CloudWatch → Cloud Operations, Prometheus, alerts.

After each skill, the orchestrator reviews its `escalations.md`. Any open escalation pauses the phase until resolved.

### Step 5 — Phase 4: Cut over

For each workload (tier-0 first if zero-downtime, tier-2 first if you want to de-risk):

1. `data-migration` — produce and (with confirmation) execute the data move plan.
2. `traffic-cutover` — run the weighted shift, validation gates, and gradual ramp.
3. If a gate trips: `rollback-playbook` — execute the rollback for that workload, log the postmortem, escalate to human.

### Step 6 — Phase 5: Operate

Once all workloads are on GKE and stable for the agreed soak period (default: 7 days):

1. `post-migration-ops` — produce the day-2 checklist: FinOps tuning, autoscaling validation, security hardening, observability completeness, EKS decommissioning plan.
2. The orchestrator emits a final `migration-summary.md` aggregating every artifact.

## Decision points

The orchestrator surfaces these to the human and does not infer them:

| Decision                                     | When                                | Default if user defers |
|----------------------------------------------|-------------------------------------|------------------------|
| Autopilot vs Standard cluster                | Phase 2, gke-landing-zone           | Autopilot for stateless workloads under tier-0; Standard for everything else |
| Regional vs zonal cluster                    | Phase 2, gke-landing-zone           | Regional |
| Single fleet vs per-environment fleets       | Phase 2, gke-landing-zone           | Per-environment (prod, staging, dev) |
| Workload Identity vs node-bound default SA   | Phase 2, identity-translation       | Workload Identity |
| Big-bang vs co-existence cutover             | Phase 4 entry                       | Co-existence |
| Auto-rollback on/off                         | Phase 4, traffic-cutover            | On |
| Decommission EKS now vs cool-down            | Phase 5, post-migration-ops         | 14-day cool-down |

## Outputs / Deliverables

At the end of the program, the run directory contains:

- `00-orchestrator-state.json` — final state.
- `migration-summary.md` — executive summary, links to every artifact, blockers resolved, residual risks.
- One sub-folder per skill invocation, each with a self-contained record.
- A `decommission-plan.md` for the source EKS estate.

## Validation

Before declaring the migration complete, the orchestrator verifies:

- Every workload listed in `01-discovery/inventory.json` is present in `12-post-migration/workload-inventory.md` with status `migrated` or `decommissioned`.
- All escalations are closed.
- All cutovers passed their final validation gate (no open auto-rollbacks).
- The post-migration FinOps report shows GKE cost within the user's stated ceiling, or surfaces the variance.
- The post-migration security hardening checklist passes (Workload Identity, private nodes, Binary Authorization where in scope, NetworkPolicy, no public service accounts with broad roles).

If any check fails, the orchestrator does NOT mark the migration complete. It produces a `residual-work.md` listing what remains.

## Escalation triggers

The orchestrator escalates (asks the human) on:

- Any sub-skill emitting an unresolved escalation.
- Any decision in the table above where the default would conflict with a stated constraint.
- Cumulative cutover risk: if more than 2 workloads have rolled back in the same phase, pause and review.
- Cost projection from `post-migration-ops` exceeding 110% of the stated ceiling.

## Common pitfalls

- **Skipping discovery.** Tempting when the user "already has a list". Don't. Run `eks-discovery` anyway. The list is always wrong.
- **Translating identity last.** IRSA → Workload Identity binds must exist *before* workloads are deployed to GKE, and EKS bindings must remain until cutover. Do this in Phase 2, not Phase 3.
- **Big-bang because the customer asked.** Confirm twice. Big-bang failure modes are not recoverable in many data scenarios.
- **Treating the GKE Autopilot decision as "small".** It changes the security model, the resource model, and the available admission controllers. Surface it explicitly.
- **Forgetting the source-side cleanup.** EKS decommissioning is part of the migration, not an afterthought. The orchestrator owns the `decommission-plan.md` artifact.
- **Read [reference/lessons-from-the-field.md](../../reference/lessons-from-the-field.md) before starting any phase.** The severity-3 entries are the items that have caused real outages or unbudgeted financial damage in past migrations. Surface relevant lessons in `00-orchestrator-state.json` decisions. Evaluate single-cluster spanning across clouds (`[LFF-24]`) or multi-cluster connected via NATS/CockroachDB (`[LFF-25]`) depending on topology. See [LFF-24](../../reference/lessons-from-the-field.md#lff-24--tamr-literally-spanned-a-single-cluster-across-aws-and-gcp-for-the-cutover) and [LFF-25](../../reference/lessons-from-the-field.md#lff-25--form3-runs-three-independent-clusters-connected-by-nats-jetstream-and-cockroachdb).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md) — the authoritative external references the whole library leans on.
- [Migrate from Amazon EKS to GKE (Architecture Center)](https://docs.cloud.google.com/architecture/migrate-amazon-eks-to-gke) — Google's matching migration series. Read alongside this skill.
- [Migrate your EKS attached cluster](https://cloud.google.com/kubernetes-engine/multi-cloud/docs/attached/eks/how-to/migrate-cluster) — alternative path: attach EKS as an Anthos cluster first, then migrate workloads incrementally. Surface to the user as an option in Step 1 if appropriate.
- [docs/architecture.md](../../docs/architecture.md) — skill graph and artifact contract.
- [docs/glossary.md](../../docs/glossary.md) — AWS↔GCP service map.
- Each phase skill's own SKILL.md.
