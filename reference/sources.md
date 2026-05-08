# Canonical Sources

The authoritative external references the Portage skills lean on. Each skill's References section links here. When a skill cites a specific page, that page appears in this file too — the skill links to the canonical doc and to the Portage sub-section that summarizes our use of it.

If a recommendation in Portage cannot be cited from one of these sources (or from a skill's own first-hand exercise of an environment), it is *tool-opinionated* and labeled as such. We never present Portage's heuristics as Google guidance.

> **Pinning note.** GCP doc URLs occasionally change as products are renamed or pages are restructured (e.g., "Workload Identity" → "Workload Identity Federation for GKE"). When a link 404s, search the page title — the canonical content usually still exists at a new URL. PR welcome to update.

---

## A — Headline migration sources

| Source | URL | Where Portage uses it |
|---|---|---|
| Migrate from AWS to Google Cloud: **Migrate from Amazon EKS to GKE** (Architecture Center series) | https://docs.cloud.google.com/architecture/migrate-amazon-eks-to-gke | Whole orchestrator, plus discovery / assessment / data-migration |
| Migrate containers to Google Cloud: Migrate from Kubernetes to GKE | https://docs.cloud.google.com/architecture/migrating-containers-kubernetes-gke | workload-translation, storage-translation |
| Migrate from Amazon RDS / Aurora MySQL to Cloud SQL for MySQL | https://docs.cloud.google.com/architecture/migrate-aws-rds-to-sql-mysql | data-migration |
| Migrate your EKS attached cluster (alternative path: attach EKS as a fleet member, migrate workloads incrementally) | https://cloud.google.com/kubernetes-engine/multi-cloud/docs/attached/eks/how-to/migrate-cluster | portage-orchestrator (alternative discovery path) |
| What's new in the Architecture Center | https://cloud.google.com/architecture/release-notes | (general — watch for updates) |
| Brain Corp migrates from AWS EKS to GKE Autopilot (Google Cloud Blog) | https://cloud.google.com/blog/products/containers-kubernetes/brain-corp-migrates-from-aws-eks-to-gke-autopilot | examples/walkthrough.md (real-world precedent) |

## B — Foundations and landing zone

| Source | URL | Where Portage uses it |
|---|---|---|
| Hardening your cluster's security | https://docs.cloud.google.com/kubernetes-engine/docs/how-to/hardening-your-cluster | gke-landing-zone (the 34 controls fold in directly) |
| Best practices for enterprise organizations | https://cloud.google.com/architecture/best-practices-for-enterprise-organizations | gke-landing-zone (project hierarchy, IAM patterns) |
| Landing zone design in Google Cloud | https://cloud.google.com/architecture/landing-zones | gke-landing-zone |
| Cloud Foundation Fabric (Google reference Terraform, GitHub) | https://github.com/GoogleCloudPlatform/cloud-foundation-fabric | reference/terraform/ — patterns inspired by Fabric |
| GKE security posture dashboard | https://cloud.google.com/kubernetes-engine/docs/concepts/about-security-posture-dashboard | gke-landing-zone, post-migration-ops |
| Setting up clusters with Shared VPC | https://cloud.google.com/kubernetes-engine/docs/how-to/cluster-shared-vpc | gke-landing-zone |
| GKE Autopilot vs Standard | https://cloud.google.com/kubernetes-engine/docs/concepts/choose-cluster-mode | gke-landing-zone (decision points) |

## C — Networking, ingress, edge

| Source | URL | Where Portage uses it |
|---|---|---|
| GKE Gateway controller | https://cloud.google.com/kubernetes-engine/docs/concepts/gateway-api | network-translation |
| Choosing a load balancer | https://cloud.google.com/load-balancing/docs/choosing-load-balancer | network-translation |
| Cloud Armor preconfigured WAF rules | https://docs.cloud.google.com/armor/docs/waf-rules | network-translation (verbatim rule names + tuning) |
| Cloud Armor rule tuning (sensitivity / paranoia levels) | https://docs.cloud.google.com/armor/docs/rule-tuning | network-translation |
| Cloud Armor adaptive protection | https://docs.cloud.google.com/armor/docs/adaptive-protection-overview | network-translation |
| Certificate Manager | https://cloud.google.com/certificate-manager/docs | network-translation |
| Cloud DNS routing policies | https://cloud.google.com/dns/docs/zones/manage-routing-policies | network-translation, traffic-cutover |
| Private Service Connect | https://cloud.google.com/vpc/docs/private-service-connect | gke-landing-zone, network-translation |

## D — Identity

| Source | URL | Where Portage uses it |
|---|---|---|
| Workload Identity Federation for GKE | https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity | identity-translation |
| Workload Identity Federation with AWS or Azure (cross-cloud) | https://cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds | identity-translation (Step 4: cross-cloud federation) |
| Best practices for using service accounts | https://cloud.google.com/iam/docs/best-practices-for-using-and-managing-service-accounts | identity-translation, gke-landing-zone |

## E — Workloads and admission

| Source | URL | Where Portage uses it |
|---|---|---|
| Autopilot resource requests/limits | https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-resource-requests | workload-translation (the deny list) |
| Pod Security Standards on GKE | https://cloud.google.com/kubernetes-engine/docs/how-to/podsecurityadmission | workload-translation |
| Removed Kubernetes APIs by version | https://kubernetes.io/docs/reference/using-api/deprecation-guide/ | workload-translation (manifest validity) |
| Policy Controller | https://cloud.google.com/anthos-config-management/docs/concepts/policy-controller | post-migration-ops |
| Binary Authorization | https://cloud.google.com/binary-authorization/docs | registry-migration, post-migration-ops |

## F — Storage

| Source | URL | Where Portage uses it |
|---|---|---|
| Persistent Disk types | https://cloud.google.com/compute/docs/disks/persistent-disks | storage-translation |
| Hyperdisk overview | https://cloud.google.com/compute/docs/disks/hyperdisks | storage-translation |
| Filestore tiers | https://cloud.google.com/filestore/docs/service-tiers | storage-translation |
| Parallelstore | https://cloud.google.com/parallelstore/docs | storage-translation |
| Backup for GKE | https://cloud.google.com/kubernetes-engine/docs/add-on/backup-for-gke | storage-translation, data-migration |
| Migrate stateful workloads to GKE | https://cloud.google.com/architecture/best-practices-stateful-applications-gke | storage-translation, data-migration |

## G — Registry and supply chain

| Source | URL | Where Portage uses it |
|---|---|---|
| Artifact Registry overview | https://cloud.google.com/artifact-registry/docs | registry-migration |
| Artifact Analysis (vulnerability scanning) | https://cloud.google.com/artifact-analysis/docs | registry-migration |
| Sigstore + Binary Authorization on GKE | https://cloud.google.com/binary-authorization/docs/setting-up-cosign | registry-migration |
| SLSA framework | https://slsa.dev | registry-migration (supply-chain references) |

## H — Data

| Source | URL | Where Portage uses it |
|---|---|---|
| Database Migration Service overview | https://cloud.google.com/database-migration/docs | data-migration |
| DMS — configure Postgres source (RDS) | https://docs.cloud.google.com/database-migration/docs/postgres/configure-source-database | data-migration (verbatim pre-flight) |
| DMS — configure MySQL source (RDS) | https://docs.cloud.google.com/database-migration/docs/mysql/configure-source-database | data-migration (verbatim pre-flight) |
| DMS — Postgres known limitations | https://docs.cloud.google.com/database-migration/docs/postgres/known-limitations | data-migration |
| DMS — MySQL known limitations | https://docs.cloud.google.com/database-migration/docs/mysql/known-limitations | data-migration |
| Storage Transfer Service | https://cloud.google.com/storage-transfer/docs | data-migration |
| Cloud SQL HA / DR | https://cloud.google.com/sql/docs/postgres/high-availability | data-migration |
| AlloyDB migration guide | https://cloud.google.com/alloydb/docs/migration | data-migration (engine change scoping) |

## I — Observability

| Source | URL | Where Portage uses it |
|---|---|---|
| Managed Service for Prometheus | https://cloud.google.com/stackdriver/docs/managed-prometheus | observability-translation |
| Migrating from CloudWatch to Cloud Operations | https://cloud.google.com/architecture/migration-to-google-cloud-monitoring-from-cloudwatch | observability-translation (metric-name table) |
| SLO monitoring | https://cloud.google.com/stackdriver/docs/solutions/slo-monitoring | observability-translation, post-migration-ops |
| Cloud Trace + OpenTelemetry on GKE | https://cloud.google.com/trace/docs/setup/opentelemetry | observability-translation |
| OpenTelemetry on GCP | https://cloud.google.com/stackdriver/docs/instrumentation/setup | observability-translation |

## J — Cutover, reliability, SRE

| Source | URL | Where Portage uses it |
|---|---|---|
| The SRE Workbook (free online) | https://sre.google/workbook/table-of-contents/ | traffic-cutover, rollback-playbook (canary, error budgets, postmortems) |
| Site Reliability Engineering (book, free online) | https://sre.google/sre-book/table-of-contents/ | (cross-cutting reliability principles) |
| Anthos Service Mesh multi-cluster | https://cloud.google.com/service-mesh/docs/managed/multi-cluster | traffic-cutover (mesh routing path) |
| GKE Gateway traffic splitting | https://cloud.google.com/kubernetes-engine/docs/how-to/gateway-traffic-splitting | traffic-cutover |

## K — FinOps / cost optimization

| Source | URL | Where Portage uses it |
|---|---|---|
| **Best practices for running cost-optimized Kubernetes applications on GKE** (canonical) | https://docs.cloud.google.com/architecture/best-practices-for-running-cost-effective-kubernetes-applications-on-gke | post-migration-ops (verbatim methodology) |
| About Vertical Pod Autoscaling | https://docs.cloud.google.com/kubernetes-engine/docs/concepts/verticalpodautoscaler | post-migration-ops (OOM safety buffer) |
| Configuring HPA | https://cloud.google.com/kubernetes-engine/docs/how-to/horizontal-pod-autoscaling | post-migration-ops |
| Cluster autoscaler | https://cloud.google.com/kubernetes-engine/docs/how-to/cluster-autoscaler | post-migration-ops |
| Node auto-provisioning | https://cloud.google.com/kubernetes-engine/docs/how-to/node-auto-provisioning | gke-landing-zone, post-migration-ops |
| Spot VMs on GKE | https://cloud.google.com/kubernetes-engine/docs/how-to/spot-vms | post-migration-ops |
| Compute Engine committed-use discounts | https://cloud.google.com/compute/docs/instances/signing-up-committed-use-discounts | post-migration-ops |
| CUD analysis | https://cloud.google.com/billing/docs/how-to/cud-analysis | post-migration-ops |

## L — Outside cloud.google.com

| Source | URL | Where Portage uses it |
|---|---|---|
| Kubernetes Gateway API | https://gateway-api.sigs.k8s.io/ | network-translation |
| Kubernetes NetworkPolicy | https://kubernetes.io/docs/concepts/services-networking/network-policies/ | network-translation, post-migration-ops |
| Pod Security Admission | https://kubernetes.io/docs/concepts/security/pod-security-admission/ | workload-translation |
| Cilium / Dataplane V2 | https://cilium.io/ | network-translation, gke-landing-zone |
| Strimzi (Kafka on K8s) | https://strimzi.io/ | data-migration (self-managed Kafka path) |
| Velero | https://velero.io/ | storage-translation |
| AWS EKS user guide | https://docs.aws.amazon.com/eks/latest/userguide/ | eks-discovery (source-side accuracy) |
| Karpenter docs | https://karpenter.sh/docs/ | eks-discovery, workload-translation |

---

## What this file is *not*

- Not a substitute for reading the linked docs. Each skill cites the *page* that grounds its recommendations; the page is the source of truth.
- Not a list of every page on cloud.google.com. Only pages Portage actually uses.
- Not curated for completeness over time. PRs to add or correct entries are welcome; see CONTRIBUTING.md.

## See also

- [lessons-from-the-field.md](lessons-from-the-field.md) — companion knowledge base of practitioner war stories and incident reports. Where this file documents canonical *guidance*, that file documents what has *actually broken* in real migrations. Both inform the skills.
