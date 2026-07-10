# MySQL to Cloud SQL for MySQL Migration

## Prerequisites

- Supported source versions: Amazon RDS / Aurora MySQL 5.6, 5.7, 8.0, 8.4.
- Source parameter group modifications and binlog access.

## Procedure

Grounded in [DMS — configure MySQL source](https://docs.cloud.google.com/database-migration/docs/mysql/configure-source-database) and [DMS — MySQL known limitations](https://docs.cloud.google.com/database-migration/docs/mysql/known-limitations).

### 1. Source Flags / Parameter Group
- `server-id`: Set to 1 or larger.
- `GTID_MODE`: `ON` or `OFF`. **`ON_PERMISSIVE` is not supported by DMS** — check your RDS defaults. Must be `ON` if migrating to a destination with read replicas.
- Binary logging enabled in **`ROW`-format**. Configuring to `STATEMENT` or `MIXED` causes replication to fail.
- Binlog retention set to 168 hours (7 days, the RDS maximum):
  ```sql
  call mysql.rds_set_configuration('binlog retention hours', 168);
  ```

### 2. Migration User & Privileges
- Configure user host as `'%'`.
- **Password ≤ 32 characters**: MySQL replication limitation (MySQL Bug #43439). Longer passwords silently break.
- For MySQL 8.0+, user must **not** have `BACKUP_ADMIN`.

Privileges required by migration type:
| Type | Privileges |
|---|---|
| Continuous + managed dump | `REPLICATION SLAVE`, `EXECUTE`, `SELECT`, `SHOW VIEW`, `REPLICATION CLIENT`, `RELOAD`, `TRIGGER`; plus `LOCK TABLES` for RDS/Aurora. |
| Continuous + manual dump | `REPLICATION SLAVE`, `EXECUTE`. |
| One-time + managed dump | `SELECT`, `SHOW VIEW`, `TRIGGER`; plus `LOCK TABLES` for RDS/Aurora; plus `RELOAD` if `GTID_MODE = ON`. |

### 3. Storage Engine & DDL Constraints
- All tables (except system DBs) must use **InnoDB**. MyISAM may cause data inconsistency.
- Stop all DDL writes during the full-dump phase. DDL may resume once continuous CDC begins.
- Cannot migrate from an Aurora *read replica* — binlogs are not retrievable from replicas.

### 4. Provision Target & Cutover
- Target: Cloud SQL for MySQL Enterprise (or Enterprise Plus).
- For cross-version 8.0 → 8.4 migrations: destination must have `local_infile = ON`.
- Cutover: drain source writers, wait for zero CDC lag, promote Cloud SQL, repoint application endpoints, and hold source read-only during soak window.

## Validation

- Replication lag < target SLA for ≥ 5 minutes pre-cutover.
- Row counts and sample row hash verification across InnoDB tables.
- System schemas (`mysql`, `performance_schema`, `information_schema`, `sys`) excluded cleanly without app breakages.

## Common pitfalls

- **`GTID_MODE = ON_PERMISSIVE`**: RDS defaults often use `ON_PERMISSIVE`. Change explicitly to `ON` before creating the DMS job.
- **MySQL 5.7.36 mysqldump bug**: Do not use `mysqldump` from MySQL 5.7.36 for manual dumps (`Bug #105761`).
- **Data-dump locking**: Data-dump parallelism briefly locks the source (100 tables ≈ 1 s, 50K ≈ 49 s). Use a read replica for the initial dump if locking primary is unacceptable.

## References

- [DMS — configure MySQL source](https://docs.cloud.google.com/database-migration/docs/mysql/configure-source-database)
- [DMS — MySQL known limitations](https://docs.cloud.google.com/database-migration/docs/mysql/known-limitations)
- [Migrate from Amazon RDS / Aurora MySQL to Cloud SQL for MySQL](https://docs.cloud.google.com/architecture/migrate-aws-rds-to-sql-mysql)
