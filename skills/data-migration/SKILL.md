---
name: data-migration
description: Plan and (with confirmation) execute data migrations from AWS data services to GCP equivalents — RDS to Cloud SQL or AlloyDB, ElastiCache to Memorystore, S3 to GCS, MSK to GCP Kafka or Confluent Cloud — and the secrets/config moves that go with them. Produces per-data-system runbooks, replication plans, validation gates, and cutover scripts. Use after storage-translation, when "plan our RDS migration", "migrate Redis to Memorystore", or "data layer plan for the GKE move".
---

# Data Migration Router

You plan and run the data layer of an EKS-to-GKE migration: managed databases, caches, queues, object storage, secrets. You produce per-system runbooks, then with explicit confirmation, drive the actual move.

## Purpose

Convert "we have RDS Postgres, ElastiCache Redis, three S3 buckets, and MSK" into a moved, validated, observable GCP state — without dropping data, without unbounded downtime, and with a rollback path at every step. Routes database and data pipeline migration requests to specialized sub-procedures, ensuring all cross-cloud egress (`[LFF-01]`) and connectivity boundaries (`[LFF-12]`, `[LFF-13]`) are validated prior to execution.

## When to use this skill

- Phase 4 of a Portage migration.
- The user asks to "plan the data migration", "migrate RDS to Cloud SQL", "move S3 to GCS for the migration".

## Prerequisites

- `01-discovery/inventory.json` data dependencies section.
- `02-assessment/readiness-report.md` with effort estimate per system.
- `03-landing-zone/plan.md` with the `data-prod` project provisioned.
- **Egress Budget Sign-Off (`[LFF-01]`)**: Section 7 of `readiness-report.md` must contain an executed model from `tools/egress-estimator/egress_estimator.py`.
- **Deny-by-Default HITL Confirmation**: Any mutation (`dms start-replication-task`, `gcloud sql instances promote`) requires interactive confirmation displaying command line and cost estimates.
- IAM permissions in source AWS for `dms:*` (where DMS is in scope) and read on source data systems.
- IAM permissions in GCP for the data services in scope (`cloudsql.admin`, `redis.admin`, etc.).

## Procedure

### Step 1 — Route to Sub-Procedure by System Type

For each data system in `inventory.json`, identify the store type and delegate to the corresponding sub-module:
- **PostgreSQL / Cloud SQL**: See [postgres.md](postgres.md) (includes public DNS/IP SSL allowlisting, `[LFF-12]`, `[LFF-13]`, `[LFF-15]`).
- **MySQL / Cloud SQL**: See [mysql.md](mysql.md) (includes `GTID_MODE` and binlog retention rules).
- **Redis / Memorystore**: See [redis.md](redis.md) (includes `RIOT-X` seed and cache stampede strategies).
- **S3 / GCS Storage Transfer**: See [s3.md](s3.md) (includes Storage Transfer Service incremental sync).
- **Kafka / MSK Strimzi**: See [kafka.md](kafka.md) (includes MirrorMaker 2 and consumer offset translation).
- **Secrets Manager / Secret Manager**: See [secrets.md](secrets.md) (includes External Secrets Operator bindings).
- **DynamoDB / AlloyDB Re-platforming**: See [dynamodb.md](dynamodb.md) (covers heterogeneous moves).

### Step 2 — Co-existence connectivity

If the GKE workload needs to call back to the AWS data system during co-existence (and vice versa), plan:
- VPN or Cloud Interconnect between AWS VPC and GCP VPC.
- Allow-list updates to source data systems' security groups (allow GCP CIDRs).
- TLS / network policy parity.
- Bandwidth budget: project peak data movement at the planned co-existence window. Surface costs explicitly.

### Step 3 — Per-system runbook with explicit gates

For each system, render a runbook (use `templates/runbook-template.md`) with:
- Pre-flight checklist.
- Cutover steps with expected commands and outputs.
- Validation gate after each step.
- Rollback procedure for each step (linking to `rollback-playbook`).
- Decommission steps and timing.

