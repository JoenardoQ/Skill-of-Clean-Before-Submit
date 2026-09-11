# Clean Before Commit

[简体中文](README.zh-CN.md)

## Purpose

Review the exact Git candidate before commit or push. Detect sensitive content, generated debris, obsolete scaffolding, debug residue, unrelated edits, and unnecessary code or architecture while preserving required behavior.

The skill is a procedure usable by agents with repository access. Its bundled scanner assists with mechanical inspection; it does not decide whether an architecture or deletion is justified.

## Use

Read `clean-before-commit/SKILL.md`, or install the complete `clean-before-commit/` directory through the chosen host's skill mechanism. Optional `agents/openai.yaml` provides Codex interface metadata.

```text
Use $clean-before-commit to review the staged change. Report findings only.
```

```text
Use $clean-before-commit to clean the requested changes, then commit and push
them to the configured upstream. Preserve unrelated working files.
```

A review alone is read-only. Existing explicit cleanup, commit, and push authorization remains effective within its scope. Ambiguous ownership, a changed destination, history rewriting, or credential remediation requires a separate decision.

## Workflow

1. Identify the repository, intended work, candidate, and authority.
2. Inspect the index and relevant working files for a commit; inspect outgoing commits for a push.
3. Run the scanner when available and assess its findings against real consumers and requirements.
4. Clean only verified, authorized material and run affected checks.
5. Review the final index, commit if requested, and verify the remote branch after an authorized push.

A clean index does not establish that outgoing commits are safe. Content removed in a later commit can still be present in the history being pushed.

## Scanner

Requires Git and Python 3.10 or later; uses only the Python standard library. From a checkout:

```bash
python3 clean-before-commit/scripts/audit_staged.py --repo /path/to/repository
python3 clean-before-commit/scripts/audit_staged.py --repo /path/to/repository --json
```

Resolve the script relative to the installed skill when running elsewhere. Without Python, use equivalent read-only tools and identify uninspected content.

| Exit code | Meaning |
| --- | --- |
| 0 | No scanner findings |
| 1 | Blocker or review findings require assessment |
| 2 | Invocation or audit failure |

The scanner inventories staged changes and untracked files, uses bounded reads, avoids following untracked symlinks, and redacts suspected values. It does not inspect all unstaged content, ignored files, or outgoing history. Review warnings do not automatically block a verified intentional change; unresolved high-impact content does.

JSON includes `repository`, `staged_files`, `staged_changes`, `untracked_files`, `findings`, `summary`, and `limitations`. Paths and diagnostics escape unsafe characters. Pattern scanning can miss secrets or produce false positives.

## Maintenance and verification

Run the scanner's existing tests from the repository root:

```bash
python3 -B tests/test_audit_staged.py
git diff --check
```

Also inspect the skill's links and exercise decisions affected by instruction changes: review-only work, authorized cleanup, intentional scanner findings, and a push with already committed changes.

Keep the scanner and tests together when changing executable behavior. The runtime directory contains the entrypoint, review policy, scanner, and UI metadata. Development records belong outside the runtime and formal documentation.

Never print suspected secrets. A removed credential may still require revocation and authorized history remediation; neither is implied by a general cleanup request.
