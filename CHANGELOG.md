# Changelog

All notable changes to Portage are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/), and the project follows [Semantic Versioning](https://semver.org/) once it reaches 1.0.

## [Unreleased]

### Added
- Initial OSS release scaffolding: `.github/` issue and PR templates, `CODEOWNERS`, `SECURITY.md`, `CHANGELOG.md`, `ROADMAP.md`, basic CI workflow.

## [0.1.0] — 2026-05

### Added
- 14 skills covering the full migration lifecycle: `portage-orchestrator`, `eks-discovery`, `migration-assessment`, `gke-landing-zone`, `network-translation`, `identity-translation`, `workload-translation`, `storage-translation`, `registry-migration`, `observability-translation`, `data-migration`, `traffic-cutover`, `rollback-playbook`, `post-migration-ops`.
- Phase-by-phase runbooks under `runbooks/`.
- Worked end-to-end example under `examples/walkthrough.md`.
- Reference materials: `service-mapping.md`, `api-translation.md`, reusable Terraform modules.
- Templates: readiness report, migration plan, runbook, postmortem, landing-zone design.
- Architecture and glossary docs.
- `reference/sources.md` — canonical source map (cloud.google.com, kubernetes.io, sre.google, CNCF) per skill.
- `reference/lessons-from-the-field.md` — citable knowledge base of 38 practitioner war stories from HN, Reddit, engineering blogs, GitHub issues, and conference talks.
- High-severity field lessons folded into the relevant skills' Common Pitfalls sections.
- Apache 2.0 license, Code of Conduct, Contributing guide.

### Known limitations
- Engine-change data migrations (DynamoDB→{Bigtable, Spanner, Firestore}, Aurora→AlloyDB with engine change, Redshift→BigQuery) are out of scope. They are scoped and handed back to a human.
- Multi-region cluster topologies beyond two regions are partially documented; see ROADMAP.md.
- Service mesh re-platforming (App Mesh → ASM) is documented but the translation is non-trivial; treated as an escalation.

[Unreleased]: https://github.com/geoffsdesk/portage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/geoffsdesk/portage/releases/tag/v0.1.0
