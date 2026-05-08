# Worked Example — Migrating "ShopCo" from EKS to GKE

This is a fictional but representative example of running Portage end-to-end. It illustrates inputs, agent prompts, and artifacts at each phase. The numbers and names are made up; the patterns are real.

## ShopCo, in brief

- One AWS account, two regions: us-east-1 (prod) + us-west-2 (DR).
- Two EKS clusters (`prod-east`, `prod-west`), both 1.30, both Karpenter-managed.
- 47 workloads across 12 namespaces. Tier-0 list: `web`, `checkout`, `payments-api`, `order-events-consumer`. Tier-2 list: 30 workloads.
- Stateful workloads: 1× RDS Postgres 15 (`prod-payments-db`), 1× ElastiCache Redis (`prod-session-cache`), 1× MSK (`order-events`), 1× S3 bucket (`shop-orders`).
- IRSA: 21 bindings.
- Observability: AMP, AMG (self-hosted Grafana), CloudWatch alarms, X-Ray.
- Compliance: PCI-DSS scope on `payments-api` and `prod-payments-db`.
- Migration window: 10 weeks (70 days).
- Cost ceiling: $14k/mo per env (matches current EKS spend).

## Day 0 — Bootstrap

The platform lead opens an agent session in the team's repo and types:

> Use the portage-orchestrator skill. Source: AWS account 123456789012 in us-east-1 and us-west-2. Target: GCP org shopco.com, billing account ABC, target folder portage-prod. Window 10 weeks. Compliance: PCI on payments-api and prod-payments-db. Cost ceiling $14k/mo per env. Tier-0: web, checkout, payments-api, order-events-consumer. Co-existence 30 days. Auto-rollback on.

The orchestrator confirms back the run plan in 6 lines, asks 3 clarifying questions (identity provider, GKE Autopilot vs Standard preference, big-bang allowed?), and creates `portage-output/2026-05-06-shopco-prod/`.

## Week 1 — Discover

```
> begin Phase 1
```

The orchestrator invokes `eks-discovery`. After 90 minutes, `inventory.json` has:

- 2 clusters, 47 workloads, 12 namespaces.
- 21 IRSA bindings (3 cluster-level: cluster-autoscaler, aws-load-balancer-controller, external-dns).
- 14 ALBs, 2 NLBs.
- 17 PVCs (12 backed by EBS gp3, 4 by EBS io2, 1 RWX on EFS).
- ECR: 38 repositories.

Two escalations:

1. `aws-pod-identity-webhook` MutatingWebhookConfiguration in `kube-system` (drop on GKE — known pattern).
2. `prod-east` cluster authentication mode is `CONFIG_MAP` (legacy `aws-auth`). Flag for translation; will need IAM+RBAC work in Phase 2.

The orchestrator runs `migration-assessment`. Output:

- Overall grade: **Tractable**.
- Workloads: 35 Ready, 9 Tractable, 3 High-risk (the stateful ones).
- Effort estimate: P50 110 eng-days, P90 165 eng-days. Org coefficient 1.0 (team has prior GKE experience). Within window for a 6-engineer team.
- Top blockers: PCI scope on Cloud SQL (verify configuration), MSK → no GA managed Kafka on GCP (Confluent Cloud chosen), RWX PVC on EFS (Filestore Enterprise sized).

The platform lead reviews. Approves Phase 2.

## Weeks 2–3 — Design

```
> proceed to Phase 2
```

The orchestrator runs `gke-landing-zone`. After clarifying:

