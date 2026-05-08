# Portage Roadmap

This document sketches how Portage evolves from a skill library that runs inside a generic agent runtime today into a complete agentic migration tool that an SRE can drive by prompt.

It is intentionally opinionated about *direction* and intentionally vague about *dates*. We move only when each stage is producing real value for real users on real migrations.

## Where we are — Stage 1: Skills + Claude Code

**Status: Released as v0.1.0.**

What works today:
- The 14 skill folders in `skills/` are loadable by any agent runtime that reads `SKILL.md` frontmatter — Claude Code, Cowork, the Claude Agent SDK, custom harnesses.
- A user with a Claude session and Portage installed can drive the orchestrator with a single prompt: "Use the portage-orchestrator skill to plan a migration of my EKS estate to GKE." The orchestrator chains the sub-skills, asks clarifying questions, and writes artifacts under `./portage-output/<run-id>/`.
- Every artifact is human-readable Markdown, YAML, JSON, or HCL. Every change is reviewable.

Limits:
- The orchestrator state machine is convention-driven, not enforced. A different agent or a session interruption can drift from the contract.
- Artifact handoffs between skills are typed by *naming* (`identity-map.json`, `inventory.json`), not by schema validation.
- There is no built-in CLI, no progress dashboard, no cross-session resume guarantee.
- Real-world cloud actions (terraform apply, kubectl, gcloud) are still operator-driven; the agent emits commands; the human runs them.

This is enough to be useful. It is not enough to feel like a finished product.

## Stage 2 — `portage` CLI on the Claude Agent SDK

**Goal: a single binary / Python package that wraps the orchestrator state machine and gives the migration a coherent command-line UX.**

Sketch:

```bash
$ pipx install portage
$ portage init --aws-account 123456789012 --gcp-org example.com --window 90d
   ↳ Creates ./portage-output/<run-id>/ and writes 00-orchestrator-state.json.

$ portage discover
   ↳ Invokes the eks-discovery skill via the Claude Agent SDK.
   ↳ Streams progress to the terminal; writes inventory.json, inventory-summary.md, escalations.md.

$ portage assess
   ↳ Invokes migration-assessment. Produces readiness-report.md.
   ↳ Exits non-zero if grade is "blocked" or "high-risk".

$ portage plan landing-zone
$ portage apply landing-zone --dry-run
$ portage apply landing-zone   # explicit confirmation prompt

$ portage cutover --workload payments-api --ramp slow --auto-rollback
   ↳ Drives the traffic-cutover skill against live cloud APIs.
   ↳ Polls Cloud Monitoring; halts on gate breach; auto-rolls back if configured.

$ portage status
   ↳ Reads orchestrator-state.json. Shows which workloads are at which weight,
     open escalations, expected cost vs ceiling, etc.

$ portage resume
   ↳ Picks up where a previous session left off based on state file.
```

What this requires:

1. **A Python package** (`portage`) that uses the Claude Agent SDK to load the skills, build a typed graph, and run the state machine. Each CLI command maps to a single skill invocation with structured arguments and structured outputs.
2. **A formal artifact schema** — `pydantic` (Python) or `zod` (TypeScript) types for every artifact (`Inventory`, `ReadinessReport`, `IdentityMap`, etc.). Schema validation between skill calls catches contract drift.
3. **A small set of cloud-side helper integrations** — thin wrappers around `aws`, `gcloud`, `kubectl`, `terraform`, `skopeo`. These make commands the agent generates *executable* with confirmation, rather than requiring copy-paste.
4. **Cross-session state recovery** — `00-orchestrator-state.json` becomes the source of truth for resume; the CLI re-hydrates a session from it.
5. **A test corpus of synthetic EKS environments** to validate the CLI doesn't regress.

Open design choices:
- Model provider neutrality. Claude is the primary target; the SDK abstraction should keep room for a runner that uses other providers without rewriting the skills.
- Whether to expose individual skills as their own subcommands (`portage skill workload-translation --workload payments-api`) or keep the CLI phase-shaped.
- How to handle long-running operations (DMS, Storage Transfer Service) where the agent shouldn't hold a session for hours.

Validation: a real team migrates a real (non-trivial) EKS estate end-to-end, driven entirely by the CLI, with the orchestrator's prompts as their primary UI.

## Stage 3 — Multi-agent orchestration with MCP

**Goal: each skill becomes an addressable agent. A control plane coordinates them. Migrations run with parallelism, real-time monitoring, and a web view.**

Sketch:
- Each skill is published as an MCP server. Inputs and outputs are typed; the skill is callable from any MCP-aware client.
- The orchestrator is its own agent that consumes the other skill agents' MCP interfaces.
- An optional web dashboard (`portage ui`) shows live state: current phase, current workload, last gate evaluation, open escalations, cost projection, decommission timeline.
- Skills that can run in parallel (e.g., `storage-translation` and `registry-migration` in Phase 3) actually do, with fan-out / fan-in coordinated by the orchestrator.
- Cloud-side integrations that today are CLI wrappers become MCP servers themselves — `mcp-aws`, `mcp-gcp`, `mcp-kubectl`, `mcp-terraform`. They expose typed actions with explicit confirmation contracts (no destructive call without an approval signal).
- A migration becomes a *graph*: nodes are skill invocations, edges are typed artifacts, and the runtime can replay or partially re-run sub-graphs.

