# Postmortem — {{title}}

**Date of incident:** {{incident_date}}
**Severity:** {{severity}}
**Status:** {{status}} (Open / Mitigated / Resolved)
**Author:** {{author}}
**Stakeholders:** {{stakeholders}}

---

## Summary

{{one_paragraph}}

## Impact

- **Duration:** {{start_ts}} → {{end_ts}} ({{duration_min}} min).
- **Workloads affected:** {{workloads}}.
- **User-visible effect:** {{user_effect}}.
- **Estimated request loss / errors:** {{request_count}} ({{percent}}% of traffic during window).
- **SLO budget consumed:** {{slo_budget_minutes}} budget-minutes of {{workload}}'s {{slo_period}} budget.

## Timeline

All times UTC.

| Time     | Event                                                                     |
|----------|---------------------------------------------------------------------------|
| {{ts_a}} | Cutover step `{{step}}` initiated; weight {{weight}}.                    |
| {{ts_b}} | Cloud Monitoring alerting policy `{{policy}}` fires — {{condition}}.     |
| {{ts_c}} | `traffic-cutover` auto-rollback triggers; weights revert to {{prev_weights}}.  |
| {{ts_d}} | DNS revert verified via `dig`; SLO returns to baseline.                  |
| {{ts_e}} | Evidence captured to `rollback-evidence/`.                                |
| {{ts_f}} | This postmortem opened.                                                   |

## What went wrong

{{narrative}}

## What we did right

{{narrative_positive}}

## Root cause

{{root_cause}}

(Distinguish *trigger* — the cutover step — from *cause* — the underlying defect that turned a routine cutover into a regression.)

## Lessons

1. {{lesson_1}}
2. {{lesson_2}}
3. {{lesson_3}}

## Action items

| ID  | Action                                                  | Owner    | Due       | Done |
|-----|---------------------------------------------------------|----------|-----------|------|
| A-1 | {{action_1}}                                            | {{own}}  | {{due}}   | [ ]  |
| A-2 | {{action_2}}                                            | {{own}}  | {{due}}   | [ ]  |
| A-3 | Add validation gate `{{new_gate}}` for {{workload}}     | {{own}}  | {{due}}   | [ ]  |

## Re-attempt plan

The cutover for `{{workload}}` will not be re-attempted until:

- [ ] All P0 / P1 action items complete.
- [ ] Load test reproduces the previous regression and the fix passes the same test.
- [ ] {{custom_gate}} added to runbook.
- [ ] Stakeholder sign-off recorded in `{{run_dir}}/11-cutover/{{workload}}/next-attempt-plan.md`.

## References

- Trigger alerting policy: `projects/{{obs_project}}/alertPolicies/{{policy_id}}`
- Evidence: `{{run_dir}}/11-cutover/{{workload}}/rollback-evidence/`
- Cutover execution log: `{{run_dir}}/11-cutover/execution-logs/{{workload}}.log`
- Rollback execution log: `{{run_dir}}/11-cutover/{{workload}}/rollback.log`
