# ElastiCache Redis to Memorystore for Redis Cluster Migration

## Prerequisites

- Inventory of ElastiCache Redis topology (Cluster Mode Enabled/Disabled, shards, replicas, persistence requirements).
- Target `data-prod` project in GCP with Memorystore API enabled.

## Procedure

### 1. Evaluate Cache Strategy
Determine if the cache dataset is **rebuildable** or **durable**:
- **Rebuildable (Sessions, Ephemeral Caches)**:
  1. Provision target Memorystore for Redis Cluster matching shard sizing.
  2. Leave target empty prior to cutover.
  3. At cutover, repoint application endpoints to Memorystore.
  4. Plan for cache warm-up and protect downstream DBs against thundering herd.
- **Durable (Counters, Rate-Limit State, Queues)**:
  1. Use open-source `RIOT-X` (or Redis `MIGRATE`/`REPLICATE` tools) to run an online initial seed + tail-based replication across VPC peering/Interconnect.
  2. Alternatively, perform a brief write freeze on ElastiCache, export an RDB snapshot to S3/GCS, and import the `.rdb` file into Memorystore (`gcloud redis clusters import`).

### 2. Provision Memorystore for Redis Cluster
- Match shard count and capacity to source peak memory + 30% headroom.
- Enable transit encryption (TLS) and auth strings if required by application security policies.

### 3. Cutover Sequence
1. Drain write traffic on EKS application.
2. If using `RIOT-X` continuous CDC, wait for lag to hit zero.
3. Repoint application environment variables / ConfigMaps (`identity-translation` & `workload-translation`) to the Memorystore cluster endpoint.
4. Verify cache hit ratios and latency.

## Validation

- Memorystore cluster reports `READY` status.
- Smoke tests verify write and read operations across all shard slots.
- No `OOM command not allowed` errors during initial warm-up load.

## Common pitfalls

- **Cache stampede at cutover**: Empty Memorystore + cold app = thundering herd on primary database. Plan a shadow warm-up phase or rate-limit cache rebuilds.
- **Cluster Mode vs Non-Cluster Mode mismatch**: Ensure client libraries (e.g., Jedis, `go-redis`) are configured correctly for `Cluster` topology vs standalone/sentinel endpoints.

## References

- [Google Cloud Memorystore for Redis Cluster Documentation](https://cloud.google.com/memorystore/docs/cluster)
- [RIOT - Redis Input/Output Tools](https://github.com/redis/riot)
