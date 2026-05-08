---
name: registry-migration
description: Migrate container images from Amazon ECR to Google Artifact Registry. Plans the AR repo layout, mirrors images (skopeo or pull-through), updates build pipelines, sets up vulnerability scanning, and produces an image-map.json mapping every old image reference to its new one. Use when "migrate ECR to Artifact Registry", "set up image registries on GCP", or as Phase 3 of a Portage migration.
---

# Registry Migration

You move container images from ECR to Artifact Registry, set up vulnerability scanning, update build pipelines, and produce a mapping file the rest of Portage uses to rewrite image references.

## Purpose

Every container image referenced from any Kubernetes workload has to be reachable from GKE — preferably from a regional Artifact Registry — at low latency, with vulnerability scanning, and (when in scope) with Binary Authorization attestations.

## When to use this skill

- Phase 3 of a Portage migration.
- The user asks to "set up Artifact Registry", "mirror ECR to GCP", "migrate images".

## Prerequisites

- `01-discovery/inventory.json` ECR section.
- `03-landing-zone/plan.md` with the `artifact-registry` shared project provisioned.
- `gcloud`, `aws`, `skopeo` CLIs.
- Either skopeo with credentials for both registries OR a CI/CD runner with both credentials.

## Procedure

### Step 1 — Plan the AR repo layout

Default layout:

```
projects/artifact-registry/locations/<region>/repositories/<repo-name>
```

Naming: one AR repository per ECR repository, same name. Multi-region repos for global distribution if cross-region pulls matter.

Decide repo format:

- **Standard repository**: contains images directly. One per (env × team) is the typical shape, OR mirror ECR's existing per-app structure 1:1 to keep image references close to identical.
- **Virtual repository**: aggregates upstream registries (Docker Hub, public ECR Public). Use to standardize where pull-through caching is needed.
- **Remote repository**: mirrors a single upstream (Docker Hub, NPM). Use for bringing public images on-cluster without depending on Docker Hub directly.

For this migration:

- Plan a *standard* AR repo per ECR repo, in the user's primary region (e.g., `us-central1`).
- For repos with very high cross-region pull rates, plan an additional repo in the second region with replication.
- Plan a *remote* repo for `docker.io` and `quay.io` if the workloads pull public images directly.

### Step 2 — Provision AR repos

Terraform per repo:

```hcl
resource "google_artifact_registry_repository" "payments_api" {
  project       = var.ar_project
  location      = var.region
  repository_id = "payments-api"
  format        = "DOCKER"

  docker_config { immutable_tags = false }   # tighten later if desired

  cleanup_policies {
    id     = "keep-recent-100"
    action = "KEEP"
    most_recent_versions { keep_count = 100 }
  }
  cleanup_policies {
    id     = "delete-untagged-after-30d"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "2592000s"
    }
  }

  cleanup_policy_dry_run = true   # flip to false after one cleanup cycle of review
}
```

For pull-through cache:

```hcl
resource "google_artifact_registry_repository" "docker_hub_remote" {
  project       = var.ar_project
  location      = var.region
  repository_id = "docker-hub"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  remote_repository_config {
    docker_repository { public_repository = "DOCKER_HUB" }
  }
}
```

### Step 3 — Mirror images

For each ECR repo + tag/digest in scope:

```bash
SRC=123456789012.dkr.ecr.us-east-1.amazonaws.com/payments/api:1.4.2
DST=us-central1-docker.pkg.dev/artifact-registry-prod/payments-api:1.4.2

aws ecr get-login-password --region us-east-1 \
  | skopeo login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com

gcloud auth configure-docker us-central1-docker.pkg.dev --quiet
gcloud auth print-access-token \
  | skopeo login --username oauth2accesstoken --password-stdin us-central1-docker.pkg.dev

skopeo copy --multi-arch=all --preserve-digests \
  docker://${SRC} \
  docker://${DST}
```

For the bulk move, drive a parallel job:

```bash
jq -r '.[] | select(.kind=="image") | "\(.src)|\(.dst)"' image-plan.json \
  | xargs -P 8 -I{} bash -c 'IFS="|" read SRC DST <<< "$1"; \
     skopeo copy --multi-arch=all --preserve-digests docker://$SRC docker://$DST' _ {}
```

`--preserve-digests` ensures digests survive the copy, which is critical if any deployment pins by digest (it should).

### Step 4 — Update build pipelines

For each upstream pipeline:

- **GitHub Actions**: add a `google-github-actions/auth@v2` step (using Workload Identity Federation), then `google-github-actions/setup-gcloud@v2`, then push to `*.pkg.dev/...`. Keep ECR push for a co-existence period.
- **CodeBuild / CodePipeline**: add a parallel push step that pushes to AR using a service account key OR (preferred) federated identity into GCP.
- **Cloud Build / Cloud Deploy**: native push to AR.
- **Tekton**: add a second `image-push` task targeting AR.

Produce a checklist `08-registry-migration/pipelines.md` listing every pipeline, the change to make, and the verification step.

### Step 5 — Build the image-map

Produce `08-registry-migration/image-map.json`:

