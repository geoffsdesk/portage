---
name: storage-translation
description: Translate EKS storage to GKE: StorageClasses (ebs.csi.aws.com → pd.csi.storage.gke.io, efs.csi.aws.com → filestore.csi.storage.gke.io), PVC/PV mappings, snapshot strategies for stateful workloads, and data-mover plans for online migration. Produces translated StorageClass YAML, snapshot plans, and a per-PVC migration runbook. Use when "translate storage", "EBS to PD", "migrate PVCs to GKE", or "plan stateful workload move" in a Portage migration.
---

# Storage Translation

You translate the storage layer: StorageClasses, PVCs, PVs, and the data movement plan for each stateful workload. You do not move data yourself — that's `data-migration`. You produce the design, the StorageClass set, and the per-PVC handoff.

## Purpose

Map every EBS / EFS / FSx volume and every StorageClass to a GKE equivalent and produce the snapshot or live-replication plan that `data-migration` will execute.

## When to use this skill

- Phase 3, after `gke-landing-zone`.
- The user asks to "translate storage", "convert StorageClasses", "plan stateful workload migration".

## Prerequisites

- `01-discovery/inventory.json` storage section (PVs, PVCs, StorageClasses, EBS volumes, EFS file systems).
- Target GKE clusters from `03-landing-zone`.

## Procedure

### Step 1 — Translate StorageClasses

For each source StorageClass:

| Source provisioner / params                         | Target StorageClass                             |
|-----------------------------------------------------|-------------------------------------------------|
| `ebs.csi.aws.com` + `type: gp3`                     | `pd.csi.storage.gke.io` + `type: pd-balanced`   |
| `ebs.csi.aws.com` + `type: io2`                     | `pd.csi.storage.gke.io` + `type: hyperdisk-extreme` (SSD-class workloads) |
| `ebs.csi.aws.com` + `type: gp2` (legacy)            | `pd.csi.storage.gke.io` + `type: pd-balanced`   |
| `ebs.csi.aws.com` + `type: st1`                     | `pd.csi.storage.gke.io` + `type: pd-standard`   |
| `efs.csi.aws.com` + `provisioningMode: efs-ap`      | `filestore.csi.storage.gke.io` (Filestore Enterprise for high throughput, Basic for low) |
| `fsx.csi.aws.com` (Lustre)                          | `parallelstore.csi.storage.gke.io`              |
| `fsx-netapp-ontap.csi.aws.com`                      | `netapp.csi.storage.gke.io` (NetApp Volumes)    |

Sample translated `StorageClass`:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3-encrypted
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: pd.csi.storage.gke.io
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
parameters:
  type: pd-balanced
  disk-encryption-kms-key: projects/data-prod/locations/us-central1/keyRings/portage/cryptoKeys/disk
  csi.storage.k8s.io/fstype: ext4
```

Always set `volumeBindingMode: WaitForFirstConsumer` — it prevents pods from being scheduled to a zone where their PD doesn't exist.

### Step 2 — Per-PVC migration plan

For each PVC in `inventory.json`:

Capture:
- Owning workload (StatefulSet / Deployment).
- Current size, access modes, current usage.
- Underlying volume type (EBS gp3 / io2 / EFS / FSx).
- Snapshot capability (already snapshotted? interval?).
- RPO/RTO targets from the readiness report.

Produce a per-PVC plan with one of these strategies:

#### Strategy A — Cold migration via backup tool (Velero)

Best for: workloads with an acceptable downtime window, no replication tooling, simple snapshot/restore semantics.

```bash
# On EKS
velero backup create payments-pvc-${TS} \
  --include-namespaces payments \
  --include-resources persistentvolumes,persistentvolumeclaims \
  --selector app=payments

# Mirror backup bucket to GCS
gcloud storage cp -r s3://velero-prod gs://portage-velero-prod

# On GKE
velero restore create payments-pvc-${TS} \
  --from-backup payments-pvc-${TS} \
  --namespace-mappings payments:payments
