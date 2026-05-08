# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in Portage — for example a skill that would cause an agent to leak credentials, exfiltrate data, or take destructive action without confirmation — please report it privately.

**Do not open a public GitHub issue for security vulnerabilities.** Instead, use one of:

- GitHub's private vulnerability reporting on this repo (Security tab → "Report a vulnerability").
- Email the maintainers (see `MAINTAINERS` file or repo settings).

We aim to acknowledge a report within 5 business days and to provide a resolution path within 30 days.

## What counts as a Portage security issue

- A skill that, if loaded by a compliant agent runtime, would cause the agent to perform a destructive action (delete production resources, transfer data outside the user's environment, write credentials anywhere unsafe) without explicit user confirmation.
- A skill that recommends a configuration that is materially less secure than current GKE / cloud baseline (for example, a hardening control we mistakenly recommend disabling).
- A reference Terraform module that would provision an insecure resource by default (for example, public IPs on resources that should be private).
- A documented command or script in a runbook that would, if pasted into a shell, leak credentials or grant overbroad access.

## What is *not* a Portage security issue

- A bug in Google Cloud, Anthropic, or any third-party service Portage references — please report those upstream.
- A bug in a downstream user's own infrastructure that surfaced during a Portage-driven migration. Portage skills are advisory; the human-in-the-loop is the final security boundary.

## Scope

This policy covers content in this repository: `skills/`, `reference/`, `templates/`, `runbooks/`, `examples/`, `docs/`, and the top-level meta files. It does not cover forks, vendor distributions, or third-party plugins that bundle Portage.