```json
[
  {
    "src": "123456789012.dkr.ecr.us-east-1.amazonaws.com/payments/api:1.4.2",
    "dst": "us-central1-docker.pkg.dev/artifact-registry-prod/payments-api:1.4.2",
    "src_digest": "sha256:abc...",
    "dst_digest": "sha256:abc...",
    "consumed_by": ["payments/payments-api"]
  }
]
```

`workload-translation` consumes this to rewrite image refs.

### Step 6 — Vulnerability scanning + Binary Authorization

Enable Artifact Analysis (formerly Container Analysis) on the AR project. New images push automatically scan. Surface findings in `08-registry-migration/vuln-baseline.md` so the team has a starting state.

For Binary Authorization (when in scope):

1. Plan an attestor: `gcloud container binauthz attestors create …`.
2. Plan an attestation policy on the cluster (start in `EVALUATION` mode, switch to `ENFORCE` after a review window).
3. Wire CI to attest on push (Cloud Build has built-in support; for GitHub Actions, use `google-github-actions/attest-build-provenance` or `cosign sign`).

### Step 7 — Cutover plan for image references

The image references in workloads should be rewritten in the same change that deploys to GKE. Until cutover, EKS continues to pull from ECR.

Sequence:

1. AR repos exist.
2. Initial mirror done; ongoing mirror automated (a Cloud Scheduler + Cloud Run job, or CI step).
3. Pipelines push to *both* ECR and AR.
4. GKE workloads reference AR.
5. After cutover and soak, EKS push step retired, then ECR repos retired (separate decommission).

### Step 8 — Decommission plan for ECR

Produce `08-registry-migration/ecr-decommission.md`:

- Per-repo decommission date (default: 30 days post final cutover for that workload).
- Final image archive: tag `archive-YYYYMMDD` and copy to a long-term Cloud Storage bucket if compliance requires.
- IAM cleanup: scoped IAM roles, lifecycle policies.

## Decision points

| Decision                                  | Default                        | When to deviate                            |
|-------------------------------------------|--------------------------------|--------------------------------------------|
| AR repo structure                          | One AR repo per ECR repo, same name | Restructure if ECR layout was historically painful |
| Region                                     | Same region as primary GKE cluster | Multi-region replication for >2 regions |
| Pull-through caches                        | One for `docker.io`, one for `quay.io` (if used) | Skip if you mirror everything explicitly |
| Cleanup policy                             | Keep 100 most recent + delete untagged > 30d | Tighter (10 most recent) for non-prod |
| Binary Authorization                       | Enabled in `EVALUATION` mode initially | `ENFORCE` mode only after attestation pipeline runs cleanly for >2 weeks |

## Outputs / Deliverables

```
08-registry-migration/
├── repos.md                  # Per-AR-repo plan
├── terraform/
│   └── artifact-registry.tf
├── mirror-plan.json          # Source images, target images, mirror command
├── image-map.json            # Used by workload-translation
├── pipelines.md              # Per-pipeline change list
├── vuln-baseline.md          # Initial Artifact Analysis findings
├── binauthz/                 # Attestor + policy YAMLs (optional)
├── ecr-decommission.md
└── escalations.md
```

## Validation

- Every image referenced by any translated workload exists in AR with matching digest.
- `gcloud container images describe <full-ref>` succeeds for every image in `image-map.json`.
- A test pod on GKE successfully pulls a representative image without auth issues (KSA → GSA with `roles/artifactregistry.reader` on the AR project).
- New CI runs push to AR and the image appears with the new tag within 5 minutes.
- (If BinAuthz enabled) `EVALUATION` mode logs show every push attestation event.

## Escalation triggers

- ECR images in repos using lifecycle rules whose retention exceeds AR cleanup policies the user is willing to set. Surface for re-decision.
- Images larger than AR's per-image / per-layer limits (rare). Surface and discuss split.
- Cross-cloud egress costs from initial mirror exceed the user's per-month tolerance. Surface plan: throttled mirror, region-by-region.
- ECR repos referenced by workloads in *another* AWS account (cross-account pulls). Discovery should have flagged; if not, surface here.

## Common pitfalls

- **Pushing without `--preserve-digests`.** Re-built images get new digests and break digest-pinned deployments.
- **Forgetting Workload Identity → AR reader.** GSAs that pull from AR need `roles/artifactregistry.reader` on the AR project, not just on the cluster project.
- **Pipelines that hardcode AWS region in image refs.** When the dual-push goes live, those pipelines break in non-obvious ways.
- **Pull-through caches that tag-pin.** A pull-through cache pinning `latest` from Docker Hub returns whatever the cache last fetched, not the real `latest`.
- **Not seeding the cache.** The first cluster pull of every cached upstream image is slow. Pre-warm before cutover.

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Artifact Registry overview](https://cloud.google.com/artifact-registry/docs).
- [Artifact Analysis (vulnerability scanning)](https://cloud.google.com/artifact-analysis/docs).
- [Binary Authorization](https://cloud.google.com/binary-authorization/docs).
- [Sigstore + Binary Authorization on GKE](https://cloud.google.com/binary-authorization/docs/setting-up-cosign).
- [SLSA framework](https://slsa.dev).
- [docs/glossary.md](../../docs/glossary.md) — registry mapping.
- [workload-translation](../workload-translation/SKILL.md) — consumes image-map.json.
- [identity-translation](../identity-translation/SKILL.md) — KSA needs `artifactregistry.reader`.
