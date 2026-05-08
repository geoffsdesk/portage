---
name: identity-translation
description: Translate EKS IRSA (IAM Roles for Service Accounts) bindings to GKE Workload Identity. Maps every annotated ServiceAccount to a Google Service Account, translates AWS IAM policies into the closest GCP IAM role set, produces additive bindings on both sides for co-existence, and emits a verification plan. Use after gke-landing-zone, when "translate IRSA to Workload Identity", "set up identity for the GKE migration", or "what's the identity plan".
---

# Identity Translation

You translate IRSA-bound ServiceAccounts into Workload Identity bindings, with both sides live during co-existence. You produce a per-binding plan: GSA, IAM roles, KSA annotation, validation.

## Purpose

Move every workload identity from AWS IAM (assumed via OIDC by IRSA) to GCP IAM (impersonated via Workload Identity), without breaking either side during the cutover. Keep the EKS bindings working until traffic-cutover removes them.

## When to use this skill

- Phase 2 of a Portage migration, after `gke-landing-zone` and in parallel with `network-translation`.
- The user asks for "IRSA to Workload Identity translation", "GKE identity plan", "how do my IAM roles map to GCP".

## Prerequisites

- `01-discovery/irsa-map.tsv` and the per-role IAM JSON exports.
- `03-landing-zone/plan.md` — confirms cluster Workload Identity pool and target project structure.
- IAM permissions in the GCP target projects to create service accounts and IAM bindings (`iam.serviceAccountAdmin`, `resourcemanager.projectIamAdmin`).

## Procedure

### Step 1 — Build the binding ledger

For each row in `irsa-map.tsv` (`namespace`, `ksa`, `role_arn`):

1. Read the IAM role's policies (attached + inline) from the discovery raw files.
2. Categorize each statement by *AWS service* (`s3`, `sqs`, `dynamodb`, `kms`, …) and *operations* (`Read`, `Write`, `Admin`, custom).
3. Map each AWS service to its target GCP service per `docs/glossary.md`.
4. Map each operation to the closest predefined GCP role (e.g., `s3:GetObject` → `roles/storage.objectViewer`; `s3:PutObject` → `roles/storage.objectUser`; `kms:Decrypt` → `roles/cloudkms.cryptoKeyDecrypter`).
5. For statements with no GCP analogue (the workload calls AWS APIs directly via SDK and will continue to call AWS APIs from GKE during co-existence), keep the AWS IAM role active and produce an *additive* AWS trust-policy entry that lets the GKE workload assume the role via Workload Identity Federation across clouds (see Step 4).

Produce `05-identity-translation/identity-map.json`:

```json
[
  {
    "ksa": { "namespace": "checkout", "name": "checkout" },
    "source": {
      "role_arn": "arn:aws:iam::123456789012:role/checkout",
      "policies": [
        { "statement_id": "S3", "actions": ["s3:GetObject","s3:PutObject"], "resources": ["arn:aws:s3:::shop-orders/*"] },
        { "statement_id": "SQS", "actions": ["sqs:SendMessage","sqs:ReceiveMessage"], "resources": ["arn:aws:sqs:us-east-1:...:order-events"] }
      ]
    },
    "target": {
      "gsa_email": "checkout@gke-prod-clusters.iam.gserviceaccount.com",
      "iam_bindings": [
        { "role": "roles/storage.objectUser", "resource": "projects/_/buckets/shop-orders" },
        { "role": "roles/pubsub.publisher",   "resource": "projects/data-prod/topics/order-events" },
        { "role": "roles/pubsub.subscriber",  "resource": "projects/data-prod/subscriptions/order-events-checkout" }
      ],
      "wi_binding": {
        "principal": "serviceAccount:gke-prod-clusters.svc.id.goog[checkout/checkout]",
        "role": "roles/iam.workloadIdentityUser"
      },
      "ksa_annotation": "iam.gke.io/gcp-service-account: checkout@gke-prod-clusters.iam.gserviceaccount.com"
    },
    "co_existence": {
      "keep_aws_role": true,
      "additional_trust": "OIDC: gke-prod-clusters.svc.id.goog/subject:ns/checkout/sa/checkout"
    },
    "validation": [
      "kubectl run -n checkout --rm -it --image=google/cloud-sdk:slim --serviceaccount=checkout test -- gcloud storage ls gs://shop-orders/",
      "kubectl run -n checkout --rm -it --image=amazon/aws-cli test -- aws s3 ls s3://shop-orders/"
    ]
  }
]
```

### Step 2 — Generate the GSAs and bindings

For each entry, emit Terraform:

