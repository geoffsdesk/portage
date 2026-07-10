---
name: post-migration-ops
description: Run the day-2 work after every workload is on GKE — FinOps tuning (right-sizing, autoscaling, CUDs, Spot adoption), security hardening (Workload Identity audit, NetworkPolicy enforcement, Binary Authorization mode flip), observability completeness (golden-signal dashboards, SLO-tied alerts), and EKS decommissioning. Produces a final summary, FinOps report, hardening checklist, and decommission plan. Use as Phase 5 of a Portage migration, when "what do we do post-migration", or "tune GKE cost / harden the new environment".
---

# Post-Migration Ops

You run the day-2 work that turns a "migration done" state into a hardened, cost-tuned, observable production estate, then decommission the source.

## Purpose

Post-cutover, the GKE environment is *running*, but it is rarely *optimized*. This skill brings it up to production hygiene: right-sized, autoscaling correctly, properly secured, fully observable, with a clean source-side decommissioning plan.

## When to use this skill

- Phase 5 of a Portage migration: every workload has cut over, soak windows have passed.
- The user asks "what do we do now", "tune the GKE cost", "harden the new clusters", "decommission EKS".

## Prerequisites

- Every workload's `traffic-cutover` is `complete` and soaked.
- Every workload's `data-migration` is `complete`.
- The 14-day cool-down window for rollback has begun (not necessarily ended).
- `gcloud`, `kubectl`, access to billing exports.

## Procedure

### Step 1 — FinOps baseline

Pull a 30-day post-cutover billing slice:

```bash
gcloud billing accounts list
bq query --use_legacy_sql=false \
'SELECT
   service.description AS service,
   sku.description AS sku,
   SUM(cost) AS cost,
   currency
 FROM `BILLING_PROJECT.BILLING_DATASET.gcp_billing_export_v1_BILLING_ACCOUNT_ID`
 WHERE _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
   AND project.id IN ("gke-prod-clusters","data-prod","obs-prod","artifact-registry")
 GROUP BY service, sku, currency
 ORDER BY cost DESC LIMIT 50;'
```

Compare against the EKS pre-migration baseline (from inventory + AWS billing). Produce `12-post-migration/finops/cost-comparison.md`:

- Total monthly cost: GKE post vs EKS pre.
- Variance per service (compute, storage, network egress, observability, registry, data services).
- Any line items > 5% of total that were not present before.

### Step 2 — Right-sizing

