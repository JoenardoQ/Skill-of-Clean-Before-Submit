# Review Policy

Use while deciding whether candidate content should enter a commit or remote.

## Classify findings

| Class | Meaning and action |
| --- | --- |
| Blocker | Suspected real secrets or unauthorized sensitive data; unresolved target or outgoing range; material failed checks; unassessed high-impact content. Stop the affected publication until resolved. |
| Review | Deletions, renames, type changes, generated files, unusual size, obsolete code, or other content needing intent and consumer inspection. Resolve using evidence; this is not an automatic approval request. |
| Intentional | The user's goal or a verified consumer establishes why the content belongs. Record the reason where it helps review. |
| Unrelated | Outside the requested change; preserve it and keep it out of this candidate. |
| Unassessed | Inspection is incomplete or unavailable. Describe the practical gap; high-impact uncertainty blocks publication. |

Presence in the repository does not establish necessity, and a scanner warning does not establish a defect. For a removal, identify what used the resource and whether those consumers remain. For an abstraction, identify the current variations or constraints it serves.

Inspect ignored paths when they are relevant to the candidate or would be exposed by an ignore-rule change. Do not recursively read unrelated private files as a precaution.

## Protect sensitive content

Never print a suspected value. Report the path, rule, and line where safe, plus the remediation needed. Do not include raw secrets in examples, diagnostic output, commit messages, or review records.

Treat a quoted credential assignment as a whole value, including spaces. A value is not synthetic merely because it contains words such as `example`, `dummy`, or `redacted`. Exempt only verified complete synthetic values or documented environment-variable references.

If sensitive content may already be committed, inspect the relevant outgoing or historical range without reproducing the value. Removing it in the newest tree does not remove it from earlier commits. Credential revocation and history repair are separate actions requiring suitable authority; do not perform them under a general cleanup request.

## Preserve the review boundary

Existing explicit authorization remains effective for the resolved action. Reconfirm only when new evidence changes its scope, destination, or consequences.

A cleanup request permits removal of verified, in-scope debris; it does not permit deleting ambiguous user material. A commit request does not authorize push, and neither implies force push, history rewriting, credential rotation, or a separate release.

Before a commit, verify the index still matches the reviewed candidate. Before a push, verify the intended outgoing commits and remote branch. If either changed after review, inspect the change that invalidated the earlier evidence.
