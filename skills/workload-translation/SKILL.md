---
name: workload-translation
description: Translate Kubernetes manifests, Helm charts, and Kustomize overlays from EKS conventions to GKE conventions. Rewrites AWS-specific annotations, replaces ALB Ingress with Gateway API, swaps ebs.csi.aws.com StorageClasses to pd.csi.storage.gke.io, fixes node selectors and tolerations, removes IRSA annotations in favor of Workload Identity, and produces a clean diff per workload. Use when "translate this Helm chart for GKE", "convert manifests to GKE", or after identity-translation in a Portage migration.
---

# Workload Translation

You translate Kubernetes manifests, Helm charts, and Kustomize overlays so they run unchanged on GKE. Every change is a tracked diff with a rationale.

## Purpose

Convert EKS-conventioned workload definitions to GKE-conventioned equivalents. Produce auditable per-workload diffs with rationale. Do not modify business logic.

## When to use this skill

- Phase 3 of a Portage migration.
- A user asks to "translate manifests", "convert this Helm chart", "make this work on GKE".

Do NOT use to change application code or container images (that's `registry-migration`).

## Prerequisites

- `01-discovery/inventory.json` and the raw workloads YAML.
- `04-network-translation/manifests/` for Gateway/HTTPRoute targets.
- `05-identity-translation/identity-map.json` for KSA → GSA mapping.

## Procedure

### Step 1 — Build a per-workload manifest set

For each workload, gather:

- The current YAML manifest (from discovery raw or from the source repo).
- The originating Helm chart and `values.yaml` (if Helm-managed).
- The originating Kustomize overlay (if Kustomize-managed).

For Helm:

```bash
helm get manifest <release> -n <ns> > <release>.rendered.yaml
helm get values <release> -n <ns> > <release>.values.yaml
helm get all <release> -n <ns> > <release>.helm-all.yaml
```

For Kustomize:

```bash
kubectl kustomize ./overlays/prod > overlays-prod.rendered.yaml
```

### Step 2 — Apply the translation rules

Walk every resource and apply rules. Each rule has a category (`drop`, `replace`, `add`, `rewrite`) and a rationale.

#### Annotations to drop

| Annotation                                                | Action |
|-----------------------------------------------------------|--------|
| `eks.amazonaws.com/role-arn` (on ServiceAccount)          | drop; replaced by `iam.gke.io/gcp-service-account` from identity-translation |
| `eks.amazonaws.com/compute-type: fargate`                 | drop; map workload to Autopilot if cluster is Autopilot |
| `kubernetes.io/ingress.class: alb`                        | drop; replaced by Gateway API resources |
| `alb.ingress.kubernetes.io/*`                             | drop; covered by Gateway/HTTPRoute/HealthCheckPolicy/GCPBackendPolicy |
| `service.beta.kubernetes.io/aws-load-balancer-*`          | drop; covered by Gateway API or `cloud.google.com/*` annotations |
| `external-dns.alpha.kubernetes.io/aws-*`                  | drop; replace external-dns config with Cloud DNS provider (handled in network-translation) |

#### Annotations to add

| Annotation                                                       | When |
|------------------------------------------------------------------|------|
| `iam.gke.io/gcp-service-account: <gsa-email>` (on ServiceAccount) | When KSA appears in identity-map |
| `cloud.google.com/load-balancer-type: "Internal"` (on LB Service) | For internal LBs replacing internal NLBs |
| `networking.gke.io/load-balancer-class: "regionalExternal"`       | For pass-through L4 external |
| `cloud.google.com/neg: '{"ingress": true}'`                       | For Services backing GKE Gateway |

#### Resource type swaps

| Source                                              | Target                              | Note |
|-----------------------------------------------------|-------------------------------------|------|
| `Ingress` (with `alb` class)                        | `Gateway` + `HTTPRoute`             | Take from `04-network-translation/manifests/` |
| `Service type=LoadBalancer` annotated for AWS NLB   | Same `Service`, swap annotations    | Don't change kind; rewrite the annotation set |
| `StorageClass` with `provisioner: ebs.csi.aws.com`  | `provisioner: pd.csi.storage.gke.io`| Rewrite parameters per `storage-translation` |
| `StorageClass` with `provisioner: efs.csi.aws.com`  | `provisioner: filestore.csi.storage.gke.io` | Rewrite per storage-translation |
| `EndpointSlice` with `addressType: IPv4` referencing AWS DNS LB | Reuse                              | No change |
| `MutatingWebhookConfiguration` for `aws-pod-identity-webhook` | drop                              | Pod identity injection is native on GKE |

#### `nodeSelector` / `tolerations` / `affinity`

Map common EKS labels to GKE labels:

| EKS                                                              | GKE                                                           |
|------------------------------------------------------------------|---------------------------------------------------------------|
| `eks.amazonaws.com/nodegroup: <ng>`                              | `cloud.google.com/gke-nodepool: <pool>`                       |
| `node.kubernetes.io/instance-type: m5.large`                     | `node.kubernetes.io/instance-type: e2-standard-2` (or actual GCE) |
| `topology.kubernetes.io/zone: us-east-1a`                        | `topology.kubernetes.io/zone: us-central1-a` (target region) |
| `karpenter.sh/capacity-type: spot`                               | `cloud.google.com/gke-spot: "true"`                           |
| `karpenter.sh/nodepool: gpu`                                     | matched node pool with the same labels (created in landing zone) |
| Bottlerocket-specific selectors                                  | drop; COS-only on GKE |

For Karpenter NodePools: do not translate the NodePool resource. Instead, build the equivalent **GKE Node Pools** in the landing zone with the labels and taints captured during discovery. Then `nodeSelector`s in workloads continue to match.

#### Topology spread

`topologySpreadConstraints` mostly translate unchanged. Validate that `topologyKey: topology.kubernetes.io/zone` works against GKE's regional cluster zones.

#### Resource requests/limits

Translate verbatim. If targeting Autopilot, validate against [Autopilot resource ranges](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests). Workloads outside the ranges either need to move to a Standard cluster or have requests rounded to allowed values. Surface as escalation, do not silently round.

#### `hostPath`, `hostNetwork`, `hostPID`

- `hostPath` referencing AWS-specific paths (`/var/lib/kubelet/plugins/...`) — usually applies only to CSI/CNI-level DaemonSets. Validate per workload.
- `hostNetwork: true` — preserve unchanged. Confirms with discovery escalation list.
- `hostPID: true` — preserve unchanged.

In Autopilot clusters: `hostNetwork`, `hostPID`, `hostPath`, and most privileged options are **denied**. Workloads using them must run on a Standard cluster or be redesigned. This is an escalation, not a silent translation.

#### Pod Security

EKS cluster defaults rarely enforce PSA. GKE Autopilot enforces `restricted` by default. Standard clusters can configure PSA.

For each namespace:

1. Set `pod-security.kubernetes.io/enforce: baseline` (start) or `restricted` (target).
2. Validate every workload manifest against the chosen level. Workloads that fail are surfaced as escalations with a list of violating fields.

#### Image references

Rewrite image refs to point at Artifact Registry equivalents (output of `registry-migration`):

```
123456789012.dkr.ecr.us-east-1.amazonaws.com/payments/api:1.4.2
→
us-central1-docker.pkg.dev/artifact-registry-prod/payments/api:1.4.2
```

Use the mapping file `08-registry-migration/image-map.json` produced by `registry-migration`. If a workload references an image not yet in that map, surface as an escalation rather than guessing.

### Step 3 — Helm-specific translation

For each Helm release in scope:

1. If the chart is publicly maintained and offers GKE-compatible values, switch values rather than the chart.
2. Produce a delta `values.yaml` with only the changed keys, named `values.gke.yaml`. Examples:

```yaml
# values.gke.yaml — overrides for GKE
serviceAccount:
  annotations:
    iam.gke.io/gcp-service-account: payments-api@gke-prod-clusters.iam.gserviceaccount.com

ingress:
  enabled: false   # using Gateway API resources instead

gateway:
  enabled: true
  className: gke-l7-global-external-managed
  hostnames:
    - api.example.com

persistence:
  storageClass: pd-balanced

nodeSelector:
  cloud.google.com/gke-nodepool: payments
```

3. If the chart is internal and embeds AWS assumptions in templates, fork the chart, mark the fork with a `MIGRATION_NOTES.md` documenting every template change, and store under `06-workload-translation/charts/<chart>-gke/`.

### Step 4 — Kustomize-specific translation

For each Kustomize root:

1. Add a new overlay `overlays/gke-prod/`.
2. Use `patches:` to apply transformations rather than editing the base.
3. Where possible, build a `gke-common/` component (KSA annotations, NodePool selectors) that all GKE overlays import.

### Step 5 — Per-workload diff and rationale

For every workload, output a side-by-side diff and a rationale list:

```
# Workload: storefront/web
## Changes
| File                           | Before                                   | After                                   | Rationale |
|--------------------------------|------------------------------------------|-----------------------------------------|-----------|
| Deployment.spec.template…annotations | eks.amazonaws.com/skip-* removed | (removed)                                | EKS-only, no GKE equivalent |
| Deployment.spec.template…serviceAccount | (none)                          | web                                       | Needed for WI binding |
| ServiceAccount.metadata.annotations | eks.amazonaws.com/role-arn         | iam.gke.io/gcp-service-account: …         | identity-translation |
| Ingress (kind: Ingress)        | spec…                                    | DROPPED → see HTTPRoute web.yaml        | Gateway API |
| StorageClass: gp3              | provisioner: ebs.csi.aws.com             | provisioner: pd.csi.storage.gke.io      | storage-translation |
| Container.image                | …ecr…/web:1.2.0                          | …pkg.dev…/web:1.2.0                      | registry-migration |
| Tolerations / nodeSelector     | karpenter.sh/capacity-type: spot         | cloud.google.com/gke-spot: "true"        | node label mapping |
```

### Step 6 — Validate

For each workload:

```bash
# Lint
kubectl --dry-run=server apply -f 06-workload-translation/manifests/<workload>/

# Server-side dry-run with PSA enforcement
kubectl --dry-run=server apply --validate=strict -f ...

# Helm template validation
helm template release-name ./chart -f values.gke.yaml | kubectl --dry-run=server apply -f -
```

For Autopilot targets, also run:

```bash
gcloud container clusters describe <cluster> --location <region> \
  --format='value(autopilot.enabled)'
# If true: validate workloads don't use forbidden features.
```

## Decision points

| Decision                              | Default                          | When to deviate |
|---------------------------------------|----------------------------------|-----------------|
| Fork Helm chart vs values overlay     | Values overlay                   | Fork only when the chart blocks WI annotations or uses AWS-only resources |
| Convert Ingress to HTTPRoute now vs at cutover | At translation time             | At cutover if the user wants to ship Ingress first and Gateway later |
| Default PSA level                     | `baseline` enforced, `restricted` warned | `restricted` enforced if compliance requires |
| Spot tolerations                      | Translate `karpenter.sh/capacity-type=spot` to `cloud.google.com/gke-spot=true` | Preserve mixed-instance with affinity if cost-sensitive |

## Outputs / Deliverables

```
06-workload-translation/
├── manifests/                # Per-workload translated YAML
│   └── <namespace>/<workload>/
├── charts/                   # Forked Helm charts (only when forked)
├── values/                   # values.gke.yaml per release
├── kustomize/                # gke overlays
├── diffs/                    # Diff + rationale per workload (Markdown)
├── psa-violations.md         # Workloads that fail target PSA level
└── escalations.md
```

## Validation

- Every Deployment, StatefulSet, DaemonSet, Job, CronJob in `inventory.json` has a translated artifact OR is explicitly marked `intentionally-not-migrated` (e.g., AWS-only DaemonSet that has no GKE equivalent).
- `kubectl --dry-run=server` passes for every translated manifest against the target cluster.
- Every image reference matches an entry in `image-map.json`.
- Every KSA reference matches an entry in `identity-map.json`.
- Every StorageClass reference matches a translated StorageClass.

## Escalation triggers

- Workload uses an admission webhook that doesn't have a GKE-compatible version (e.g., `aws-pod-identity-webhook`, custom webhooks tied to AWS auth).
- Workload references a CRD whose operator isn't translated (still on EKS).
- Autopilot target with workloads outside resource bounds.
- Helm chart with templates that conditionally render AWS-only resources and don't have a flag to disable.

## Common pitfalls

- **Translating image refs by string-replace in YAML.** Some manifests embed images in non-obvious places (init containers, sidecars in CRD specs, JSON-encoded strings). Walk the entire YAML tree.
- **Forgetting CronJob backoff differences.** GKE Autopilot warns/denies certain CronJob configurations.
- **PodTopologySpread + cluster autoscaler.** Underprovisioned clusters with strict spread will leave pods Pending. Tune CA's max bounds first.
- **Operator CRDs missing.** If an operator (e.g., Postgres operator) is in EKS, you have to install it on GKE before its CRs apply. Surface in the workload-translation phase, not at apply time.
- **Karpenter NodePools do not translate to GKE.** Capture taints/labels and rebuild as GKE node pools (or NAP rules) in `gke-landing-zone`. The community Karpenter-on-GCP provider exists but is not production-ready. See [LFF-16](../../reference/lessons-from-the-field.md#lff-16--karpenter-on-gcp-exists-but-is-preview-grade-treat-the-parity-as-a-re-platform).
- **Workloads tuned to Karpenter's seconds-class scale-up will queue under NAP.** Increase HPA `minReplicas` and tune target utilization down for these workloads. See [LFF-17](../../reference/lessons-from-the-field.md#lff-17--salesforce-karpenter-migration-brought-scaling-latency-from-minutes-to-seconds).
- **App Mesh retirement.** App Mesh retires 2026-09-30; target for a GKE move is Cloud Service Mesh. See [LFF-29](../../reference/lessons-from-the-field.md#lff-29--app-mesh-is-retiring-2026-09-30-awss-own-path-is-vpc-lattice--ecs-service-connect--for-a-gke-move-the-target-is-cloud-service-mesh).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Autopilot resource requests/limits](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests) — the deny list for Autopilot.
- [Pod Security Standards on GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/podsecurityadmission).
- [Removed Kubernetes APIs by version](https://kubernetes.io/docs/reference/using-api/deprecation-guide/) — manifest validity check.
- [Migrate containers to Google Cloud: Migrate from Kubernetes to GKE](https://docs.cloud.google.com/architecture/migrating-containers-kubernetes-gke).
- [identity-translation](../identity-translation/SKILL.md)
- [storage-translation](../storage-translation/SKILL.md)
- [registry-migration](../registry-migration/SKILL.md)
- [reference/api-translation.md](../../reference/api-translation.md) — annotation-by-annotation map.