### Step 4 — Drive the migration (with explicit confirmation)

For each system:
1. Surface the full runbook to the user. Ask explicit confirmation: "Begin replication for `prod-payments-db`? Estimated initial sync: 4–6 hours. Cost: $X."
2. On confirmation, execute step-by-step. After each step, run the validation gate. If a gate fails, stop, do not proceed.
3. Log every command executed and its output to `10-data-migration/<system>/execution.log`.

The agent never destructively modifies the source. The agent never bypasses a failed gate.

## Decision points

| Decision | Default | When to deviate |
|---|---|---|
| Postgres / MySQL replication tool | DMS | `pglogical` native if DMS network constraints |
| Redis seed strategy | Rebuildable → empty target; durable → snapshot import | Online tail-based replication for true zero-downtime |
| S3 → GCS engine | Storage Transfer Service | gsutil/`gcloud storage` for one-shot, small datasets |
| MSK target | Confluent Cloud on GCP | Self-managed Kafka if cost or operator is fluent |
| DynamoDB target | Out of scope; re-platform project | (No default) |
| Soak duration on source | 14 days read-only | 7 days for non-prod, longer for tier-0 |

## Outputs / Deliverables

```
10-data-migration/
├── plan.md                       # Index of all systems
├── <system-1>/
│   ├── runbook.md
│   ├── pre-flight-checks.md
│   ├── execution.log              # Filled in during execution
│   ├── validation-gates.md
│   └── rollback.md                # Links into rollback-playbook
├── <system-2>/
└── escalations.md
```

## Validation

For each system, the cutover gate criteria must be defined and met before declaring complete:
- **Postgres / MySQL**: replication lag < target SLA for ≥ 5 min, row counts match for top 10 tables, sample row hashes match.
- **Redis**: target writeable + readable, app smoke tests pass on cached paths.
- **S3 → GCS**: object count matches, sample hashes match, lifecycle rules verified active on GCS.
- **Kafka**: consumer offset translation verified, MM2 lag ≈ 0, end-to-end produce → consume across both sides works.

## Escalation triggers

- Heterogeneous data store moves (DynamoDB, Aurora→AlloyDB, Neptune, Redshift→BigQuery). Surface as scoping requirements.
- Datasets where the time-to-replicate exceeds the user's available window.
- Encryption key migrations that cannot reuse a CMEK approach (HSM-only key material). Surface for KMS planning.
- Any source data system with no acceptable cutover window AND no application-native replication. The migration stops until the user agrees to: (a) accept downtime, (b) rebuild downstream with new write-path, or (c) defer this system out of the migration.

## Common pitfalls

- **Egress during co-existence routinely runs 5–10× the unbudgeted estimate.** Model it explicitly per-workload at assessment time and monitor near-real-time during execution. See [LFF-01](../../reference/lessons-from-the-field.md#lff-01--egress-during-co-existence-routinely-runs-510-the-unbudgeted-estimate).
- **Cross-cloud bulk transfer over open internet bottlenecks at default Linux TCP buffers.** Tune `net.ipv4.tcp_{r,w}mem` before measuring throughput; otherwise you'll mis-time the cutover window. See [LFF-11](../../reference/lessons-from-the-field.md#lff-11--zfs-send-over-wan-bottlenecks-at-30-mbs-on-default-linux-tcp-buffers).
- **Cloud SQL connection methods.** Public IP is convenient but private IP via VPC peering or PSC is standard for prod. Use [Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/connect-auth-proxy) sidecar or Workload Identity-aware connector.

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Database Migration Service overview](https://cloud.google.com/database-migration/docs).
- [Storage Transfer Service](https://cloud.google.com/storage-transfer/docs).
- [storage-translation](../storage-translation/SKILL.md) — provides StorageClass, in-cluster volume strategies.
- [traffic-cutover](../traffic-cutover/SKILL.md) — sequences workload + data cutovers.
- [rollback-playbook](../rollback-playbook/SKILL.md) — gates failing during data migration cutover.
- [docs/glossary.md](../../docs/glossary.md) — service map.
