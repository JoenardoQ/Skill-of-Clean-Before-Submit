# Clean Before Commit

## Purpose

`clean-before-commit` is a Codex Skill that audits the exact Git change set
before a commit or push. It identifies secret exposure, production or personal
data, generated debris, obsolete scaffolding, debug residue, stale fixtures,
large or unexpected files, unrelated changes, and unnecessary code or
architecture before they reach repository history or a remote.

## Safety boundary

The Skill is read-only by default. Invocation does not authorize deletion,
staging, committing, pushing, credential use, or any other external write.
Before a mutation it resolves the exact repository, paths, diff, target branch,
and current authority. Ambiguous or pre-existing files are reported for a user
decision rather than deleted.

Secret values are never printed. If a real credential may have entered Git
history, removing the local file is insufficient: the Skill blocks publication
and reports that revocation and history remediation require separate decisions.

## Workflow

The Skill:

1. resolves repository root, branch, upstream, worktree state, index state, and
   the exact staged diff;
2. inventories staged, unstaged, untracked, ignored, binary, and large files;
3. runs the bundled read-only scanner to inventory every staged change status
   and inspect content-bearing staged and untracked entries with bounded reads,
   without following untracked symlinks or treating scanner output as proof of
   safety;
4. classifies blockers, review items, unrelated work, and verified intentional
   files with evidence and proposed remediation;
5. performs only authorized cleanup, then runs relevant tests and rebuilds the
   index with explicit paths; and
6. re-audits the final staged bytes before any separately authorized commit or
   push and verifies the requested remote revision after pushing.

## Architecture

```text
SKILL_Clean_Before_Commit/
├── ITERATION_STATE.md
├── README.md
├── README.zh-CN.md
├── evaluation/
│   └── eval-spec.json
├── release-policy.json
├── tests/
│   └── test_audit_staged.py
└── clean-before-commit/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/review-policy.md
    └── scripts/audit_staged.py
```

Only `clean-before-commit/` is installed. Tests, evaluation artifacts, the
release policy, and the iteration record remain outside the runtime bundle.

## Prerequisites

- Git 2.x with a readable local repository and index.
- Python 3.10 or later; the scanner uses only the standard library.
- Codex or another host that can discover Agent Skills for runtime use. Host
  discovery and behavior still require independent verification.

## Installation

From the repository root:

```bash
mkdir -p "$HOME/.agents/skills"
ln -s "$(pwd)/clean-before-commit" \
  "$HOME/.agents/skills/clean-before-commit"
```

Resolve an existing destination before replacement. Avoid duplicate source and
installed copies, then restart Codex if needed.

## Validation

Run the dependency-free checks from the repository root:

```bash
python3 -B tests/test_audit_staged.py
python3 "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" \
  clean-before-commit
```

Maintainers with the Agent Skill Author project can run the release-policy and
evaluation-spec validators without assuming a particular checkout location:

```bash
export AGENT_SKILL_AUTHOR_ROOT=/path/to/SKILL_Agent_Skill_Author
python3 "$AGENT_SKILL_AUTHOR_ROOT/agent-skill-author/scripts/validate_skill.py" \
  clean-before-commit --policy release-policy.json
python3 "$AGENT_SKILL_AUTHOR_ROOT/agent-skill-author/scripts/validate_eval_spec.py" \
  evaluation/eval-spec.json
```

The scanner exits `0` when it finds no items, `1` when it emits one or more
blocker or review findings, and `2` for invalid invocation or an audit/Git
failure. JSON output retains `repository`, `staged_files`, `untracked_files`,
`findings`, `summary`, and `limitations`, and adds `staged_changes` with status,
path, prior path when applicable, and old/new Git modes.

JSON output is valid UTF-8. Filesystem bytes that are not valid UTF-8, along with
control characters, are emitted as JSON escape sequences instead of raw bytes;
text output applies the same safety boundary to paths and diagnostics.

## Acceptance and limitations

Acceptance requires deterministic read-only scanning, an inventory of additions,
Git-reported copies, deletions, modifications, renames, and type changes, bounded
content reads, non-following treatment of untracked symlinks, redacted diagnostics,
explicit authority gates, final-index reinspection, passing local tests, and a
runtime bundle without development debris. Placeholder suppression must match a
documented synthetic value or environment-variable reference as a complete
value; a credential-like value is not safe merely because it contains words
such as `example`, `dummy`, or `redacted`. Quoted assignment values are assessed
as complete values, including embedded spaces. Tests must trace the scanner's
blocker, review, clean, and error exits to its material Git-state, file, resource,
and trust boundaries.

Pattern scanning can produce false positives and cannot prove the absence of
secrets, obsolete design, or hidden dynamic consumers. Untracked content is a
worktree snapshot and can change after inspection; the final Git index must
still be re-read before commit. The source-linked Skill is installed at its
renamed location. Automatic routing, entrypoint loading, full behavior
evaluation, remote readback, and recovery paths remain unverified without
independent lifecycle evidence.
