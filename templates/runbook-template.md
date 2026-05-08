# Runbook — {{title}}

**Run ID:** {{run_id}}
**Workload / system:** {{workload}}
**Tier:** {{tier}}
**Window:** {{window_start}} → {{window_end}}
**Owner:** {{owner}}
**On-call:** {{oncall}}

---

## Summary

{{one_paragraph_summary}}

## Pre-flight checklist

Run all of these before the cutover window starts. Every box must tick.

- [ ] GKE workload deployed and `Available`. `kubectl rollout status deploy/{{workload}}` returns success.
- [ ] Gateway/HTTPRoute is `Programmed: True`. `kubectl describe gateway {{gateway}}` confirms.
- [ ] External Gateway IP resolves and `curl https://{{host}}/healthz` returns 200.
- [ ] WI / GSA bindings validated against `identity-map.json`.
- [ ] Image references resolve to AR digests (`gcloud container images describe`).
- [ ] Data system synchronized (replication lag < {{lag_threshold}} s).
- [ ] Observability dashboards and alerts wired up. Test alert fires.
- [ ] Rollback plan reviewed; EKS workload still scaled to {{eks_replica_count}} replicas.
- [ ] Stakeholder comms sent ({{comms_channel}}).
- [ ] Maintenance window confirmed; freeze in effect for adjacent services.

## Cutover steps

### Step 1 — {{step_1_title}}

**Command:**
```bash
{{step_1_command}}
```

**Expected output:** {{step_1_expected}}

**Validation gate:** {{step_1_gate}}

**Rollback if failed:** {{step_1_rollback}}

### Step 2 — {{step_2_title}}

…

(One section per step.)

## Validation gates

| Gate                         | Threshold              | Window  | Action on breach   |
|------------------------------|------------------------|---------|--------------------|
| 5xx rate (target side)       | ≤ {{baseline_5xx}}+0.5%| 5 min   | Pause; alert       |
| p95 latency (target side)    | ≤ 1.5× baseline        | 5 min   | Pause; alert       |
| Backend health               | ≥ 95% targets healthy  | 1 min   | Auto-rollback      |
| {{custom_gate}}              | {{threshold}}          | {{win}} | {{action}}         |

## Rollback

If any gate breaches at >50% traffic, or any backend-health gate breaches at any weight:

1. Run `bash {{run_dir}}/rollback.sh` (calls into `rollback-playbook`).
2. Capture evidence per `rollback-playbook` Step 5.
3. Open postmortem from `templates/postmortem-template.md`.

## Decommission (post-soak)

Soak period: {{soak_days}} days. After soak, with explicit user confirmation:

- [ ] Scale EKS Deployment to 0.
- [ ] Remove ALB / NLB target group references.
- [ ] Update DNS to remove EKS targets entirely.
- [ ] Mark `traffic-cutover` complete in orchestrator state.
- [ ] Schedule source data system retention review (per `data-migration` plan).

## References

- Workload manifests: `{{run_dir}}/06-workload-translation/manifests/{{workload}}/`
- Identity map: `{{run_dir}}/05-identity-translation/identity-map.json`
- Gates: `{{run_dir}}/11-cutover/gates/{{workload}}-gates.yaml`
- Source-side tracking: {{tracking_link}}
