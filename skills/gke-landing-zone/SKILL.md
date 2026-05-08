---
name: gke-landing-zone
description: Design and stand up the GCP target environment for an EKS migration: project hierarchy, Shared VPC, fleet, GKE cluster(s), org policies, baseline IAM, observability, and budget. Produces Terraform plus a written design doc. Use when starting Phase 2 of a Portage migration, when "we need a GKE landing zone", "design the GCP target environment", or "set up the GKE clusters to migrate to".
---

# GKE Landing Zone

You are a GCP landing-zone architect. Design the target GCP environment, generate Terraform that materializes it, and produce a one-page architecture doc. You do not apply Terraform yourself — you produce the plan and hand it to a human.

## Purpose

Stand up a production-grade GKE target environment (project hierarchy, Shared VPC, fleet, clusters, org policy, baseline IAM, observability, billing budget) so the rest of Portage has somewhere to land workloads.

## When to use this skill

- Phase 2 of a Portage migration.
- A user asks for a "GKE landing zone", "GCP foundation for our K8s estate", or "set up the target environment".
- After `migration-assessment` produced a phased plan and is now ready for design.

Do NOT use to "create one cluster" — for ad-hoc cluster creation, point at the GKE quickstart instead. This skill produces a *foundation*.

## Prerequisites

- `00-orchestrator-state.json` with target GCP organization, billing account, target folder.
- `02-assessment/scorecard.json` and `readiness-report.md`.
- The user has Org Admin or has delegated the relevant Org-level roles to the agent operator.
- `gcloud` and `terraform` >= 1.6 installed locally.
- A bootstrap GCP project (or willingness to create one) for Terraform state.

## Procedure

### Step 1 — Confirm the design inputs

Confirm with the user (in 4–6 question batches via AskUserQuestion):

1. **Cluster topology**: Autopilot vs Standard per environment; regional vs zonal; release channel (Rapid / Regular / Stable). Default: Autopilot Regional Stable for prod, Standard Regional Regular for non-prod with custom node pools.
2. **Fleet model**: one fleet per environment (recommended) or one fleet across environments.
3. **Network topology**: Shared VPC (recommended) or service-project-local VPC.
4. **Private cluster**: private nodes + private endpoint (recommended) vs public endpoint with authorized networks.
5. **Identity**: Workforce Identity Federation (which provider) vs existing IAM users (no IdP).
6. **Org policy baseline**: deny default external IPs, deny non-CMEK disks (if compliance requires), require Shielded VMs, restrict allowed images.

### Step 2 — Project hierarchy

Plan and emit Terraform for:

```
Org
├── Folder: prod
│   ├── Project: net-prod-host       (Shared VPC host)
│   ├── Project: gke-prod-clusters   (GKE control planes)
│   ├── Project: data-prod           (Cloud SQL, Memorystore)
│   └── Project: obs-prod            (Cloud Monitoring scoping project)
├── Folder: nonprod
│   ├── Project: net-nonprod-host
│   ├── Project: gke-nonprod-clusters
│   └── Project: data-nonprod
└── Folder: shared
    ├── Project: artifact-registry   (centralized registries)
    ├── Project: cicd                (Cloud Build, Cloud Deploy)
    └── Project: terraform-state     (the bootstrap project)
```

Per project: enable APIs (`container.googleapis.com`, `compute.googleapis.com`, `iam.googleapis.com`, `iamcredentials.googleapis.com`, `cloudresourcemanager.googleapis.com`, `serviceusage.googleapis.com`, `logging.googleapis.com`, `monitoring.googleapis.com`, `gkehub.googleapis.com`, `anthos.googleapis.com` if fleet, `artifactregistry.googleapis.com`, `cloudkms.googleapis.com`, `secretmanager.googleapis.com`).

### Step 3 — Shared VPC

For each environment host project, plan:

