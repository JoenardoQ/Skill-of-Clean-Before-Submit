# Pre-commit Review Policy

## Evidence order

Review the exact candidate in this order:

1. repository identity, instructions, branch, upstream, and intended scope;
2. index state and staged bytes;
3. unstaged and untracked work that may be accidentally included or omitted;
4. ignore rules and generated boundaries;
5. tests, static checks, dependency changes, and build reproducibility;
6. final staged diff immediately before commit;
7. remote readback after an authorized push.

Re-read state after cleanup because any edit or staging action invalidates the
previous candidate evidence.

## Finding classes

### Blocker

- possible API key, token, password, private key, connection string, or real
  credential material;
- personal, customer, confidential, or production data;
- a material test/build failure attributable to the candidate;
- an unexpected binary, dump, archive, generated bundle, or large file with no
  verified consumer;
- ambiguous repository, branch, remote, staged scope, or publication target;
- unresolved partial mutation or a staged diff that differs from the reviewed
  bytes.

### Review

- caches, logs, coverage output, temporary files, editor state, generated
  scaffolding, sample applications, debug statements, stale fixtures, or old
  snapshots;
- unused or redundant dependencies, adapters, abstractions, implementations,
  configuration, tests, or documentation;
- lockfile, schema, migration, vendored, generated, binary, or large-file
  changes requiring provenance and reproducibility evidence;
- broad formatting churn, mass rename, or unrelated changes mixed into scope.

### Intentional

Mark an item intentional only when the current change contract or an observed
consumer establishes its need. “It was already present,” “the generator made
it,” and “tests pass” do not establish necessity.

### Unassessed

Use this when dynamic discovery, missing tools, inaccessible files, encrypted or
binary content, incomplete history, or unavailable environment evidence prevents
a reliable conclusion. Unassessed high-impact content blocks publication.

## Secret handling

Never print a suspected value. Report only severity, rule, path, line when safe,
and remediation class. Do not add a real secret to an allowlist. Use a documented
placeholder or scanner-specific fingerprint suppression only after confirming
the value is synthetic. Placeholder suppression must match the complete value;
do not suppress a credential-like value merely because it contains a marker such
as `example`, `dummy`, or `redacted` as a substring.

If a credential was committed previously, removing it from the next commit does
not revoke it or remove prior copies. Stop publication, determine exposure with
read-only history checks, rotate or revoke through the credential owner, and
rewrite history only with explicit approval and a coordinated recovery plan.

## Cleanup authority

- Read-only inspection may proceed within the repository scope.
- Editing newly introduced, clearly in-scope content may proceed when the user
  asked to prepare or clean the change.
- Deleting ambiguous or pre-existing material requires a concrete decision.
- Commit requires an explicit commit request.
- Push requires an explicit push request and a resolved remote/branch target.
- History rewriting, force push, credential rotation, production-data handling,
  and public release each require separate authorization.

## Final gate

Do not commit or push until the final staged bytes have been re-inspected, every
blocker is resolved, review items are intentional or excluded, relevant checks
pass or their limitations are accepted, and unrelated user work remains outside
the candidate.