```hcl
resource "google_service_account" "checkout" {
  project      = var.cluster_project
  account_id   = "checkout"
  display_name = "checkout — migrated from arn:aws:iam::123456789012:role/checkout"
  description  = "Workload Identity GSA for namespace checkout / sa checkout."
}

resource "google_storage_bucket_iam_member" "checkout_orders" {
  bucket = "shop-orders"
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.checkout.email}"
}

resource "google_pubsub_topic_iam_member" "checkout_publisher" {
  project = var.data_project
  topic   = "order-events"
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.checkout.email}"
}

resource "google_service_account_iam_member" "checkout_wi" {
  service_account_id = google_service_account.checkout.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.cluster_project}.svc.id.goog[checkout/checkout]"
}
```

Emit per-KSA YAML:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: checkout
  namespace: checkout
  annotations:
    iam.gke.io/gcp-service-account: checkout@gke-prod-clusters.iam.gserviceaccount.com
```

### Step 3 — Validate before deploying any workload

Run the validation commands from each entry. Common invocation pattern:

```bash
kubectl create ns checkout 2>/dev/null
kubectl -n checkout apply -f 05-identity-translation/manifests/sa-checkout.yaml
kubectl -n checkout run wi-test --rm -it --restart=Never \
  --image=google/cloud-sdk:slim \
  --overrides='{"spec":{"serviceAccountName":"checkout"}}' \
  -- gcloud auth list