- Subnets per region with secondary ranges for pods and services. Default sizing: nodes /22, pods /16, services /20. Adjust per environment scale.
- Cloud NAT in each region for egress.
- Cloud Router per region.
- Hierarchical firewall policies for the org-level baseline (deny inbound public, allow IAP, allow GFE health-check ranges).
- VPC firewall rules per environment.
- Private Google Access on every subnet.
- Private Service Connect endpoints for `googleapis.com` if private clusters require it.

Sample HCL skeleton (full module in `assets/landing-zone-tf/`):

```hcl
resource "google_compute_network" "shared" {
  project                 = var.host_project
  name                    = "${var.env}-shared"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "gke" {
  for_each = var.regions
  project  = var.host_project
  name     = "gke-${each.key}"
  region   = each.key
  network  = google_compute_network.shared.id
  ip_cidr_range = each.value.nodes_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = each.value.pods_cidr
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = each.value.services_cidr
  }
}
```

### Step 4 — GKE clusters

Per environment cluster, plan:

```hcl
resource "google_container_cluster" "primary" {
  project  = var.cluster_project
  name     = "${var.env}-primary"
  location = var.region                     # regional cluster

  # Use the existing Shared VPC
  network    = "projects/${var.host_project}/global/networks/${var.network}"
  subnetwork = "projects/${var.host_project}/regions/${var.region}/subnetworks/${var.subnet}"

  # Private cluster
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = true
    master_ipv4_cidr_block  = var.master_cidr
  }
  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.authorized_networks
      content { cidr_block = cidr_blocks.value }
    }
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Workload Identity
  workload_identity_config {
    workload_pool = "${var.cluster_project}.svc.id.goog"
  }

  # Dataplane V2 (eBPF)
  datapath_provider = "ADVANCED_DATAPATH"
  network_policy { enabled = false }   # Dataplane V2 implements policy natively

  release_channel { channel = var.release_channel }

  # Logging & monitoring
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS","WORKLOADS","API_SERVER","SCHEDULER","CONTROLLER_MANAGER"]
  }
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS","API_SERVER","SCHEDULER","CONTROLLER_MANAGER","STORAGE","HPA","POD","DAEMONSET","DEPLOYMENT","STATEFULSET","CADVISOR","KUBELET"]
    managed_prometheus { enabled = true }
  }

  # Gateway API
  gateway_api_config { channel = "CHANNEL_STANDARD" }

  # Binary Authorization (where in scope)
  binary_authorization { evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE" }

  # Database encryption with CMEK
  database_encryption {
    state    = "ENCRYPTED"
    key_name = var.kms_key_id
  }

  remove_default_node_pool = true
  initial_node_count       = 1

  deletion_protection = true
}
```

For Standard clusters, also define node pools with: COS_CONTAINERD image, Shielded VMs, secure boot, integrity monitoring, surge upgrade strategy, taints/labels mirrored from Karpenter discovery, autoscaling bounds matching the EKS baseline +20% headroom.

For Autopilot, omit node pools. Pin the `release_channel`, set Workload Identity, Gateway API, Binary Authorization (where in scope), CMEK.

### Step 5 — Fleet registration

```hcl
resource "google_gke_hub_membership" "primary" {
  project       = var.fleet_host_project
  membership_id = google_container_cluster.primary.name
  endpoint {
    gke_cluster {
      resource_link = "//container.googleapis.com/${google_container_cluster.primary.id}"
    }
  }
}

resource "google_gke_hub_feature" "configmanagement" {
  project = var.fleet_host_project
  name    = "configmanagement"
  location = "global"
}
```

Enable the fleet features the readiness report identified: Config Management (for Config Sync), Multi-Cluster Ingress (if applicable), Anthos Service Mesh (if App Mesh was in use), Policy Controller (if you use OPA Gatekeeper today), Identity Service (for IdP integration).

### Step 6 — Baseline IAM

Define groups via the IdP (do not create individual users in GCP):