The methodology below is grounded in [Best practices for running cost-optimized Kubernetes applications on GKE](https://docs.cloud.google.com/architecture/best-practices-for-running-cost-effective-kubernetes-applications-on-gke) and [About Vertical Pod Autoscaling](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/verticalpodautoscaler). Where Google publishes a number, that's what we use; where they don't, the rule is labeled **tool-opinionated**.

**Google's request/limit shape rule (verbatim):**
- **Memory**: set the same amount of memory for the request and limit. ("when memory is exhausted, the Pod needs to be taken down ... you must set requested memory to the memory limit.")
- **CPU**: set request to the minimum CPU needed for SLO compliance. **Set an unbounded CPU limit** (omit `limits.cpu`). ("When the CPU is contended, these Pods can be throttled down to its requests.")

**Google's methodology (verbatim):**
- Run **VPA in `Off` (recommendation) mode** in a production-like environment with real traffic.
- Wait at least **24 hours, ideally one week or more**, before pulling recommendations.
- Then statically pin requests and limits in the manifest, or graduate VPA to `Initial` / `Auto` / `InPlaceOrRecreate`.

**Google's OOM safety buffer (verbatim, from VPA concepts):** "If a Pod is `OOMKilled`, the vertical Pod autoscaler immediately observes the event and increases the memory recommendation by approximately 20% (or 100 MB, whichever is larger)." Apply this buffer to the recommendation before pinning.

**Procedure:**

1. Enable VPA in `Off` mode for every Deployment / StatefulSet:

   ```yaml
   apiVersion: autoscaling.k8s.io/v1
   kind: VerticalPodAutoscaler
   metadata:
     name: payments-api
     namespace: payments
   spec:
     targetRef:
       apiVersion: apps/v1
       kind: Deployment
       name: payments-api
     updatePolicy:
       updateMode: "Off"   # recommendation only
   ```

2. Soak for ≥ 7 days at production-representative traffic.

3. Pull recommendations:

   ```bash
   kubectl get vpa payments-api -n payments \
     -o jsonpath='{.status.recommendation.containerRecommendations[*].target}'
   ```

4. Apply the request/limit shape rule:
   - `requests.cpu` = VPA `target` CPU.
   - `limits.cpu` = (omit).
   - `requests.memory` = `limits.memory` = VPA `target` memory + 20% (or +100 MB, whichever is larger).

5. Open as PR; surface for review. Do not promote VPA to `Auto` mode without explicit user opt-in (see Step 3 guardrails).

> **Tool-opinionated** — *Portage* compares VPA recommendations against current requests and flags candidates where current request is > 1.5× the recommendation. Google does not publish a percentile threshold for "over-provisioned"; the VPA recommender's internal histograms target ~90th-percentile CPU and 90th–95th memory, but those numbers come from the upstream VPA source, not from this Google page.

### Step 3 — Autoscaling tuning

**HPA target utilization (Google's formula, verbatim):**

```
target = (1 - buff) / (1 + perc)
```

where *buff* is your safety buffer and *perc* is the traffic growth you expect in 2–3 minutes. Google's worked example: 10% buffer + 30% spike → target = (1 − 0.1) / (1 + 0.3) = **0.69** (i.e., ~70% target CPU utilization).

For each HPA:
- Set the target via the formula. The 70% example is Google's illustrative default.
- Ensure container startup is fast and shutdown is graceful (init container for warm-up if needed; `terminationGracePeriodSeconds` honored).
- Confirm the workload has meaningful readiness/liveness probes.
- Verify Metrics Server is up.

> **Tool-opinionated** — *Portage* sets `behavior.scaleDown.stabilizationWindowSeconds: 300` and `behavior.scaleUp.stabilizationWindowSeconds: 0` as defaults. Google does not publish recommended HPA stabilization windows; these come from common SRE practice.

**VPA mode promotion (verbatim guardrails from Google):**
- Start in **Off** mode for ≥ 24 h, ideally a week.
- "**Don't use VPA Initial or Auto mode if you need to handle sudden spikes in traffic. Use HPA instead.**"
- Set `minAllowed` / `maxAllowed` to "avoid the autoscaler making significant changes when your application is not receiving traffic."
- "**Don't make abrupt changes**" — e.g., dropping replicas from 30 to 5 at once.
- For `Auto` mode: workload must be safe to restart while taking traffic; add a PodDisruptionBudget.
- VPA + HPA on the same metric is **not allowed**. Safe combinations: VPA in recommendation mode while HPA is on CPU, or HPA on a custom metric (e.g., RPS) while VPA is on Auto for CPU/memory.
- Cap of 1,000 VPA objects per cluster.

**Cluster Autoscaler / NAP (verbatim guidance):**
- "Enable CA whenever you are using either HPA or VPA."
- NAP is the right call when workload shapes vary enough that pre-defined node pools waste resources, accepting that scale-up latency can be slightly higher.
- Set min/max bounds on NAP pools to avoid drift when traffic drops.
- "When using HPA for serving workloads, consider reserving a slightly larger target utilization buffer because NAP might increase autoscaling latency."

**Headroom for bursts.** Google does not publish a fixed cluster-headroom percentage. Two patterns it does name:
1. **Higher HPA buffer** — enlarge *buff* in the formula above.
2. **Pause Pods** — low-priority deployments that reserve capacity and get evicted when high-priority pods need it. Google's sizing rule (verbatim): "It's a best practice to have only a single pause Pod per node. For example, if you are using 4 CPU nodes, configure the pause Pods' CPU request with around 3200m." (Implication: ~80% of node-allocatable CPU.)

**Pod Disruption Budgets:** every Deployment with > 1 replica has a PDB.

Produce `12-post-migration/autoscaling-tuning.md` with per-workload changes.

### Step 4 — Spot / Committed-use discounts

**Spot adoption (Google's eligibility, verbatim):** "Spot VMs on GKE are best suited for running batch or fault-tolerant jobs that are less sensitive to the ephemeral, non-guaranteed nature of Spot VMs. **Stateful and serving workloads must not use Spot VMs unless you prepare your system and architecture to handle the constraints of Spot VMs.**"

**Discount level (verbatim):** "up to 91% cheaper than standard Compute Engine VMs."

**Constraints to plan for (verbatim):**
- "Pod Disruption Budget might not be respected because Spot VMs can shut down inadvertently."
- "There is no guarantee that your Pods will shut down gracefully once node preemption ignores the Pod grace period."
- "It might take several minutes for GKE to detect that the node was preempted."
- Graceful node shutdown is enabled by default since GKE 1.20.

**Backup pool requirement (verbatim):** "Spot VMs have no guaranteed availability, meaning that they can stock out easily in some regions. To overcome this limitation, we recommend that you set a backup node pool without Spot VMs."

For each candidate workload, validate batch / fault-tolerant fit, attach `cloud.google.com/gke-spot: "true"` toleration, and verify the on-demand backup pool sizing.

> **Tool-opinionated** — Portage caps the % of cluster capacity on Spot at "whatever the on-demand backup pool can absorb during a stockout" — there is no Google-published numeric cap. Portage default: ≤ 50% for non-prod, ≤ 25% for prod batch tier.

**Committed-use discounts (verbatim from Google):** "If you intend to stay with Google Cloud for a few years, we strongly recommend that you purchase committed-use discounts ... up to 70% discount ... commit to paying for those resources for one year or three years. If you are unsure about how much resource to commit, look at your minimum computing usage—for example, during nighttime—and commit the payment for that amount."

Methodology Portage applies (with citations to Google for each step):
1. Compute the **trough** of vCPU and memory across all clusters from 30 days of billing/usage data — that's the floor commitment.
2. Choose **resource-based** vs **spend-based** CUDs based on shape stability. Resource-based pins to a machine family + region; spend-based applies organization-wide and survives re-architecture.
3. Choose **1y** or **3y** term. Google does not publish a break-even threshold. Portage's defensible default: 1y unless the workload has been steady for ≥ 6 months and roadmap doesn't reshape it within 24 months.
4. Use [CUD analysis](https://cloud.google.com/billing/docs/how-to/cud-analysis) in the billing console to validate; the analyzer recommends a commit shape based on actual usage.

CUDs are a binding commitment. Do not purchase without explicit user confirmation.

> **Tool-opinionated** — break-even thresholds, "commit if utilization > X%" rules, and 1y-vs-3y math are *not* in the canonical Google FinOps page. The CUD analyzer page is the authoritative tool; treat anything beyond "commit to your floor" as Portage opinion.

### Step 5 — Security hardening checklist

Walk through and confirm:

| Check                                                          | Default state | Tighten action                              |
|----------------------------------------------------------------|---------------|---------------------------------------------|
| Workload Identity enabled                                      | Yes           | Verify; no `iam.disableServiceAccountKeyCreation` exceptions |
| Private nodes                                                  | Yes           | Verify; private endpoint where possible     |
| Authorized networks list                                       | Limited       | Confirm only ops/CI ranges; remove `0.0.0.0/0` if present |
| Binary Authorization                                           | EVALUATION    | Move to ENFORCE after 2-week clean attestation history |
| NetworkPolicy default-deny per prod namespace                  | Apply         | Migrate from "logging only" to enforced     |
| Pod Security Admission                                         | `baseline` enforced | Move to `restricted` enforced for new namespaces; warn-then-enforce for existing |
| GKE Compliance Posture (Cloud Security Posture)                | Enabled       | Review findings, file fixes                 |
| CMEK on cluster DB encryption                                  | Yes           | Verify                                       |
| Container scanning (Artifact Analysis)                         | Enabled       | Address criticals, set SLA for high/critical |
| Audit logs enabled (Admin Activity, Data Access)               | Admin Activity always; Data Access opt-in | Enable Data Access for sensitive resources |
| Service-account-key audit                                      | None expected | Run `gcloud iam service-accounts keys list` org-wide; expect zero in steady state |
| GKE upgrade channel                                            | `regular` or `stable` | Confirm; no manual pinning unless required |

Produce `12-post-migration/hardening-checklist.md` with status per item.

### Step 6 — Observability completeness

Verify per workload:

- Golden signals dashboard (latency, traffic, errors, saturation) in Cloud Monitoring scoped to the workload.
- SLO defined and tracking (use the SLO created in `observability-translation`).
- Alerting policy on SLO burn-rate (multi-window: fast 1h × 5%, slow 6h × 5%).
- Runbook URL embedded in each alerting policy.

Produce `12-post-migration/observability-checklist.md`.

### Step 7 — EKS decommissioning plan

Render `12-post-migration/decommission-plan.md`:

- **T+0**: rollback window closes (default 14 days post the *last* workload's cutover).
- **T+1**: scale all EKS deployments to 0; keep clusters up.
- **T+7**: archive any application logs/metrics not yet exported. Snapshot any remaining EBS volumes and copy to long-term storage (Cloud Storage Archive or S3 Glacier).
- **T+14**: delete EKS clusters (`eksctl delete cluster` or Terraform destroy on the EKS module). VPC endpoints, NAT gateways, ALBs deleted in parallel.
- **T+21**: delete any leftover IAM roles whose Trust Policies referenced the cluster's OIDC provider.
- **T+30**: delete S3 buckets that were data-migration sources and have completed retention. Delete RDS / ElastiCache / MSK clusters that have completed retention. Retire CloudWatch log groups per retention policy.
- **T+30**: review AWS billing for residual charges. Most should be $0; investigate any non-zero line items.

Surface to the user as a checklist with confirmation gates at T+1, T+14, T+30. Decommissioning is irreversible; never auto-execute.

### Step 8 — Final summary

Render `12-post-migration/migration-summary.md`:

- Migration window, actual vs planned.
- Workload count: total / migrated / decommissioned / out-of-scope.
- Cost variance vs ceiling.
- Open issues (none expected; if any, listed with owners and dates).
- Lessons learned (the agent emits a draft; the user finalizes).
- Links to every artifact in the run directory.

Also render `migration-summary.pdf` if the user wants a board-ready version.

## Decision points

| Decision                                | Default                       | When to deviate                              |
|-----------------------------------------|-------------------------------|----------------------------------------------|
| VPA `Off` (recommend) vs `Auto`         | Off; manual review            | Auto on stateless, low-tier after one clean cycle |
| Spot adoption per workload              | Recommend; user opts in       | Default Spot only on test/dev clusters       |
| CUD purchase amount                     | 1-year resource-based for steady state | 3-year only with explicit CFO sign-off       |
| Decommission timing                     | 14-day cool-down              | 7 days for non-prod, 30 days for tier-0      |
| Move PSA to `restricted`                | After hardening review        | Immediately for new namespaces only          |

## Outputs / Deliverables

```
12-post-migration/
├── migration-summary.md
├── finops/
│   ├── cost-comparison.md
│   ├── rightsizing-recommendations.md
│   └── cud-plan.md
├── autoscaling-tuning.md
├── hardening-checklist.md
├── observability-checklist.md
├── decommission-plan.md
└── workload-inventory.md            # final state of every workload
```

## Validation

- Cost comparison: GKE post-migration cost is within the user's stated ceiling, or the variance is named and explained.
- Right-sizing recs are scoped (no recommendation < 100m / < 64Mi to avoid silly suggestions).
- Hardening checklist has a row for every cluster.
- Observability checklist: every tier-0 workload has a tracking SLO and burn-rate alert.
- Decommission plan: every EKS cluster, EKS-bound IAM role, EKS-bound network resource (ALB/NLB/security group/route 53 record) has a row with a target date.
- Final summary signed off by the user.

## Escalation triggers

- Cost exceeds 110% of ceiling and right-sizing alone won't close the gap. Surface; the user may need to revisit cluster sizing or tier classification.
- Hardening item cannot be enforced without breaking a workload (e.g., a workload won't run under `restricted` PSA). File as a known exception with owner and target date.
- A scheduled decommission step has dependencies still using the source resource. Pause that step.

## Common pitfalls

- **Right-sizing into instability.** Trim too aggressively and you trigger throttling/OOM under spike. Apply with VPA `Off` recommendations, not blindly.
- **Premature Binary Authorization enforce.** Forces a deployment outage if any image lacks an attestation. Dry-run for at least two weeks.
- **Decommissioning before the cool-down.** Resist the urge. The cool-down is what saved the last migration that needed a rollback at day 9.
- **CUD lock-in for unstable workloads.** Workloads that are in mid-architecture-change should not be CUD-covered. Wait one quarter.
- **Forgetting NAT gateway and load-balancer cost on AWS side.** Even with workloads scaled to 0, AWS NAT and ALB costs continue. Decommission them on schedule.
- **GKE bin-packing post-migration commonly drops to <40% utilization** as teams arrive from Karpenter-on-EKS and NAP runs many small node pools. Use `optimize-utilization` profile and consolidate node pools. See [LFF-19](../../reference/lessons-from-the-field.md#lff-19--gke-bin-packing-post-migration-commonly-drops-to-40-node-utilization).
- **Autopilot per-pod billing scales badly at high-volume bursty workloads.** Model Autopilot vs Standard cost on actual workload shape before defaulting. See [LFF-34](../../reference/lessons-from-the-field.md#lff-34--autopilot-pay-per-request-billing-exploded-at-scale-for-one-team-they-reversed-to-eks-with-karpenter).
- **Autopilot POC cost.** Trivial CPU workloads on Autopilot can incur unexpected baseline sizing costs (~$1k/mo in POCs). Verify node sizing vs Autopilot minimums. See [LFF-35](../../reference/lessons-from-the-field.md#lff-35--autopilot-poc-cost-1kmo-for-trivial-cpu-workloads-in-one-teams-measurement).
- **PB scale shadow-reads and dedicated interconnect.** Dedicated cloud interconnect is roughly 5× cheaper than open-internet egress for PB volumes. See [LFF-02](../../reference/lessons-from-the-field.md#lff-02--sifts-petabyte-awsgcp-move-dual-wrote-and-shadow-read-for-weeks).
- **HPA + VPA on the same metric is unsupported and thrashes.** Move VPA to recommend mode, or HPA to a custom metric. See [LFF-18](../../reference/lessons-from-the-field.md#lff-18--hpa--vpa-on-the-same-metric-thrashes-upstream-warns-explicitly).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Best practices for running cost-optimized Kubernetes applications on GKE](https://docs.cloud.google.com/architecture/best-practices-for-running-cost-effective-kubernetes-applications-on-gke) — verbatim source for right-sizing, HPA, VPA, CA, NAP, Spot, CUD methodology.
- [About Vertical Pod Autoscaling](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/verticalpodautoscaler) — OOM safety buffer (~20% / 100 MB), mode definitions.
- [Cluster autoscaler](https://cloud.google.com/kubernetes-engine/docs/how-to/cluster-autoscaler).
- [Node auto-provisioning](https://cloud.google.com/kubernetes-engine/docs/how-to/node-auto-provisioning).
- [Spot VMs on GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/spot-vms).
- [CUD analysis](https://cloud.google.com/billing/docs/how-to/cud-analysis).
- [Hardening your cluster's security](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/hardening-your-cluster) — for the hardening checklist.
- [docs/glossary.md](../../docs/glossary.md) — final reference for service mappings.
- [traffic-cutover](../traffic-cutover/SKILL.md) — verifies all workloads are at 100%.
- [templates/postmortem-template.md](../../templates/postmortem-template.md) — for the residual-issue reviews.
