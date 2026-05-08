# Runbook 02 — Landing Zone, Network, Identity

The Phase 2 runbook. Build the GCP target, translate the network, and stand up identity.

## Goal

End the phase with: applied Terraform for projects/VPC/clusters; Gateway/HTTPRoute/Cloud Armor manifests reviewed; per-workload identity bindings created and validated.

## Pre-flight

- Phase 1 complete (see `01-discovery.md`).
- Org Admin or delegated permissions for the operator running Terraform.
- `gcloud` and `terraform` >= 1.6.
- Bootstrap project for Terraform state created.

## Execute

1. **Run the landing zone skill.**

   "Use the gke-landing-zone skill. Target org: example.com. Billing account: ABC. Folder: portage-prod. Constraints: regional clusters, Autopilot for prod, Standard for nonprod, BinAuthz in evaluation."

   The agent asks the design questions in clusters, builds `03-landing-zone/terraform/`, runs `terraform plan`, and surfaces the plan to you.

2. **Review the Terraform plan.**

   Resources created (typical):
   - 4 projects, 2 networks (one per env), 4 GKE clusters, KMS keyring + keys, fleet memberships, IAM bindings, org policies, billing budgets.

   Check for surprises: unexpected destroys, IAM bindings on the wrong principal, public IP on any resource.

3. **Apply.**

   Apply org policies first (separate workspace), then folders + projects, then VPC, then KMS, then clusters, then fleet/IAM/budget. The agent suggests this order in the plan output.

   Time: 25–60 min.

4. **Validate clusters.**

   ```bash
   gcloud container clusters get-credentials prod-primary --region us-central1 \
     --project gke-prod-clusters
   kubectl get ns
   kubectl get crd | grep gateway.networking.k8s.io
   gcloud container clusters describe prod-primary --region us-central1 \
     --format='value(workloadIdentityConfig.workloadPool, datapathProvider, gatewayApiConfig.channel)'
   ```

   Expect: pool ends in `.svc.id.goog`, `ADVANCED_DATAPATH`, `CHANNEL_STANDARD`.

5. **Run network translation.**

   "Use the network-translation skill. Output to 04-network-translation/."

   The agent reads the source-side ALBs/NLBs/Ingresses and produces target Gateway/HTTPRoute/HealthCheckPolicy/GCPBackendPolicy manifests, plus Cloud Armor TF, plus a DNS plan.

6. **Apply Cloud Armor + Certificate Manager.**

   ```bash
   cd 04-network-translation/terraform
   terraform init && terraform plan && terraform apply
   ```

7. **Apply Gateway / HTTPRoute manifests.**

   ```bash
   kubectl apply -k 04-network-translation/manifests/
   ```

   Validate: `kubectl describe gateway` shows `Programmed: True`. Curl the Gateway IP with the placeholder hostname and expect either a 404 (no backends yet) or a healthy response if backends are already deployed.

8. **Run identity translation.**

   "Use the identity-translation skill against the discovery's irsa-map.tsv."

   The agent maps every IRSA SA to a target GSA, generates Terraform, creates KSAs, and writes a per-binding validation plan.

9. **Apply identity Terraform.**

   ```bash
   cd 05-identity-translation/terraform
   terraform init && terraform plan && terraform apply
   ```

10. **Validate identity end-to-end.**

    For one representative KSA per cohort:

    ```bash
    kubectl create ns checkout 2>/dev/null
    kubectl apply -f 05-identity-translation/manifests/serviceaccounts/checkout.yaml
    kubectl -n checkout run wi-test --rm -it --restart=Never \
      --image=google/cloud-sdk:slim \
      --overrides='{"spec":{"serviceAccountName":"checkout"}}' \
      -- gcloud auth list
    ```

    Expect: the GSA email is the active account.

11. **Set up cross-cloud federation (if any workload retains AWS API calls).**

    The agent emits AWS-side OIDC provider Terraform and updated trust policies under `05-identity-translation/aws-federation/`. Apply with AWS credentials.

## Exit gate

- [ ] Terraform applied for landing zone, network, and identity.
- [ ] Each cluster: WI enabled, Dataplane V2 active, Gateway API installed.
- [ ] Each Gateway: programmed; reachable.
- [ ] Each KSA in `identity-map.json`: validated WI resolution.
- [ ] Cloud Armor / Certificate Manager / DNS plan reviewed and ready for cutover.

Proceed to `runbooks/03-workload-translation.md`.