What this enables:
- **Parallelism**: Phase 3's four translation skills run concurrently against the same inventory; cuts total elapsed time.
- **Real-time observability**: a web tab shows the live trace; ops teams who don't read terminal output can still follow the migration.
- **Replay**: a failed cutover for one workload doesn't invalidate the surrounding state; only that workload's branch re-runs.
- **Plugin model**: third-parties (e.g., a partner operating in regulated industries) ship their own MCP server that adds a custom validation gate — say, FedRAMP or PCI control checks — without touching core Portage.

What this requires:
- MCP server scaffolding for each skill (mostly mechanical given Stage 2 schemas).
- A control-plane process that holds run state, dispatches skill calls, and exposes a streaming API.
- A small front-end (Next.js + a state stream) for the dashboard.
- A "deny by default" policy engine in front of every cloud-side MCP server so that destructive calls always need explicit human approval, even when the orchestrator could in principle approve them.

Validation: a multi-cluster, multi-region migration runs to completion with the dashboard as primary UI, the agent-side prompt as secondary UI.

## Stage 4 — Hosted service (optional)

**Goal: a managed Portage that non-technical buyers can authorize via cross-account role and run without standing up infrastructure.**

This is a business question, not just an engineering one. The OSS skills + CLI + control plane are sufficient for an in-house platform team to operate. A hosted offering only makes sense if there is demand from teams that:
- Want PSO outcomes without a PSO budget.
- Don't have the ops capacity to run the control plane themselves.
- Are comfortable granting cross-account read access to a third party.

If we go there, the hosted product is the open-source control plane plus:
- Cross-account credentials brokering (with the hardest possible defaults: read-only on AWS, scoped IAM on GCP).
- A multi-tenant control plane.
- Audit logs accessible to the customer and immutable from the operator side.
- A pricing model (per migration / per workload / subscription).
- A support SLA.

This stage is optional. Stages 1–3 stand on their own.

---

## Agentic UX patterns — how a user actually drives this

Independent of the stage, the user's interface to Portage is some combination of:

### Conversational orchestrator (today)

User opens an agent session, types one prompt, and the orchestrator runs the program. Clarifying questions arrive in batches of 3–4. Confirmation gates surface as clearly bounded yes/no decisions. Artifacts appear in a known directory. Escalations stop progress with a structured note.

This is the pattern v0.1.0 supports natively. Strength: zero infrastructure, low ceremony. Weakness: long sessions, no resume, no real-time view for non-driver stakeholders.

### CLI + watch mode (Stage 2)

`portage run --watch` shows a live progress table (cohort, weight, gates, soak countdown). Confirmation prompts inline. State on disk. Resume works.

Pattern fit: SREs running migrations from their own terminal. Maps onto how teams already drive Terraform and kubectl.

### Slack-bot mode (Stage 2 add-on, light)

Portage as a Slack app. The migration produces a thread; phase events post into it. Approval gates land as message buttons. Status queries run as slash commands.

Pattern fit: stakeholder visibility during a live cutover. Engineers approve gates from wherever they are.

### GitHub Actions / GitOps mode (Stage 2 / 3)

Migration plan committed to a repo. Each phase produces artifacts as PRs. Confirmation = merging the PR. Apply-side actions trigger from `main`. Audit trail is git history.

Pattern fit: regulated environments where every change must be traceable. Aligns with how landing-zone Terraform is already managed.

### Web dashboard (Stage 3)

Live view of the migration graph. Click into a phase, see the live trace. Approve gates from the UI. Re-run sub-graphs. Export the run as a single PDF for the post-migration review.

Pattern fit: large migrations with multiple stakeholders, where the agent thread is too narrow a UI for the audience.

### IDE extension (longer-term)

A VS Code (and competitor) panel exposing skills as commands and artifacts as files. Particularly valuable for the workload- and storage-translation phases where the diff IS the unit of review.

Pattern fit: developer-led migrations where engineers want the migration in their existing editor.

The skills do not change as we move between these UX patterns. They are the stable substrate; the UX is configuration around them.

---

## What we will NOT do

Some directions we'd be tempted toward but will resist unless data forces us:

- **Auto-execution without confirmation.** The whole point is an auditable migration. "It applied itself overnight" is a feature only on demo day; in production it's a way to lose customer trust.
- **A proprietary DSL for migrations.** The skill format is the DSL. Adding another layer ossifies the project.
- **A walled garden.** The skills must remain runnable in any compliant agent runtime. We do not use Claude-specific affordances in skill bodies that would break portability.
- **Customer-pinned forks.** If an org needs proprietary modifications, they vendor the skills they care about into their own plugin and load it after Portage. This is the standard Skills 2.0 override pattern. We do not maintain customer-specific branches.
- **Premature scale-out.** Two test customers running successful end-to-end migrations are worth more than fifty stars on GitHub. We optimize for the first ten real runs, not the first thousand watchers.

---

## Contributing to the roadmap

Open an issue with the `roadmap` label. Be specific:
- What stage is this aiming at?
- What's the next 90-day deliverable?
- What does success look like in measurable terms?

PRs that move the roadmap forward incrementally — one CLI command implemented, one MCP server scaffolded, one cloud integration written — are the main currency.
