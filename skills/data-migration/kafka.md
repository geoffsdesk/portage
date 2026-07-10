# Amazon MSK to GCP Kafka Migration

## Prerequisites

- Assessment of existing MSK topic configuration, partition counts, replication factors, and consumer group offset offsets.
- Target Kafka environment identified (Confluent Cloud on GCP or self-managed Strimzi Kafka on GKE).

## Procedure

### 1. Select Target Platform
- **Confluent Cloud on GCP (Recommended Default)**: Fully managed enterprise Kafka on GCP infrastructre.
- **Self-Managed Strimzi on GKE**: Kubernetes-native Kafka operator running inside dedicated nodepools (`gke-landing-zone`).

### 2. Topic & Schema Replication
- Provision destination topics with matching partition counts and retention configurations.
- If Schema Registry is used, export schemas from AWS Glue / Confluent Schema Registry and import to target destination.

### 3. Continuous Mirroring via MirrorMaker 2 (MM2)
- Deploy Apache Kafka MirrorMaker 2 (or Confluent Replicator) bridging MSK to GCP Kafka over Cross-Cloud Interconnect (`[LFF-01]`).
- Enable topic data mirroring, consumer group offset synchronization (`sync.group.offsets.enabled = true`), and topic configuration synchronization.

### 4. Cutover Sequence
1. Stop Kafka producers on EKS; allow consumers to drain remaining messages in MSK topics until consumer lag hits zero.
2. Verify MM2 has replicated the final offset batches to GCP Kafka.
3. Repoint producer and consumer bootstrap server endpoints in GKE ConfigMaps/Secrets (`workload-translation`).
4. Restart consumers on GKE using the translated consumer group offsets.

## Validation

- End-to-end produce and consume smoke test passes on target GCP Kafka cluster.
- MirrorMaker 2 consumer offset translation table verified (`offset-syncs` topic).
- Zero message loss during producer cutover window.

## Common pitfalls

- **Consumer Offset Translation**: Source topic offsets (`MSK`) do not numerically equal target topic offsets (`GCP`) due to log cleaning and compression. Consumer groups must use MM2's translated offset mappings rather than raw numeric offsets.
- **Egress Costs**: Continuous CDC mirroring across clouds for high-throughput topics incurs heavy per-GB internet egress without a Cross-Cloud Interconnect circuit (`[LFF-01]`).

## References

- [Apache Kafka MirrorMaker 2 Documentation](https://kafka.apache.org/documentation/#mirrormaker)
- [Strimzi Kafka Operator on Kubernetes](https://strimzi.io/documentation/)
- [reference/lessons-from-the-field.md](../../reference/lessons-from-the-field.md#lff-01--egress-during-co-existence-routinely-runs-510-the-unbudgeted-estimate)
