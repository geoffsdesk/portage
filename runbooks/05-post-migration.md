# Runbook 05 — Post-Migration Operations

The Phase 5 runbook. Tune, harden, and decommission.

## Goal

End the phase with: GKE estate cost-tuned, security-hardened, fully observable; EKS retired; final summary signed off.

## Pre-flight

- Phase 4 complete (`04-cutover.md`).
- 7+ days post-cutover for tier-2; per-tier soak windows met.

## Execute

1. **FinOps baseline.**

   "Use the post-migration-ops skill to produce the FinOps baseline."

   The agent pulls 30-day billing, compares against the EKS baseline, and writes `12-post-migration/finops/cost-comparison.md`.

2. **Right-size workloads.**

   The agent enables VPA in `Off` (recommend) mode for every Deployment, gathers 14-day data, and produces a recommendations PR. Review and merge selectively.

3. **Tune autoscaling.**

   Walk per-workload HPA / VPA / CA settings. Confirm bounds reflect post-migration traffic.

4. **Plan Spot adoption / CUDs.**

   The agent surfaces Spot candidates and a CUD purchase plan with break-even. Decide what to commit to.

5. **Run hardening checklist.**

   The agent walks `12-post-migration/hardening-checklist.md`. Address each row:
   - Move BinAuthz to ENFORCE if attestation history is clean.
   - Move PSA to `restricted` enforced for new namespaces.
   - Confirm zero service-account keys org-wide.
   - Address any SCC findings.

6. **Confirm observability completeness.**

   Every tier-0 workload: golden-signals dashboard, SLO, burn-rate alert, runbook URL.

7. **Plan EKS decommission.**

   Render `12-post-migration/decommission-plan.md`. Walk the T+0/T+14/T+30 schedule with the team.

8. **Decommission, in stages.**

   - **T+1**: scale all EKS Deployments to 0. Keep clusters up.
   - **T+7**: archive what's needed. Snapshot remaining EBS volumes; move to long-term storage.
   - **T+14**: delete EKS clusters; tear down ALBs/NLBs/NAT/VPC endpoints.
   - **T+21**: clean up IAM roles, OIDC providers.
   - **T+30**: retire data systems past their retention; review residual AWS charges.

   At every stage, the agent confirms before destructive action. Never auto-destroy.

9. **Final summary.**

   Render `migration-summary.md`. Get sign-off from each approver in the migration plan's approval table.

## Exit gate

- [ ] FinOps baseline accepted.
- [ ] Right-sizing PR merged for the workloads where it applies.
- [ ] Hardening checklist 100% green or with documented exceptions.
- [ ] Observability checklist 100% green for tier-0.
- [ ] Decommission complete to T+30 (or scheduled).
- [ ] Final summary signed off.

Migration complete.