```

Velero's CSI snapshotter cannot directly translate EBS → PD. Use the data-mover pattern: Velero packages PV contents into the object store, restore re-creates a PD-backed PV with the same data.

#### Strategy B — Block-level replication (pre-cutover sync)

Best for: high-volume workloads where downtime is small and copy time is large.

1. Create the target PV+PVC on GKE pinned to a temporary "shadow" pod with `dd`/`rsync`/`pgpv-replication`-class tooling.
2. Initial sync: copy from EKS-side snapshot (exported to object storage as image) into the GKE PD via a one-shot Job.
3. Incremental sync: depends on workload (database WAL shipping, application-level replication).
4. At cutover: stop EKS workload, do final delta sync, mount to the target StatefulSet.

Produce per-workload Job manifests for the sync.

#### Strategy C — Application-native replication

Best for: databases. PostgreSQL streaming replication, MySQL binlog replication, MongoDB replica set additions, Redis replicas. The "PVC" in that case never literally moves; the data does.

This crosses into `data-migration`. `storage-translation` simply notes "Strategy C — handled by data-migration" for these PVCs and links to the data-migration plan.

#### Strategy D — Object-storage-fronted (re-platform)

Best for: workloads that *could* use object storage but happen to use a PVC for caching. Replace the PVC with a `gcsfuse`-mounted bucket via the GCS Fuse CSI driver. This is a re-platform decision and surfaces as an escalation.

#### Strategy E — RWX (multi-pod read-write)

Best for: workloads using EFS access points across many pods.

- Identify per-AP usage patterns and pod counts.
- Map to Filestore Enterprise (recommended) or NetApp Volumes (when you need NetApp APIs).
- For very high IOPS / many-pod scale-out, evaluate Parallelstore.
- Produce a migration plan: provision Filestore, copy contents via `gcsfuse` intermediate or DataSync (cross-cloud), cut over.

### Step 3 — Snapshot, retention, and DR

For each migrated PVC:

1. Plan a `VolumeSnapshotClass` and snapshot schedule on GKE matching the existing EKS schedule.
2. Verify CMEK encryption parity. If EKS volumes were encrypted with a KMS key, the GKE PVs use the equivalent Cloud KMS key declared in the StorageClass.
3. Plan cross-region DR if the EKS workload had cross-region snapshot copying — use Backup for GKE for application-level backups including PVCs.

### Step 4 — Validate sizing

GKE Persistent Disks have minimum sizes (e.g., `pd-balanced` minimum 10 GiB; performance scales with size). If a source PVC is smaller than the GKE minimum, request the user's confirmation before bumping size. Do not silently change sizes.

### Step 5 — Stateful workload pre-cutover dry-run

For at least one representative stateful workload per class (DB, queue, file share):

1. Stand up a non-prod copy of the workload on GKE with the translated StorageClass and a small PV.
2. Restore a recent snapshot.
3. Run the workload's smoke tests.
4. Capture the timing: snapshot copy, restore, mount-to-ready latency.

This timing feeds `traffic-cutover`'s window calculation.

### Step 6 — Output

```
07-storage-translation/
├── storage-design.md
├── manifests/
│   ├── storageclasses/
│   ├── volumesnapshotclasses/
│   └── filestores/             # Filestore instance manifests where applicable
├── pvc-plans/
│   └── <namespace>-<pvc>.md    # Per-PVC strategy and runbook
├── terraform/
│   └── filestore.tf            # Filestore / Parallelstore as TF where appropriate
└── escalations.md
```

## Decision points

| Decision                                | Default                       | When to deviate                              |
|-----------------------------------------|-------------------------------|----------------------------------------------|
| Default block disk type                 | `pd-balanced`                 | `hyperdisk-extreme` for io2 + IOPS-bound; `pd-standard` for st1 |
| RWX target                              | Filestore Enterprise          | NetApp Volumes if NetApp APIs are required; Parallelstore for HPC |
| Migration strategy default              | Velero backup/restore (Strategy A) | App-native replication (C) for databases |
| Filesystem (`fstype`)                   | `ext4`                        | `xfs` only when source is xfs and required |
| Snapshot retention parity               | Match EKS schedule            | Tighten if compliance requires |

## Outputs / Deliverables

```
07-storage-translation/
├── storage-design.md
├── manifests/
├── pvc-plans/
├── terraform/
└── escalations.md
```

## Validation

- Every PVC in `inventory.json` has a `pvc-plans/<ns>-<pvc>.md` entry with a strategy.
- Every StorageClass referenced by any translated workload exists in `manifests/storageclasses/`.
- Provisioning a test PVC on GKE with the new StorageClass succeeds and produces a PV in the expected zone.
- `volumeBindingMode: WaitForFirstConsumer` on every translated SC.
- Snapshot/restore round-trip works for a representative PVC of each class.

## Escalation triggers

- PVC backed by storage with no clean GKE equivalent (FSx OpenZFS, certain Storage Gateway flavors).
- RWX usage that exceeds Filestore tier limits even at Enterprise.
- Workload with no acceptable downtime AND no application-native replication path. Surface; the user must choose between extending the cutover window, accepting downtime, or re-platforming.
- Volumes encrypted with externally-managed keys (e.g., HSM-backed KMS) where the GCP target uses CMEK with Cloud HSM and key import is not yet planned.

## Common pitfalls

- **Treating `gp2` as `pd-standard`.** It's not — gp2 is SSD. Use `pd-balanced`.
- **Forgetting `volumeBindingMode`.** Default `Immediate` causes PV provisioning at PVC creation time, often in the wrong zone.
- **Snapshot semantics.** EBS snapshots are incremental and account-scoped. PD snapshots are also incremental, but you can't directly import an EBS snapshot — you copy data.
- **EFS performance modes.** EFS Bursting → Filestore Basic; EFS Provisioned/Max IO → Filestore Enterprise or Parallelstore.
- **Quorum on stateful clusters.** When migrating Kafka, etcd, MongoDB, do *not* try to live-extend the quorum across clusters across clouds. Build a new quorum on GKE, replicate data, switch consumers.
- **Freshly provisioned PDs ship with a `lost+found` directory** that crashes Kafka log scanning. Mount via `subPath` for Kafka-class workloads. See [LFF-33](../../reference/lessons-from-the-field.md#lff-33--strimzi-kafka-statefulsets-race-with-multi-zone-gce-pd-mount-lostfound-via-subpath).
- **Stuck PVs at decommission time** are a known class of CSI finalizer race. Verify finalizer cleanup before destroying any source cluster. See [LFF-32](../../reference/lessons-from-the-field.md#lff-32--stuck-pvs--finalizer-races-at-decommissioning-time).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Persistent Disk types](https://cloud.google.com/compute/docs/disks/persistent-disks).
- [Hyperdisk overview](https://cloud.google.com/compute/docs/disks/hyperdisks).
- [Filestore tiers](https://cloud.google.com/filestore/docs/service-tiers).
- [Parallelstore](https://cloud.google.com/parallelstore/docs).
- [Backup for GKE](https://cloud.google.com/kubernetes-engine/docs/add-on/backup-for-gke).
- [Best practices for stateful applications on GKE](https://cloud.google.com/architecture/best-practices-stateful-applications-gke).
- [Velero](https://velero.io/) — cold-migration tool.
- [data-migration](../data-migration/SKILL.md) — runs the actual data move.
- [docs/glossary.md](../../docs/glossary.md) — storage service map.
