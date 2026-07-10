r"""
Portage Structure, Manifest & LFF Integrity Validator
=======================================================
Validates:
1. SKILL.md frontmatter (PyYAML / python-frontmatter) and description length [80, 1024].
2. 10 mandatory H2 headers on root SKILL.md files (`Purpose`, `When to use this skill`,
   `Prerequisites`, `Procedure`, `Decision points`, `Outputs / Deliverables`,
   `Validation`, `Escalation triggers`, `Common pitfalls`, `References`).
3. Manifest.json folder consistency and phase references.
4. Internal markdown link resolution across all .md files.
5. 100% LFF-* war story references: ensures every `### LFF-\d+` entry in
   `reference/lessons-from-the-field.md` is referenced somewhere across `skills/`.
"""

import argparse
import json
import os
import re
import sys
from typing import List, Set, Dict

try:
    import yaml
    import frontmatter
except ImportError:
    yaml = None
    frontmatter = None

ROOT_MANDATORY_H2 = [
    "Purpose",
    "When to use this skill",
    "Prerequisites",
    "Procedure",
    "Decision points",
    "Outputs / Deliverables",
    "Validation",
    "Escalation triggers",
    "Common pitfalls",
    "References",
]

# Alias normalization for headings that might use slightly different phrasing
HEADER_ALIASES = {
    "outputs": "Outputs / Deliverables",
    "outputs / deliverables": "Outputs / Deliverables",
    "when to use this skill": "When to use this skill",
    "purpose": "Purpose",
    "prerequisites": "Prerequisites",
    "procedure": "Procedure",
    "decision points": "Decision points",
    "validation": "Validation",
    "escalation triggers": "Escalation triggers",
    "common pitfalls": "Common pitfalls",
    "references": "References",
}


def validate_skills(repo_root: str) -> List[str]:
    errors = []
    skills_dir = os.path.join(repo_root, "skills")
    if not os.path.exists(skills_dir):
        return [f"Skills directory missing: {skills_dir}"]

    skill_count = 0
    for root, _, files in os.walk(skills_dir):
        for f in files:
            if f != "SKILL.md":
                continue
            skill_count += 1
            path = os.path.join(root, f)
            folder_name = os.path.basename(root)

            try:
                post = frontmatter.load(path) if frontmatter else _fallback_load(path)
            except Exception as e:
                errors.append(f"{path}: frontmatter parsing failed: {e}")
                continue

            name = post.metadata.get("name")
            desc = post.metadata.get("description", "")
            if not name:
                errors.append(f"{path}: missing 'name' in frontmatter")
            elif name != folder_name:
                errors.append(f"{path}: frontmatter name '{name}' != folder '{folder_name}'")

            if len(desc) < 80:
                errors.append(f"{path}: description too short ({len(desc)} chars, min 80)")
            if len(desc) > 1024:
                errors.append(f"{path}: description too long ({len(desc)} chars, max 1024)")

            # Check mandatory H2 headings for root SKILL.md files
            body = post.content
            h2_matches = re.findall(r"^##\s+(.+)$", body, re.MULTILINE)
            normalized_headers = {
                HEADER_ALIASES.get(h.strip().lower(), h.strip()) for h in h2_matches
            }

            for req in ROOT_MANDATORY_H2:
                if req not in normalized_headers:
                    errors.append(f"{path}: missing mandatory H2 header '## {req}'")

    print(f"Validated {skill_count} root SKILL.md files.")
    return errors


def _fallback_load(path: str):
    class Post:
        def __init__(self, metadata, content):
            self.metadata = metadata
            self.content = content

    content = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not m:
        return Post({}, content)
    meta_str = m.group(1)
    body_str = m.group(2)
    meta = {}
    for line in meta_str.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("'\"")
    return Post(meta, body_str)