- `gcp-org-admins@…` — Org Admin, Folder Admin (break-glass).
- `gcp-platform-admins@…` — project owner on platform projects, network admin on host project.
- `gcp-platform-readers@…` — project viewer org-wide.
- `gcp-sre-prod@…` — Container Cluster Admin on prod cluster project, log/monitoring viewer.
- `gcp-developers-<env>@…` — limited container.developer + custom role with namespace-scoped admin via RBAC binding.

Bind via Terraform with `google_project_iam_binding` (authoritative) at the project level for non-overlapping roles, and `google_project_iam_member` (additive) where multi-source bindings exist.

### Step 7 — Org policy baseline

```hcl
resource "google_org_policy_policy" "external_ip" {
  name   = "organizations/${var.org_id}/policies/compute.vmExternalIpAccess"
  parent = "organizations/${var.org_id}"
  spec { rules { deny_all = "TRUE" } }
}

resource "google_org_policy_policy" "shielded_vm" {
  name   = "organizations/${var.org_id}/policies/compute.requireShieldedVm"
  parent = "organizations/${var.org_id}"
  spec { rules { enforce = "TRUE" } }
}

resource "google_org_policy_policy" "trusted_image" {
  name   = "organizations/${var.org_id}/policies/compute.trustedImageProjects"
  parent = "organizations/${var.org_id}"
  spec {
    rules {
      values {
        allowed_values = [
          "projects/cos-cloud",
          "projects/gke-node-images",
        ]
      }
    }
  }
}
```

