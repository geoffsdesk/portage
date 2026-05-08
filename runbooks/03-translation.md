# Runbook 03 — Workload, Storage, Registry, Observability Translation

The Phase 3 runbook. Translate manifests and supporting infrastructure for every workload.

## Goal

End the phase with: every workload's manifests translated and dry-run-applied to the GKE target; StorageClasses + PVC plans ready; AR populated and image-map.json complete; observability parity validated.

## Pre-flight

- Phase 2 complete (`02-landing-zone.md`).
- AR project provisioned.
- Source registry credentials available.

## Execute

1. **Run registry-migration.**

   "Use the registry-migration skill. Mirror all in-use ECR images to AR, set up dual-push pipelines."

   The agent provisions AR repos via Terraform, drives `skopeo` mirrors, generates `image-map.json`, and produces pipeline-change checklists.

   Time: depends on image volume; mirror time often dominates.

2. **Update build pipelines.**

   Per the `08-registry-migration/pipelines.md` checklist, add AR push steps. Verify a CI run pushes to both registries.

3. **Run storage-translation.**

   "Use the storage-translation skill."

   The agent emits target StorageClasses, per-PVC plan documents, and Filestore Terraform where applicable.

4. **Apply translated StorageClasses.**

   ```bash
   kubectl apply -f 07-storage-translation/manifests/storageclasses/
   ```

5. **Run workload-translation.**

   "Use the workload-translation skill against the discovery's workloads."

   The agent rewrites manifests and Helm values, produces per-workload diffs with rationale, and surfaces any Autopilot-incompatible workloads as escalations.

6. **Review diffs.**

   Walk `06-workload-translation/diffs/` for each workload. Each diff is annotated with rationale. Sanity-check.

7. **Server-side dry-run.**

   ```bash
   for d in 06-workload-translation/manifests/*/*; do
     kubectl --dry-run=server apply -f "$d/"
   done
   ```

   Investigate any errors.

8. **Apply to a non-prod cluster.**

   For each non-prod workload, apply the translated manifests. Run smoke tests.

9. **Run observability-translation.**

   "Use the observability-translation skill."

   The agent emits PodMonitoring/Rules CRs, alerting policies, dashboards, and an alarm-translation table.

10. **Apply observability.**

    ```bash
    kubectl apply -f 09-observability-translation/manifests/
    cd 09-observability-translation/terraform
    terraform init && terraform plan && terraform apply
    ```

11. **Validate observability parity.**

    Run a known load on a non-prod workload. Confirm:
    - Metrics appear in Cloud Monitoring (and via PromQL through GMP).
    - Logs appear in Cloud Logging within 30s.
    - The translated alerting policy fires on a test breach.

## Exit gate

- [ ] Every in-scope image is in AR with matching digest.
- [ ] Pipelines push to AR (verified).
- [ ] Every PVC has a plan in `pvc-plans/`.
- [ ] Every workload has a translated manifest set + rationale diff.
- [ ] All translated manifests pass `kubectl --dry-run=server apply`.
- [ ] Non-prod cluster runs the translated manifests; smoke tests pass.
- [ ] Observability parity confirmed on a non-prod canary.

Proceed to `runbooks/04-cutover.md`.
