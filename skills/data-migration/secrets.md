# AWS Secrets Manager to Google Secret Manager Migration

## Prerequisites

- Inventory of all AWS Secrets Manager secrets referenced by migrating workloads (`01-discovery/inventory.json`).
- `data-prod` project provisioned with Secret Manager API (`secretmanager.googleapis.com`) enabled.

## Procedure

### 1. Provision Secret Manager Secrets
For each secret referenced by workloads in scope:
1. Create equivalent Google Cloud Secret with matching name (or namespaces defined in `identity-translation`).
2. Replicate payload value securely using a one-time script with read-only AWS credentials (`aws secretsmanager get-secret-value | gcloud secrets create ...`).
3. Set IAM access policies (`roles/secretmanager.secretAccessor`) for target Kubernetes Service Account (KSA) Workload Identity bindings (`identity-translation`).

### 2. Application Integration
Configure how workloads retrieve secrets in GKE (`workload-translation`):
- **External Secrets Operator (ESO)**: Deploy `ClusterSecretStore` / `SecretStore` pointing to Google Secret Manager with Workload Identity. Create `ExternalSecret` manifests to materialize Kubernetes Secrets.
- **Direct SDK / Volume Mounts**: Use Google Secret Manager CSI Driver or native client SDKs.

### 3. Cutover & Rollback
- During cutover, GKE workloads retrieve credentials from Google Secret Manager.
- Retain AWS Secrets Manager secrets during the 14-day rollback window.
- **Source Environment Credentials**: For secret values that are credentials connecting back to *AWS* services during co-existence, retire/delete them once those AWS dependencies are fully decommissioned.

## Validation

- All `ExternalSecret` custom resources in GKE report `SecretSynced` status.
- Workloads successfully read database passwords, API keys, and certificates on startup without permission errors.

## Common pitfalls

- **Leaking secrets in commit history or logs**: Never commit exported secret payloads to Git or print them to execution logs during migration scripting (`validate.yml` enforces `gitleaks` checks).
- **Missing IAM permissions**: Ensure the Workload Identity service account has exact `roles/secretmanager.secretAccessor` on specific secret resource names rather than project-wide owner/editor roles.

## References

- [Google Cloud Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [External Secrets Operator — Google Secret Manager Provider](https://external-secrets.io/latest/provider/google-secret-manager/)
