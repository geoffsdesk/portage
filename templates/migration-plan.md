# Migration Plan — {{customer_name}}

**Run ID:** {{run_id}}
**Plan owner:** {{owner}}
**Last updated:** {{date}}

---

## 1. Goals and non-goals

### Goals

- Move {{n_workloads}} workloads from EKS to GKE within {{window_days}} days.
- Achieve parity on availability ({{slo}}) and p95 latency ({{p95_target}}) for tier-0 workloads.
- Land cost within {{cost_ceiling}} per month per environment.
- Decommission EKS source within {{decommission_days}} days post-cutover.

### Non-goals

- Engine changes for data systems (Aurora → AlloyDB, DynamoDB → anything). These are scoped separately.
- Application-code changes beyond what is necessary for cloud-API translation.
- Changes to upstream identity provider beyond enabling Workforce Identity Federation.

## 2. Scope

| In-scope                                                  | Out-of-scope                                                       |
|-----------------------------------------------------------|--------------------------------------------------------------------|
| All EKS clusters in account {{account_id}}                | EKS clusters in {{out_of_scope_accounts}}                          |
| Stateless workloads in tier-0/1/2                         | Stateful workloads using {{out_of_scope_storage}}                  |
| RDS Postgres instances                                    | DynamoDB tables (separate re-platform)                              |
| ElastiCache Redis (rebuild semantics)                     | Aurora-specific replicas                                            |
| ECR repositories actively pulled from                     | Archived ECR repos                                                  |

## 3. Phasing

(Same shape as readiness-report Phase 5, with absolute dates.)

| # | Phase                  | Start         | End           | Skill(s) executed                                          | Exit gate                                  |
|---|------------------------|---------------|---------------|------------------------------------------------------------|---------------------------------------------|
| 0 | Bootstrap              | {{date}}      | {{date}}      | portage-orchestrator                                       | State file created                          |
| 1 | Discover & assess      | {{date}}      | {{date}}      | eks-discovery, migration-assessment                        | Readiness report signed off                 |
| 2 | Design                 | {{date}}      | {{date}}      | gke-landing-zone, network-translation, identity-translation | Terraform applied; identity validated       |
| 3 | Translate              | {{date}}      | {{date}}      | workload-, storage-, registry-, observability-translation  | Manifests reviewed; AR populated            |
| 4 | Cut over               | {{date}}      | {{date}}      | data-migration, traffic-cutover, rollback-playbook         | Each cohort: 24-h soak green                |
| 5 | Operate & decommission | {{date}}      | {{date}}      | post-migration-ops                                         | EKS retired; final summary                  |

## 4. Cohorts

Group workloads into cutover cohorts to limit blast radius:

| Cohort | Workloads                                | Tier | Stateful? | Window                  |
|--------|------------------------------------------|------|-----------|-------------------------|
| C1     | {{cohort_1}}                             | 2    | No        | {{date_window_1}}       |
| C2     | {{cohort_2}}                             | 1    | Yes       | {{date_window_2}}       |
| C3     | {{cohort_3}}                             | 0    | Yes       | {{date_window_3}}       |

## 5. Identities & access

- Workforce Identity Federation source: {{idp}}.
- Per-cohort GSAs created and bound; KSAs annotated.
- Cross-cloud federation (AWS-side OIDC provider for the GKE workload pool) for any workload retaining AWS API calls during co-existence.

## 6. Data plan

| System                | Source                              | Target                       | Strategy   | Replication tool     | Cutover gate                  |
|-----------------------|-------------------------------------|------------------------------|------------|----------------------|-------------------------------|
| prod-payments-db      | RDS Postgres 15.4                   | Cloud SQL Postgres 15        | Continuous | Database Migration Service | Lag < 30s for 5 min            |
| prod-session-cache    | ElastiCache Redis Cluster Mode 7    | Memorystore Redis Cluster    | Empty + warm-up | Cache rebuild         | Hit-rate > {{hr_target}}      |
| shop-orders bucket    | S3                                  | GCS                          | Incremental | Storage Transfer Service | Object count parity            |
| order-events stream   | MSK Kafka                           | Confluent Cloud on GCP       | Mirror     | MM2                   | MM2 lag ≈ 0                   |

## 7. Cutover mechanism

- Routing: Cloud DNS WRR weighted records, TTL 60s.
- Ramp: 1% / 10% / 50% / 100% with soaks per readiness-report.
- Auto-rollback: enabled at backend-health gates; pause + ask at SLO gates.

## 8. Risks

(Inherited from readiness-report § 7. Update as cutover progresses.)

## 9. Communication plan

- Stakeholder list: {{list}}
- Cadence: weekly status (Mon 9am), daily during active cutover windows.
- Escalation path: {{path}}
- Status page (internal): {{link}}

## 10. Approvals

| Approver        | Role                | Phase    | Signed off |
|------------------|---------------------|----------|-------------|
| {{approver_1}}  | Engineering owner    | All      | [ ]         |
| {{approver_2}}  | Security             | 2, 5     | [ ]         |
| {{approver_3}}  | Compliance           | 2, 5     | [ ]         |
| {{approver_4}}  | Finance / FinOps     | 5        | [ ]         |
