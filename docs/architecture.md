# Portage Architecture

This document describes how Portage is organized, how skills compose, and the contracts that hold the library together.

## The mental model

A Portage migration is a **graph of skills**, not a wizard. The orchestrator is the graph runner. Each skill is a node that:

1. takes typed inputs (artifacts produced by upstream skills, plus human answers),
2. performs a bounded chunk of work,
3. emits typed outputs (artifacts the next skill can consume),
4. or *escalates* — stops and writes a structured note to a human.

```
  ┌─────────────────────────┐
  │  portage-orchestrator   │  ← reads inputs, picks next skill, tracks state
  └────────────┬────────────┘
               │
   ┌───────────┼───────────┐
   ▼           ▼           ▼
[discover] [design]   [translate] → [cut over] → [operate]
```

The orchestrator never does the work itself. It picks the next skill, hands it the right inputs, watches for an escalation, and writes the migration *trace* — a chronological log of every skill invocation, its inputs, its outputs, and any human decisions that gated it.

## The skill format

Every skill is a folder under `skills/<skill-name>/` containing at minimum a `SKILL.md`:

```markdown
---
name: skill-name
description: One-line description with concrete triggers.
---

# Skill Title

## Purpose
## When to use this skill
## Prerequisites (inputs, IAM, tools)
## Procedure
   1. ...
   2. ...
## Decision points
## Outputs / Deliverables
## Validation
## Escalation triggers
## Common pitfalls
## References
```

The frontmatter is the **load contract**: any agent runtime that reads `SKILL.md` files (Claude Code, Cowork, custom Agent SDK harnesses) discovers the skill by scanning frontmatter. The body is the **execution contract**: any agent reading the body should be able to perform the work.

Skills MAY include:

- `assets/` — Terraform modules, Helm value files, scripts.
- `templates/` — Output document templates the skill fills in.
- `examples/` — Worked examples showing input → output for the skill in isolation.

Skills MUST NOT include:

- Untrusted scripts that would run unconfirmed.
- Hardcoded customer data.
- Dependencies on a specific orchestrator beyond the `SKILL.md` contract.

## The artifact contract

Skills communicate by writing artifacts to a run directory:

```
portage-output/
└── 2026-05-06-acme-prod-migration/
    ├── 00-orchestrator-state.json
    ├── 01-discovery/
    │   ├── inventory.json
    │   ├── inventory-summary.md
    │   └── escalations.md
    ├── 02-assessment/
    │   ├── readiness-report.md
    │   └── blockers.md
    ├── 03-landing-zone/
    │   ├── plan.md
    │   ├── terraform/
    │   └── apply-log.md
    ├── 04-network-translation/
    ├── 05-identity-translation/
    ├── 06-workload-translation/
    ├── 07-storage-translation/
    ├── 08-registry-migration/
    ├── 09-observability-translation/
    ├── 10-data-migration/
    ├── 11-cutover/
    │   ├── runbook.md
    │   ├── validation-gates.md
    │   └── execution-log.md
    └── 12-post-migration/
```

Every artifact is human-readable. JSON files are pretty-printed. Markdown is the lingua franca for everything narrative.

## State tracking

The orchestrator maintains `00-orchestrator-state.json`:

```json
{
  "run_id": "2026-05-06-acme-prod-migration",
  "started_at": "2026-05-06T14:00:00Z",
  "source": { "provider": "aws", "account_id": "123456789012", "regions": ["us-east-1"] },
  "target": { "provider": "gcp", "org_id": "123456789012", "billing_account": "..." },
  "current_phase": "translate",
  "current_skill": "workload-translation",
  "completed_skills": ["eks-discovery", "migration-assessment", "gke-landing-zone", "network-translation", "identity-translation"],
  "blockers": [],
  "open_escalations": ["custom-cni-detected"],
  "decisions": [
    { "at": "2026-05-06T15:12:00Z", "skill": "gke-landing-zone", "question": "Regional vs zonal cluster?", "answer": "regional", "rationale": "user requirement: 99.95% SLO" }
  ]
}
```

This file is the migration's source of truth. If the agent session is interrupted, a new session can resume by reading the state file and continuing from `current_skill`.

## Escalation model

A skill escalates by writing an `escalations.md` file in its run directory and returning a structured `Escalation` payload to the orchestrator. An escalation includes:

- **Trigger**: the precise condition that fired (e.g., "DaemonSet using `hostNetwork: true` with custom CNI plugin").
- **Why this is human-only**: the reason the skill cannot safely translate this without a decision.
- **Options**: 2–4 concrete paths forward, with trade-offs.
- **Recommended**: the option the skill would pick if forced, with rationale.
- **Deferred work**: what the skill would have done after the human decides.

Escalations are not failures. They are the skill saying "here is the part of this engagement that genuinely requires you." The PSO consultant equivalent would be a one-page email asking the customer to choose.

## Inputs that come from humans

Some inputs are irreducibly human and the orchestrator collects them up-front. These include:

- Compliance constraints (HIPAA, PCI, FedRAMP, sovereignty).
- SLO targets per workload class.
- Migration window and acceptable downtime per workload.
- Cost ceilings and FinOps preferences.
- Identity provider (Workforce Identity Federation? Existing SSO?).
- Network reachability constraints (do GKE nodes need to reach the VPC the EKS cluster lives in during co-existence? for how long?).

These are gathered once, written to `00-orchestrator-state.json`, and referenced by every downstream skill so no one re-asks.

## Co-existence vs cutover

Portage assumes a **co-existence period** during which workloads run on both EKS and GKE for some non-zero time, and traffic shifts gradually. Skills that touch traffic, identity, or data are designed around this assumption:

- `identity-translation` builds Workload Identity bindings *additively*, so the EKS IRSA continues working until the workload is fully cut over.
- `network-translation` produces a hybrid topology where pods on either cluster can call services on either cluster (typically via a private cross-cloud connection or a temporary public ingress).
- `traffic-cutover` shifts weighted traffic, watches SLO impact, and pulls back automatically if guardrails trip.

A "big bang" cutover is supported but not the default. Big-bang requires explicit confirmation in the orchestrator.

## What the orchestrator does *not* do

- **Apply infrastructure changes.** It produces Terraform plans. A human (or a CI/CD job the human approves) applies them.
- **Modify the source EKS cluster.** Portage is read-only against EKS by default. The only EKS changes it ever recommends are scoped IAM grants for cross-account image pulls during co-existence, and even those are emitted as proposals.
- **Touch data without a runbook.** Data migration skills emit runbooks; they do not start replication or run mysqldumps unless explicitly invoked in a confirmed step.
- **Skip validation.** Every cutover step has an associated validation gate. Failed gates roll back automatically when in `auto-rollback: true` mode (the default).

## Extending Portage

To add a skill:

1. Read [CONTRIBUTING.md](../CONTRIBUTING.md) for the bar.
2. Create `skills/<your-skill>/SKILL.md` with valid frontmatter.
3. Add the skill to `manifest.json`.
4. Add it to the orchestrator's phase routing (or document it as a standalone-only skill).
5. Run end-to-end against a real environment.
6. Open the PR with the trace in the description.

To override a skill for your org without forking, vendor the skill folder into your own plugin and load that plugin *after* Portage. Last-loaded skill wins. This is the same pattern the Skills 2.0 ecosystem uses elsewhere.