# Expect: the GSA email to be the active account.
```

If `gcloud auth list` shows the node default SA instead of the GSA:

- Workload Identity pool is not enabled on the cluster (verify cluster setup).
- The KSA annotation is missing or has the wrong GSA email.
- The `roles/iam.workloadIdentityUser` binding is missing or member format is wrong.
- The pod's spec doesn't reference the KSA.

### Step 4 — Cross-cloud identity (during co-existence)

For workloads that must keep calling AWS APIs from GKE during co-existence (DynamoDB, Kinesis, IAM-protected S3 in another account), set up Workload Identity Federation in AWS:

1. Create an AWS IAM OIDC provider for the GKE cluster's workload pool URL: `https://container.googleapis.com/v1/projects/PROJECT_ID/locations/REGION/clusters/CLUSTER_NAME`.
2. Create or update an AWS IAM role with a trust policy allowing the OIDC provider with a `Condition` matching the federated subject:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789012:oidc-provider/container.googleapis.com/v1/projects/PROJECT/locations/REGION/clusters/CLUSTER"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "container.googleapis.com/v1/projects/PROJECT/locations/REGION/clusters/CLUSTER:sub":
            "system:serviceaccount:checkout:checkout"
        }
      }
    }
  ]
}
```

3. The GKE workload then exchanges its projected token for AWS credentials via `aws sts assume-role-with-web-identity`. Most AWS SDKs handle this with the `web identity token file` profile pattern.

This is the *additive* path — the EKS pod's IRSA still works on EKS, and the GKE pod gets the same AWS IAM role via federation. After cutover and the EKS shutdown, retire the federated role.

### Step 5 — Migrate identity for system workloads

DaemonSets and platform-level workloads also have IRSA bindings (cluster-autoscaler, external-dns, cert-manager, aws-load-balancer-controller, fluentbit). For these:

- `cluster-autoscaler` → not needed; GKE has built-in CA.
- `aws-load-balancer-controller` → replace entirely with GKE Gateway controller.
- `external-dns` → re-deploy with Cloud DNS provider config and a new GSA.
- `cert-manager` with Route 53 DNS01 → re-deploy with Cloud DNS DNS01 provider and a new GSA.
- `fluentbit` / Cloud Operations agent → GKE has native logging.

Each of these is a *new* binding, not a translation. Capture them in a separate section of `identity-map.json` flagged as `kind: platform_workload`.

### Step 6 — Document the cutover order

The orchestrator's `traffic-cutover` flips traffic per workload. For each workload:

1. Pre-cutover: GKE binding live; AWS binding live; both clusters running.
2. At cutover: traffic shifts to GKE; AWS binding still live (in case of rollback).
3. Post-cutover (after soak): retire the AWS IAM role.

`identity-translation` produces `cutover-order.md` listing this order per workload.

## Decision points

| Decision                                       | Default                              | When to deviate                                        |
|------------------------------------------------|--------------------------------------|--------------------------------------------------------|
| Cross-cloud federation vs re-platform now      | Cross-cloud federation               | Re-platform now if the dependency is small + shipped late |
| One GSA per KSA vs shared GSAs                 | One GSA per KSA                      | Shared only for true multi-tenant cases (and document the trust) |
| Predefined GCP roles vs custom                 | Predefined                           | Custom when predefined are too broad and policy-as-code can validate the diff |
| KSA per Deployment vs per namespace            | Per-Deployment KSA                   | Per-namespace only for very small services |
| Retire AWS role at cutover vs cool-down        | 14-day cool-down                     | Immediate retire only for non-critical workloads |

## Outputs / Deliverables

```
05-identity-translation/
├── identity-map.json
├── identity-map.md           # Human-readable
├── manifests/
│   └── serviceaccounts/      # KSA YAML per workload
├── terraform/
│   ├── google-service-accounts.tf
│   └── iam-bindings.tf
├── aws-federation/           # AWS-side OIDC providers + role trust amendments
├── cutover-order.md
└── escalations.md
```

## Validation

For each KSA in the ledger, before deploying any application workload:

- `kubectl get sa <ksa> -n <ns> -o jsonpath='{.metadata.annotations.iam\.gke\.io/gcp-service-account}'` returns the expected GSA.
- `gcloud iam service-accounts get-iam-policy <gsa-email>` shows the correct `roles/iam.workloadIdentityUser` member.
- The validation pod (Step 3) resolves to the right identity.
- For cross-cloud federation, an AWS-side `aws sts get-caller-identity` from the GKE test pod returns the federated role ARN.

## Escalation triggers

- IRSA role with a trust policy that condition-matches *another* AWS account's OIDC provider — unusual and likely needs human review.
- IRSA role with `Action: "*"` or `Resource: "*"` — flag and propose a least-privileged target rather than translating literally.
- Workload using AWS-only services (KMS for app-level crypto, STS as auth backend, IAM as a runtime API) — re-platform plan needed.
- Workload that authenticates *AWS users via IAM* (e.g., apps fronting IAM authenticator) — these need a re-architecture.

## Common pitfalls

- **Translating IAM policies literally.** A literal translation of an over-broad IAM policy produces an over-broad GCP role. Use this as the chance to least-privilege.
- **Forgetting to remove the IRSA annotation post-cutover.** Stale annotations confuse future operators. Have `traffic-cutover` strip them.
- **Workload pool name typos.** It's `<project>.svc.id.goog`, not `<cluster>.svc.id.goog`. The cluster project's pool is the one used by all clusters in that project.
- **Missing GSA on cross-project resource access.** If the workload reads from a bucket in `data-prod`, the GSA needs the binding in `data-prod`, not in the cluster project. See [LFF-36](../../reference/lessons-from-the-field.md#lff-36--external-secrets-fails-when-gsa-and-secret-manager-live-in-different-projects).
- **Assuming all SDKs auto-detect WI.** Most do. A few language-specific SDKs need an explicit `GOOGLE_APPLICATION_CREDENTIALS` or library version bump. Test.
- **Pod cold-start auth fails ~50% of the time on the first request** due to `gke-metadata-server` not being ready. Either retry with backoff at startup, or gate startup with a `wait-for-workload-identity`-style init container. See [LFF-06](../../reference/lessons-from-the-field.md#lff-06--workload-identity-metadata-server-isnt-ready-at-pod-start-50-of-cold-start-auths-fail).
- **Argo CD and other charts that overwrite the projected token mount** silently break IRSA-style auth for ~40 minutes after install. Check `automountServiceAccountToken` and projected-token-volume integrity in chart templates. See [LFF-07](../../reference/lessons-from-the-field.md#lff-07--argo-cd-pods-lose-iam-access-for-40-minutes-after-first-install).
- **Don't forget to block egress to `169.254.169.254`** from non-system namespaces — without it, a misconfigured WI binding silently inherits the node's GCE service account. See [LFF-08](../../reference/lessons-from-the-field.md#lff-08--on-gke-you-must-explicitly-block-169254169254-to-prevent-pods-grabbing-node-level-credentials).
- **Cloud SQL Auth Proxy under WI flaps with `NOT_AUTHORIZED`** due to token-refresh races. Validation must include sustained-traffic tests, not just single-request smoke. See [LFF-14](../../reference/lessons-from-the-field.md#lff-14--cloud-sql-proxy-randomly-drops-with-not_authorized-due-to-token-refresh-races).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Workload Identity Federation for GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity) — the canonical product page (note the rebrand from "Workload Identity").
- [Workload Identity Federation with AWS or Azure](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds) — for the cross-cloud federation pattern in Step 4.
- [Best practices for using service accounts](https://cloud.google.com/iam/docs/best-practices-for-using-and-managing-service-accounts).
- [docs/glossary.md](../../docs/glossary.md) — IAM/identity translation.
- [eks-discovery](../eks-discovery/SKILL.md) — produces irsa-map.tsv.
- [traffic-cutover](../traffic-cutover/SKILL.md) — coordinates removal of AWS bindings.
