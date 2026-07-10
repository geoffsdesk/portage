# Contributing to Portage

Thanks for considering a contribution. Portage is intentionally small and intentionally opinionated. Please read this whole document before opening a PR — it will save us both time.

## What we want

- **Bug fixes and corrections** to existing skills (a translation that's wrong, a command that no longer works, a recommendation that contradicts current GKE guidance).
- **Tightening** of existing skill prompts: clearer triggers, better escalation language, more precise output schemas.
- **New reference content**: Terraform modules, service mappings, runbook templates that one of the existing 14 skills can call into.
- **Friction logs**: write up what broke when you ran Portage on a real migration. These are gold.
- **New entries in [reference/lessons-from-the-field.md](reference/lessons-from-the-field.md)** — citable practitioner war stories that the existing skills should anticipate. See the *Contributing* section in that file for the entry format. The bar: a verifiable URL, an attributable author, paraphrased lesson (≤15 words verbatim), an owning skill, and a justified severity rating.

## What we don't want (yet)

- **Fifty new skills.** The bar for a new top-level skill is high: it must cover a phase that the existing 14 demonstrably do not, and it must be runnable end-to-end by an SRE who has never seen Portage. If your idea is a sub-pattern of an existing skill, contribute it as a referenced section, not a new skill.
- **Speculative features.** No "future-looking" skills for GCP services that have not GA'd. We will add support after launch, not before.
- **Tooling lock-in.** Skills must work with any agent runtime that loads `SKILL.md`-format files. Do not introduce dependencies on a specific orchestrator, plugin format, or model provider.

## The skill bar

A new skill ships when **two SREs at two different companies can execute it end-to-end on their own infrastructure without our help**. This is not a slogan. It is the merge criterion.

Concretely, a passing skill has:

1. A `SKILL.md` with valid frontmatter (`name`, `description`).
2. A `description` field that triggers the skill on the right kinds of requests and *does not* trigger it on the wrong kinds. Test this with five real-sounding prompts before submitting.
3. Explicit `Purpose`, `When to use this skill`, `Prerequisites`, `Procedure`, `Decision points`, `Outputs / Deliverables`, `Validation`, `Escalation triggers`, `Common pitfalls`, and `References` sections (these exactly 10 mandatory H2 headings are checked by `portage-validate`).
4. **Deny-by-Default HITL Confirmation**: Any destructive cloud command or data mutation (`dms start-replication-task`, `gcloud sql instances promote`, `terraform apply`) must require an interactive confirmation gate displaying the exact command, target environment, and cost impact before running.
5. Real commands. Not pseudocode. Not "run the appropriate `gcloud` command". The actual command, with the actual flags, that the SRE should run.
6. At least one worked example showing input → output.
7. A list of failure modes the skill has seen in the wild and how it handles each (`Common pitfalls`). All new practitioner entries added to `reference/lessons-from-the-field.md` must be cross-referenced by at least one skill.

## Style

- **Imperative, terse, factual.** "Create the cluster with these flags." Not "you might want to consider creating a cluster, perhaps with the following flags".
- **Show diffs.** When a skill rewrites a manifest, it shows the before, the after, and the rationale.
- **Cite when you assert.** If you say "GKE does X" in a customer-facing skill, link to the public doc that says so. If the public doc disagrees with the internal truth, the skill says so explicitly and flags the discrepancy.
- **No emojis** in skill files unless the user asked for them.

## How to propose a change

1. Open an issue describing what you're trying to fix or add. For non-trivial changes, *wait for ack* before writing the PR.
2. Branch from `main`, name your branch `<area>/<short-description>` (`workload-translation/helm-values-overrides`).
3. One skill change per PR. Mixed changes get split or rejected.
4. Run the skill end-to-end on a real or representative environment. Paste the trace into the PR description.
5. Update `docs/CHANGELOG.md` under the next unreleased version.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Short version: be a professional, assume good faith, give precise feedback.

## License

By submitting a contribution, you agree that it will be released under [Apache 2.0](LICENSE).