def validate_manifest(repo_root: str) -> List[str]:
    errors = []
    manifest_path = os.path.join(repo_root, "manifest.json")
    if not os.path.exists(manifest_path):
        return [f"Missing manifest.json at {manifest_path}"]

    try:
        with open(manifest_path, encoding="utf-8") as fh:
            m = json.load(fh)
    except Exception as e:
        return [f"manifest.json invalid JSON: {e}"]

    skills = m.get("skills", [])
    for s in skills:
        p = os.path.join(repo_root, s["path"], "SKILL.md")
        if not os.path.exists(p):
            errors.append(f"manifest references missing skill file: {p}")
        folder_name = os.path.basename(s["path"])
        if folder_name != s["name"]:
            errors.append(f"manifest skill name '{s['name']}' != folder '{folder_name}'")

    phases = m.get("phases", [])
    for ph in phases:
        for sname in ph.get("skills", []):
            if not any(s["name"] == sname for s in skills):
                errors.append(f"phase {ph['id']} references unknown skill: {sname}")

    print(f"Validated manifest.json ({len(skills)} skills across {len(phases)} phases).")
    return errors


def validate_links(repo_root: str) -> List[str]:
    errors = []
    link_re = re.compile(r"\]\(([^)]+\.(?:md|yaml|json|tf|py))\)")
    for root, _, files in os.walk(repo_root):
        if ".git" in root or ".github" in root:
            continue
        for f in files:
            if not f.endswith(".md"):
                continue
            path = os.path.join(root, f)
            body = open(path, encoding="utf-8").read()
            for m in link_re.finditer(body):
                target = m.group(1).split("#")[0]  # remove anchor
                if not target or target.startswith("http"):
                    continue
                rel = os.path.normpath(os.path.join(os.path.dirname(path), target))
                if not os.path.exists(rel):
                    errors.append(f"{path} -> link target '{target}' (resolved {rel}) MISSING")

    print("Validated internal link resolution across markdown files.")
    return errors


def validate_lff_coverage(repo_root: str) -> List[str]:
    errors = []
    lff_path = os.path.join(repo_root, "reference", "lessons-from-the-field.md")
    if not os.path.exists(lff_path):
        return [f"Missing {lff_path}"]

    body = open(lff_path, encoding="utf-8").read()
    # Find all ### LFF-XX headings
    lff_ids = set(re.findall(r"^###\s+(LFF-\d+)", body, re.MULTILINE))
    if not lff_ids:
        return ["No LFF-\\d+ headings found in lessons-from-the-field.md"]

    # Scan all skill files in skills/ for occurrences of LFF-XX
    found_lffs: Set[str] = set()
    skills_dir = os.path.join(repo_root, "skills")
    for root, _, files in os.walk(skills_dir):
        for f in files:
            if f.endswith(".md"):
                content = open(os.path.join(root, f), encoding="utf-8").read()
                for lff_id in lff_ids:
                    if lff_id in content:
                        found_lffs.add(lff_id)

    missing = lff_ids - found_lffs
    if missing:
        errors.append(
            f"The following LFF war stories in lessons-from-the-field.md are never referenced across skills/: {', '.join(sorted(missing))}"
        )

    print(f"Validated LFF coverage ({len(found_lffs)}/{len(lff_ids)} war stories referenced across skills/).")
    return errors


def main():
    ap = argparse.ArgumentParser(description="Portage validation CLI.")
    ap.add_argument("--repo-root", default=".", help="Root of portage repository")
    ap.add_argument("--check-manifest", action="store_true", help="Only check manifest.json")
    ap.add_argument("--check-links", action="store_true", help="Only check markdown links")
    ap.add_argument("--check-lff", action="store_true", help="Only check LFF coverage")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    errors = []

    if args.check_manifest:
        errors.extend(validate_manifest(repo_root))
    elif args.check_links:
        errors.extend(validate_links(repo_root))
    elif args.check_lff:
        errors.extend(validate_lff_coverage(repo_root))
    else:
        errors.extend(validate_skills(repo_root))
        errors.extend(validate_manifest(repo_root))
        errors.extend(validate_links(repo_root))
        errors.extend(validate_lff_coverage(repo_root))

    if errors:
        print("\n=== Validation Errors Detected ===", file=sys.stderr)
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nAll Portage validation checks passed successfully!")


if __name__ == "__main__":
    main()
