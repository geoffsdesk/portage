## What this PR does

<!-- 1–3 sentences. What changes, and why. -->

## Type of change

- [ ] Bug fix in an existing skill
- [ ] Tightening of an existing skill (clarity, command accuracy, escalation language)
- [ ] New entry in `reference/lessons-from-the-field.md`
- [ ] New canonical source in `reference/sources.md`
- [ ] Reference material (Terraform module, template, runbook)
- [ ] New skill (must follow the bar in `CONTRIBUTING.md`)
- [ ] Repo meta / docs / CI

## Issue link

<!-- Reference an issue number, or "discussed in #..." -->

## How was this validated?

<!--
For skill changes: paste the trace of running the skill end-to-end on a real or representative environment.
For lessons: confirm the source URL resolves and the author attribution matches the page.
For new skills: confirm two SREs at two different orgs could execute end-to-end without your help.
For meta / docs: describe the manual checks performed.
-->

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] One area of change per PR (no mixed-concerns PRs).
- [ ] No verbatim quotes >15 words from any source.
- [ ] All cited URLs resolve at the time of submission.
- [ ] Frontmatter on any modified `SKILL.md` is valid (see CI).
- [ ] If this changes user-facing behavior, the relevant runbook in `runbooks/` is updated.
- [ ] If this is a new entry in `lessons-from-the-field.md`, the indexes (by category and by skill) are updated.
- [ ] Updated `CHANGELOG.md` under `[Unreleased]`.
