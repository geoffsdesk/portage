# Heterogeneous Database Re-Platforming (DynamoDB, Aurora to AlloyDB)

## Prerequisites

- Identification of heterogeneous target architecture (e.g., DynamoDB to Cloud Spanner/Bigtable/Firestore, or Aurora MySQL/Postgres to AlloyDB with significant engine/feature changes).

## Procedure

### 1. Scope & Escalation
Heterogeneous database moves represent architectural re-platforming rather than homogeneous data migration. `data-migration` treats these as formal **escalations** and requires a dedicated scoping note before handing execution back to the user or a separate modernization project.

### 2. DynamoDB Re-Platforming Guidelines
When moving off DynamoDB, select the target engine based on data model and SLA requirements:
- **Cloud Bigtable**: Best for high-throughput, low-latency key-value / wide-column workloads without complex secondary index transactions.
- **Cloud Spanner**: Best for workloads requiring global consistency, relational SQL queries, and transactional ACID guarantees across secondary indexes.
- **Cloud Firestore**: Best for document-oriented web/mobile backends with real-time sync and flexible schema models.

Migration path:
1. Export DynamoDB table to S3 (`ExportTableToPointInTime`).
2. Transfer S3 export files to GCS using Storage Transfer Service ([s3.md](s3.md)).
3. Run Dataflow / Apache Beam import pipeline transforming JSON/Parquet items into Bigtable mutations or Spanner `INSERT` statements.
4. Implement dual-writes or application-level CDC (DynamoDB Streams to Pub/Sub via Lambda) during co-existence.

### 3. Aurora / RDS to AlloyDB for PostgreSQL
While AlloyDB is 100% PostgreSQL-compatible, moving from standard RDS/Aurora to AlloyDB involves specific storage and cache tier tuning:
1. Use Database Migration Service (DMS) for continuous logical CDC replication (`[postgres.md](postgres.md)`).
2. Tune AlloyDB columnar engine flags (`google_columnar_engine.enabled`) and adaptive memory sizing post-cutover.
3. Conduct full performance and load regression testing before promoting AlloyDB to production primary.

## Validation

- Scoping document signed off by application architecture owners.
- End-to-end data parity verified on imported datasets before initiating dual-write or CDC cutover.

## Common pitfalls

- **Assuming 1:1 Query Parity on NoSQL**: DynamoDB query patterns and partition keys do not map 1:1 to Bigtable or Spanner without careful key schema redesign.
- **Egress on Bulk DynamoDB Exports**: S3 exports and stream forwarding across clouds must be accounted for in the egress budget (`[LFF-01]`).

## References

- [Migrating from DynamoDB to Cloud Spanner](https://cloud.google.com/architecture/migrating-dynamodb-to-spanner)
- [Google Cloud AlloyDB for PostgreSQL Documentation](https://cloud.google.com/alloydb/docs)
