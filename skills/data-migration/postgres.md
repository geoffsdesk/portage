# PostgreSQL to Cloud SQL for PostgreSQL Migration

## Prerequisites

- IAM permissions for `dms:*` on source AWS and `cloudsql.admin` on GCP.
- **Egress Sign-Off**: Section 7 of `readiness-report.md` signed off using `egress_estimator.py` (`[LFF-01]`).
- Source RDS parameter group access or source Postgres superuser/logical replication privileges.

## Procedure

Grounded in [DMS — configure Postgres source](https://docs.cloud.google.com/database-migration/docs/postgres/configure-source-database) and [DMS — Postgres known limitations](https://docs.cloud.google.com/database-migration/docs/postgres/known-limitations).

### 1. Source RDS Parameter Group
Create a new parameter group, attach to the instance, and restart:
- `shared_preload_libraries` includes `pglogical`.
- `rds.logical_replication = 1` (RDS-managed; enables WAL at `logical` level — do NOT also set `wal_level = logical` directly on RDS).
- `wal_sender_timeout = 0`.
- `max_replication_slots` ≥ (DBs being migrated × concurrent migration jobs) + existing usage. Default is 10.
- `max_wal_senders` ≥ `max_replication_slots` + existing senders.
- `max_worker_processes` ≥ DBs being migrated + existing usage.

### 2. Per-Database Setup
On every database (except `template0`, `template1`, `rdsadmin`):
```sql
CREATE EXTENSION IF NOT EXISTS pglogical;
```

### 3. User Privileges
On each database, for every schema other than `information_schema` and any beginning with `pg_`:
```sql
GRANT USAGE  ON SCHEMA <schema>          TO <migration_user>;
GRANT USAGE  ON SCHEMA pglogical         TO PUBLIC;
GRANT SELECT ON ALL TABLES    IN SCHEMA pglogical  TO <migration_user>;
GRANT SELECT ON ALL TABLES    IN SCHEMA <schema>   TO <migration_user>;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA <schema>   TO <migration_user>;
```
For RDS specifically (`ALTER USER ... WITH REPLICATION` does not apply):
```sql
GRANT rds_replication TO <migration_user>;
```

### 4. Network Reachability & SSL Allowlisting
The source must be reachable by DMS:
- **Public IP / DNS Source**: Use IP Allowlist. Obtain the AWS RDS global SSL trust bundle before connecting:
  ```bash
  curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
  ```
- **Private IP Source**: Use Private IP (VPC peering). Enable the **Service Networking API** (`servicenetworking.services.addPeering`, `compute.networkAdmin`).

### 5. Provision Cloud SQL Target via DMS Wizard
- Type: `New instance`. Set `postgres` admin password in wizard.
- Edition: Cloud SQL for PostgreSQL Enterprise (or Enterprise Plus).
- Connectivity: For source with public IP/DNS use IP Allowlist (with `global-bundle.pem`). For source with private IP use Private IP via VPC peering.
- Storage ≥ source DB size.
- Encryption: Google-managed default, or CMEK (`projects/<p>/locations/<l>/keyRings/<kr>/cryptoKeys/<k>`).

### 6. Tables Without Primary Keys
Only initial snapshot and `INSERT` statements migrate during CDC. `UPDATE` and `DELETE` must be migrated manually. Add a PK or follow docs workarounds.

### 7. Initial Snapshot & Continuous CDC
Validate row counts per table; sample row hashes match. Monitor replication lag — target lag < 30 s for 5 minutes before cutover.

### 8. Cutover Window
1. Stop writers on EKS app side (drain).
2. Wait for replication lag = 0.
3. Promote target. Disable replication.
4. Repoint app config to Cloud SQL connection string.
5. **Re-enable point-in-time recovery and re-apply custom backup settings** (DMS resets these during promotion).
6. Execute smoke tests on target.

### 9. Soak & Decommission
Keep RDS read-only for 14 days as rollback before decommissioning.

## Validation

- Replication lag < 30 s for 5 minutes pre-cutover.
- Row count parity per critical table and random sample hash checks match.
- Zero errors in target Cloud SQL log for 30 minutes pre-cutover.

## Common pitfalls

- **Cloud SQL hides behind Google-controlled VPC peering** and routes do *not* propagate through a second peering hop (`[LFF-12]`). Co-locate or use Private Service Connect; do not plan a transit-VPC hop. See [LFF-12](../../reference/lessons-from-the-field.md#lff-12--cloud-sql-hides-behind-google-controlled-vpc-peering-blocking-second-hop-route-propagation).
- **DMS new-instance flow only supports VPC peering for private IP** (`[LFF-13]`). If PSC is required, pre-create the Cloud SQL instance and migrate to it. See [LFF-13](../../reference/lessons-from-the-field.md#lff-13--cloud-sql-dms-new-instance-flow-only-supports-vpc-peering-for-private-ip).
- **Postgres replication slots can vanish silently** on managed-DB failover (`[LFF-15]`), causing CDC consumers to lose rows. Monitor slot existence + lag continuously during cutover. See [LFF-15](../../reference/lessons-from-the-field.md#lff-15--postgres-replication-slots-can-be-dropped-silently-on-managed-db-failover).
- **Missing extensions or pg_cron**: `pg_cron` settings do not migrate (`cron` table). Re-install and re-schedule after promotion.

## References

- [DMS — configure Postgres source (RDS)](https://docs.cloud.google.com/database-migration/docs/postgres/configure-source-database)
- [DMS — Postgres known limitations](https://docs.cloud.google.com/database-migration/docs/postgres/known-limitations)
- [reference/lessons-from-the-field.md](../../reference/lessons-from-the-field.md)
