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
3. runs the bundled read-only staged-content scanner and available repository
   checks without treating scanner output as proof of safety;
4. classifies blockers, review items, unrelated work, and verified intentional
   files with evidence and proposed remediation;
5. performs only authorized cleanup, then runs relevant tests and rebuilds the
   index with explicit paths; and
6. re-audits the final staged bytes before any separately authorized commit or
   push and verifies the requested remote revision after pushing.

## Architecture

```text
SKILL_Clean_Before_Commit/
├── README.md
├── README.zh-CN.md
├── evaluation/
│   └── eval-spec.json
├── tests/
│   └── test_audit_staged.py
└── clean-before-commit/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/review-policy.md
    └── scripts/audit_staged.py
```

Only `clean-before-commit/` is installed. Tests and evaluation artifacts remain
outside the runtime bundle.

## Installation

```bash
mkdir -p ~/.agents/skills
ln -s "/home/joenardo/My Projects/SKILL_Clean_Before_Commit/clean-before-commit" \
  ~/.agents/skills/clean-before-commit
```

Resolve an existing destination before replacement. Avoid duplicate source and
installed copies, then restart Codex if needed.

## Validation

```bash
python3 -B tests/test_audit_staged.py
python3 "$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py" \
  clean-before-commit
python3 "$HOME/My Projects/SKILL_Agent_Skill_Author/agent-skill-author/scripts/validate_skill.py" \
  clean-before-commit --policy release-policy.json
python3 "$HOME/My Projects/SKILL_Agent_Skill_Author/agent-skill-author/scripts/validate_eval_spec.py" \
  evaluation/eval-spec.json
```

## Acceptance and limitations

Acceptance requires deterministic read-only scanning, redacted diagnostics,
explicit authority gates, final-index reinspection, passing local tests, and a
runtime bundle without development debris. Placeholder suppression must match a
documented synthetic value or environment-variable reference as a complete
value; a credential-like value is not safe merely because it contains words
such as `example`, `dummy`, or `redacted`. Tests cover the scanner's blocker,
review, clean, and error exits plus its material file and trust boundaries.

Pattern scanning can produce false positives and cannot prove the absence of
secrets, obsolete design, or hidden dynamic consumers. The source-linked Skill
is installed at its renamed location. Automatic routing, entrypoint loading,
full behavior evaluation, remote readback, and recovery paths remain unverified
without independent lifecycle evidence.