- 4 prod projects (`net-prod-host`, `gke-prod-clusters`, `data-prod`, `obs-prod`) plus 4 nonprod equivalents plus 3 shared.
- Shared VPC per env, 2 regions each (us-central1 + us-east1 for DR).
- Clusters: Autopilot for `nonprod-primary`, Standard for `prod-primary` (because checkout's payment processor needs a sidecar with hostNetwork — not Autopilot-compatible).
- Org policies, KMS, fleet, budgets.

`terraform plan` output: ~180 resources. Reviewed. Applied in 35 minutes.

`network-translation` runs:
- 14 ALBs → 6 Gateways (some merged), 14 HTTPRoutes.
- 2 NLBs → 2 Services with `networking.gke.io/load-balancer-class: regionalExternal`.
- ACM cert ARNs reissued in Certificate Manager (DNS01 via Cloud DNS for hostnames the team owns).
- AWS WAFv2 rules → Cloud Armor with preconfigured `xss-stable`, `sqli-stable`, `cve-stable` plus 2 custom CEL rules for known scrapers.
- Cloud DNS records planned with TTL 60s for the cutover hostnames.

`identity-translation` runs:
- 21 IRSA bindings → 21 GSAs.
- 18 of them map cleanly to predefined GCP roles. 3 have AWS-specific operations the workload uses; the orchestrator sets up cross-cloud federation for those 3 to retain the AWS IAM role during co-existence.
- Per-KSA validation passes via the test pod.

End of Week 3: cluster up, identity wired, network manifests ready (not yet applied at full scale).

## Weeks 4–5 — Translate

```
> proceed to Phase 3
```

`registry-migration`:
- 38 ECR repos → 38 AR repos in `us-central1`. Mirror complete in 4 hours (~340 GiB).
- Pipelines updated to dual-push.
- Vuln baseline: 11 critical findings across base images. Filed for fix.

`storage-translation`:
- 12 EBS gp3 → `pd-balanced` StorageClass.
- 4 EBS io2 → `hyperdisk-extreme`.
- 1 EFS → Filestore Enterprise, 2.5 TiB tier.
- Per-PVC plan: Strategy A (Velero) for 11 of 17, Strategy C (app-native) for the Postgres data dir, Strategy E (RWX) for the EFS file share.

`workload-translation`:
- 47 workloads translated.
- 3 require Helm chart forks (templates assumed AWS LB Controller).
- 2 fail Autopilot validation (use `hostNetwork: true`); they're already targeting Standard.
- 12 need `nodeSelector` updates (Karpenter labels → GKE Spot).

`observability-translation`:
- AMP scrape configs → 41 PodMonitorings.
- 89 CloudWatch alarms → 89 alerting policies (5 needed manual review for custom expressions).
- AMG dashboards → re-deployed Grafana on `obs-prod` with two data sources.
- X-Ray → OTel + Cloud Trace exporter (5 services need SDK swap; non-blocking, scheduled separately).

End of Week 5: every workload has translated artifacts. Non-prod cluster running translated tier-2 cohort.

## Weeks 6–8 — Cut over

```
> proceed to Phase 4 with cohort C1 (tier-2 stateless, 30 workloads)
```

`data-migration` (no data needed for C1).

`traffic-cutover` for C1:
- 1% / 10% / 50% / 100% per workload, 5 workloads in parallel max.
- 28 of 30 cut over without incident.
- 2 workloads tripped p95 latency gate at 50%. Investigation: cross-cloud egress to a still-on-EKS dependency. Resolution: deploy the dependency on GKE first, retry. Both pass.
- 24 h soak on C1: green.

```
> proceed to cohort C2 (tier-1 + stateful)
```

`data-migration` for C2:
- `prod-payments-db` (RDS Postgres → Cloud SQL Postgres): DMS continuous replication, 18 h initial sync, lag < 8 s steady-state. Cutover during a 30-minute window: writers stopped, lag drained to 0, target promoted, app config repointed. Replication verification: row counts match for 11 critical tables, 1000-row hash sample matches.
- `prod-session-cache` (Redis): rebuildable; empty target provisioned, 30 s warm-up at cutover with shadow traffic, no impact.

`traffic-cutover` for C2 workloads (`web`, `checkout`, `payments-api`):
- Slower ramp (1% / 5% / 25% / 50% / 75% / 100%).
- `payments-api` tripped backend-health gate at 50% — auto-rollback fires. Cause: WI binding for the new GSA missed `roles/cloudkms.cryptoKeyDecrypter` on the data-prod KMS keyring. Fixed in 15 min. Re-attempt (after sign-off): clean.
- `web` and `checkout` cut over without incident.
- 24 h soak: green.

```
> proceed to cohort C3 (tier-0 stateful, 14 workloads incl. order-events-consumer)
```

`data-migration`:
- `order-events` (MSK → Confluent Cloud on GCP): MM2 mirror set up 4 days before cutover, lag steady < 1 s. Consumer offsets translated, consumer groups switch over during cutover window with zero message loss verified.
- `shop-orders` (S3 → GCS): STS continuous, ~12M objects, 8 TiB. Final delta at cutover: 4 minutes.

`traffic-cutover` for C3:
- Slowest ramp pattern (1% / 5% / 25% / 50% / 75% / 100% with 60-min soaks).
- All 14 workloads cut over without rollback.
- 24 h soak: green.

End of Week 8: 100% on GKE. EKS workloads scaled to 0. DNS cleaned up.

## Weeks 9–10 — Operate

```
> proceed to Phase 5
```

`post-migration-ops`:
- FinOps cost comparison: GKE prod $12.4k/mo, GKE nonprod $3.1k/mo. EKS baseline was $13.8k + $3.4k. **Savings: 9%** (mostly from CUD-eligible commitments and the shift from EBS io2 → Hyperdisk Extreme being cheaper at the IOPS level used).
- Right-sizing: 14 workloads identified as over-provisioned by P95 < 50% requests. PR opened.
- Spot adoption: 5 tier-2 workloads moved to Spot node pool. Saves an additional ~$400/mo.
- 1y resource-based CUD purchase: planned and signed off after CFO review.

Hardening checklist:
- BinAuthz moved to ENFORCE (after 14 days clean attestation history).
- NetworkPolicy default-deny applied to `payments` namespace.
- PSA: `restricted` enforced for new namespaces; existing namespaces in `baseline` enforced + `restricted` warned.
- Service-account keys org-wide: 0 (good).
- SCC findings: 3 high, 11 medium. All filed; high-severity addressed before sign-off.

Decommission:
- T+1 (Week 9): EKS Deployments scaled to 0.
- T+7: archive logs/metrics, snapshot residual EBS volumes.
- T+14 (Week 10): both EKS clusters deleted, ALBs/NLBs/NAT torn down.
- T+21: IAM roles cleaned up.
- T+30: data retention review; RDS snapshots archived per PCI retention.

Final summary signed off by: VP Engineering, Head of Security, Head of Compliance, CFO delegate.

## Outcome

| Metric                       | Plan         | Actual           | Notes                                              |
|------------------------------|--------------|-------------------|----------------------------------------------------|
| Migration window             | 10 weeks     | 10 weeks          | On time.                                           |
| Workloads migrated           | 47           | 47                | None abandoned.                                    |
| Auto-rollbacks               | 0–2 expected | 1 (`payments-api`)| Caught by backend-health gate; resolved in 15 min. |
| Postmortems                  | 0–2          | 1                 | Action items closed before phase 5 sign-off.       |
| Cost vs ceiling              | ≤ $14k/mo    | $12.4k/mo prod    | 11% under.                                         |
| SLO impact (cumulative)      | < 1 budget-hour | 12 budget-minutes  | All within tier-0 budget.                          |

## Lessons (for future runs)

1. The `payments-api` rollback could have been prevented by an end-to-end identity test that *exercised* every GSA binding before cutover — not just `gcloud auth list`. The team is contributing this as a `identity-translation` enhancement.
2. The MM2 setup for Kafka was the longest-running pre-cutover task. Future runs should start MM2 in Phase 3, not Phase 4.
3. Cloud Armor's preconfigured WAF rules at `stable` tuning level produced fewer false positives than EKS's AWS WAF managed rules. Recommend `stable` over `canary` for prod from the start.
4. The cool-down window was respected and not used; consider 7 days for non-PCI workloads next time.