Apply also: `iam.allowedPolicyMemberDomains` (lock to your org's domain), `compute.disableSerialPortAccess`, `storage.uniformBucketLevelAccess`, `iam.disableServiceAccountKeyCreation` (use Workload Identity).

### Step 8 — Observability

In each `obs-<env>` project, create a metrics scope that aggregates the cluster project. Create a Cloud Monitoring workspace, default dashboards for each cluster, baseline alerting policies (apiserver SLO burn-rate, node CPU/mem saturation, pod CrashLoopBackOff rate, image-pull failure rate). Use Managed Service for Prometheus by default; do not stand up self-managed Prometheus unless the user explicitly wants Grafana parity with self-host.

### Step 9 — Budgets

For each env folder, plan a `google_billing_budget` at 50% / 80% / 100% of the user's stated cost ceiling, with notifications to the platform team. Add a per-project budget for the cluster project specifically — that's where most cost shows up.

### Step 10 — Output the design doc

Render `03-landing-zone/plan.md` from `templates/landing-zone-design.md`. One page per environment, with:

- ASCII diagram of project hierarchy + Shared VPC + clusters.
- Table of cluster facts (Autopilot/Standard, region, channel, node pools, sizing).
- IAM groups and their roles.
- Org policy state.
- Budget thresholds.

### Step 11 — Hand off the Terraform

```
03-landing-zone/
├── plan.md
├── terraform/
│   ├── envs/
│   │   ├── prod/main.tf
│   │   └── nonprod/main.tf
│   ├── modules/
│   │   ├── shared-vpc/
│   │   ├── gke-cluster/
│   │   ├── fleet/
│   │   └── orgpolicy/
│   └── README.md   # how to plan/apply
└── apply-log.md     # populated when the human applies
```

Run `terraform plan` in dry-run mode and capture the output. Do not run `apply`. Surface the plan to the user with a 5-line summary: "creates 4 projects, 2 networks, 4 clusters, 12 IAM bindings, 3 org policies. Budget: $X/mo per env. Apply when ready."

## Decision points

| Decision                           | Default                     | When to deviate                                  |
|------------------------------------|-----------------------------|--------------------------------------------------|
| Autopilot vs Standard              | Autopilot for prod stateless | Standard if you need DaemonSets requiring node-level access, custom node taints with privileged, GPU/TPU, or Spot at >50% of cluster capacity |
| Regional vs zonal                  | Regional                    | Zonal only for non-prod ephemeral test clusters  |
| Private endpoint                   | Yes (private endpoint)      | Public endpoint with authorized networks if there's no VPN/peering yet and the team needs immediate access |
| One fleet vs many                  | Per-environment fleet       | Single fleet only for very small estates         |
| CMEK on cluster DB                 | Yes                         | No CMEK only if no compliance requirement and the cost is unjustified |
| Binary Authorization               | Enabled (allow-all policy initially) | Enabled with attestor enforcement after `registry-migration` is complete |

## Outputs / Deliverables

```
03-landing-zone/
├── plan.md                # Design doc, human-readable
├── design-decisions.md    # Every decision with rationale
├── terraform/             # Modular Terraform
└── apply-log.md           # Filled in by the human after apply
```

## Validation

Before declaring landing zone ready:

- `terraform plan` runs clean (no errors, no unexpected destroys).
- All clusters reachable from the operator's network (private endpoint via VPN/IAP, or public via authorized networks).
- `kubectl get ns` succeeds against each cluster.
- Workload Identity pool is enabled on each cluster (`gcloud container clusters describe` shows `workloadIdentityConfig.workloadPool`).
- Dataplane V2 is enabled (`datapathProvider: ADVANCED_DATAPATH`).
- Gateway API CRDs are installed (`kubectl get crd gateways.gateway.networking.k8s.io`).
- Logs flow to Cloud Logging within 2 minutes of the first deploy.
- Org policies are inherited by all environment projects (`gcloud org-policies list --project ...`).
- Billing budget alerts have at least one notification channel each.

## Escalation triggers

- The user's compliance scope requires a setting Portage cannot validate against public guidance (e.g., FedRAMP High control mapping). Stop and produce a compliance gap doc.
- The Shared VPC plan conflicts with an existing on-prem CIDR — surface for user routing decision.
- Org policy `iam.allowedPolicyMemberDomains` would lock out an existing identity already needed for cross-cloud automation. Surface and stage the rollout.

## Common pitfalls

- **Sizing pod CIDRs too small.** /16 is the default for a reason. /22 sounds plenty until you autoscale.
- **Forgetting Private Service Connect.** Private clusters without PSC for `googleapis.com` will time out on SDK calls.
- **Default node SA has too much.** The default Compute SA has Editor. Replace with a least-privileged dedicated SA per cluster (logs writer, monitoring writer, AR reader).
- **Missing `deletion_protection`.** Set `deletion_protection = true` on every prod cluster. It has saved more than one weekend.
- **One fleet to rule them all.** Tempting for small teams but conflates blast radius. Per-env fleets.
- **Plan a Cloud SQL transit-VPC hop and find routes don't propagate.** Cloud SQL hides behind a Google-controlled peering and routes don't traverse a second peering. Co-locate, or use Private Service Connect endpoints. See [LFF-12](../../reference/lessons-from-the-field.md#lff-12--cloud-sql-hides-behind-google-controlled-vpc-peering-blocking-second-hop-route-propagation).
- **Quota blocks at apply time.** A regional GKE node pool needs ~300 GB SSD by default; default per-minute API quotas throttle multi-resource Terraform applies. Pre-check quotas, request increases ahead, and lower `parallelism` on the apply. See [LFF-37](../../reference/lessons-from-the-field.md#lff-37--regional-gke-node-pools-need-300-gb-ssd-by-default-and-trip-initial-regional-quotas) and [LFF-38](../../reference/lessons-from-the-field.md#lff-38--default-per-minute-api-quotas-throttle-terraform-on-multi-resource-gke-upgrades).
- **Spotify-style "delete all clusters" is a real failure mode.** Declarative IaC + per-namespace Backup-for-GKE + multi-cluster posture is the tested DR pattern. See [LFF-31](../../reference/lessons-from-the-field.md#lff-31--spotify-accidentally-deleted-all-their-kubernetes-clusters-with-no-user-impact--the-canonical-dr-case-study).

## Canonical hardening controls

This section grounds the design defaults above against [Hardening your cluster's security](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/hardening-your-cluster) — the canonical Google reference. Every default in this skill should match a row below, or be labeled tool-opinionated. When the table conflicts with the prose above, the table wins.

### Controls — apply at cluster creation (mostly immutable)

| # | Control | Default | Recommended | Autopilot enforces |
|---|---|---|---|---|
| 1 | Use a custom IAM service account for nodes (not the default Compute Engine SA) | Default Compute Engine SA | Custom least-privileged SA per cluster | No (still required) |
| 2 | Container-Optimized OS node image | COS default in Standard | "use the Container-Optimized OS node image for your nodes" | Yes (only supported) |
| 3 | Shielded GKE Nodes (secure boot + integrity monitoring) | On in Autopilot; on by default in Standard | "enable Shielded GKE Nodes, secure boot, and integrity monitoring in all clusters and node pools" | Yes |
| 4 | Disable kubelet read-only port (10255) | Disabled by default on newer versions | "disable the kubelet read-only port and switch any workloads that use port 10255 to use the more secure port 10250 instead" | Yes |
| 5 | Workload Identity Federation for GKE | On in Autopilot; off in Standard | "enable Workload Identity Federation for GKE for all clusters and node pools" | Yes |

### Controls — applied during the design

| # | Control | Default | Recommended | Notes |
|---|---|---|---|---|
| 6 | Restrict access to the control plane | External endpoint reachable | "enable the DNS-based endpoint for control plane access and disable all IP-based control plane endpoints" | Configure during cluster create |
| 7 | Isolate nodes from the internet | Nodes have external IPs | "enable private nodes" | `enable_private_nodes = true` in our module |
| 8 | Restrict Pod-to-Pod traffic | All allowed | "control Pod-to-Pod network traffic by using NetworkPolicies, a service mesh, or both" | Dataplane V2 enforces |
| 9 | Restrict anonymous access to cluster endpoints | `system:anonymous` allowed; denied by default on 1.35.0-gke.1171000+ on new clusters | "specify LIMITED for the --anonymous-authentication-config flag" | Configure for older versions |
| 10 | Plan multi-tenant namespaces / clusters | Single default namespace | "creating separate namespaces or clusters for each team and environment" | Per-environment fleets is our default |
| 11 | Use Shared VPC | Off | "use Shared VPC to let resources in multiple projects communicate ... by using internal IP addresses" | Default on in our design |
| 12 | Separate VPC networks per environment | Off | "use separate Shared VPC networks for staging, test, and production environments" | Per-environment host project default |
| 13 | Least-privilege firewall rules | GKE default rules created | "use the principle of least privilege ... ensure that your firewall rules don't conflict with, or override, the GKE default firewall rules" | No "allow all ingress for debugging" — Google calls this out by name |
| 14 | Use tags to group GCP resources for conditional policy | Off | "use tags to organize GKE resources for conditional policy enforcement" | Apply at folder/project level |

### Controls — operational hygiene

| # | Control | Default | Recommended | Notes |
|---|---|---|---|---|
| 15 | RBAC least privilege | Default permissive | "design and implement good RBAC policies to reduce the risk of unauthorized access from workloads" | Per-namespace RBAC; SA-bound roles |
| 16 | Use groups (not individuals) for access | Off | "give permissions to groups of users instead of to individuals" | Federated groups in our IAM design |
| 17 | Org Policy Service for hierarchical constraints | Off | "use Organization Policy Service" | Our org-policy block enforces this |
| 18 | Admission control (Policy Controller or PodSecurity) | Off | "use an admission controller like Policy Controller or the PodSecurity admission controller" | PSA `baseline` enforced; `restricted` warned at minimum |
| 19 | Enroll in a release channel + accelerated patch auto-upgrades | Control plane auto-upgrade on; node auto-upgrade default-on | "Enroll your clusters in a release channel ... enable accelerated patch auto-upgrades ... enable automatic node upgrades" | `release_channel` set in our module |
| 20 | Security bulletin notifications | Off | "configure notifications for new security bulletins that affect your cluster" via Pub/Sub | Add Pub/Sub notification channel |
| 21 | Log collection (don't disable on Standard) | System/workload + Kubernetes audit + GKE audit logs sent by default | "implement a consistent logging strategy ... Don't disable log collection in your Standard clusters" | Our cluster module enables full logging |
| 22 | GKE security posture dashboard + Security Command Center | Off | "use the GKE security posture dashboard and Security Command Center" | Enable in `obs-<env>` project |
| 23 | Store secrets outside the cluster | K8s Secrets in Spanner-backed etcd (encrypted at rest by default) | "use an external secret manager like Secret Manager to store sensitive data" | External Secrets Operator → Secret Manager |
| 24 | GKE Sandbox for untrusted workloads | Off | "use GKE Sandbox to prevent malicious code from affecting the host kernel on your cluster nodes" | Apply selectively, not as a baseline |
| 25 | Confidential GKE Nodes (memory encryption in use) | Off | "Use hardware-based memory encryption ... by using Confidential GKE Nodes" | Apply when in compliance scope |

### Defaults Google says **leave alone**

These are on by default; verify in the cluster spec, do not disable.

- Legacy API server authentication methods (static certs/passwords) — disabled by default; **don't enable ABAC**.
- ABAC — disabled by default; never re-enable.
- `DenyServiceExternalIPs` admission controller — enabled by default on clusters created on GKE 1.21+; **don't disable**. Mitigates GCP-2020-015.

### Anti-patterns Google explicitly calls out (do NOT do these)

1. Don't create permissive higher-priority firewall rules that override GKE defaults — example given: a rule that "allows all ingress traffic for debugging."
2. Don't use the Compute Engine default service account for nodes; it "might have more permissions than GKE needs."
3. Don't use the node service account for application workloads — that SA "should be used only by system workloads." Use Workload Identity Federation.
4. Don't disable Shielded GKE Nodes, secure boot, or integrity monitoring.
5. Don't use the kubelet read-only port (10255).
6. Don't rely on the anonymous-authentication restriction alone to secure the cluster.
7. Don't distribute Google Cloud credentials to workloads when client libraries can use Workload Identity Federation.
8. Don't store secrets in Kubernetes Secrets if you can avoid it. Anyone able to create Pods in a namespace, or with read access to API objects, can read them.
9. Don't run third-party secret tools in the same cluster as your workloads.
10. Don't enable ABAC.
11. Don't enable legacy API server authentication methods.
12. Don't disable the `DenyServiceExternalIPs` admission controller.
13. Don't disable log collection on Standard clusters.
14. Don't treat default API discovery roles as a security boundary — `system:authenticated` includes "anyone with a Google account."
15. Don't leave external IP-based control plane endpoints enabled unless paired with strict authorized networks; prefer DNS-based endpoint only.
16. Don't leave nodes with external IP addresses.

The hardening checklist `gke-landing-zone` produces in `03-landing-zone/hardening.md` walks every row above with status, evidence (`gcloud` command + expected value), and the link to the canonical doc.

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md) — source map for the whole library.
- [Hardening your cluster's security](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/hardening-your-cluster) — the source for the table above.
- [Migrate from Amazon EKS to GKE (Architecture Center)](https://docs.cloud.google.com/architecture/migrate-amazon-eks-to-gke) — the matching migration series.
- [Cloud Foundation Fabric](https://github.com/GoogleCloudPlatform/cloud-foundation-fabric) — Google's reference Terraform; our `reference/terraform/modules/` is structurally aligned with Fabric's.
- [docs/glossary.md](../../docs/glossary.md) — service map.
- [reference/terraform/](../../reference/terraform/) — reusable HCL modules.
- [network-translation](../network-translation/SKILL.md) — consumes the network plan.
- [identity-translation](../identity-translation/SKILL.md) — consumes the IAM groups.
