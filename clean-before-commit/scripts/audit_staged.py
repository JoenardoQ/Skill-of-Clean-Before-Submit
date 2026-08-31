#!/usr/bin/env python3
"""Read-only audit of staged and untracked Git content with redacted findings."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


ARTIFACT_PATH = re.compile(
    r"(^|/)(node_modules|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|"
    r"\.tox|coverage|htmlcov|dist|build|out|target|tmp|temp|logs?)(/|$)",
    re.IGNORECASE,
)
PRODUCTION_DATA_PATH = re.compile(
    r"(^|/)[^/]*(prod|production|customer|backup|dump)[^/]*"
    r"\.(csv|tsv|jsonl?|sql|dump|db|sqlite3?|parquet|zip|tar|gz)$",
    re.IGNORECASE,
)
ENV_FILE = re.compile(r"(^|/)\.env(?:\..+)?$", re.IGNORECASE)
SAFE_ENV_FILE = re.compile(r"(^|/)\.env\.(example|sample|template)$", re.IGNORECASE)
PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
KNOWN_SECRET_PREFIX = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[A-Z0-9]{16})\b"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)[\"']?\b(?:[a-z0-9]+[_-])*(?:api[_-]?key|secret|token|password|passwd|"
    r"client[_-]?secret|access[_-]?key|connection[_-]?string)\b[\"']?\s*[:=]\s*(?P<value>.+)$"
)
DEBUG_MARKER = re.compile(
    r"(?:\bdebugger\s*;|\bconsole\.log\s*\(|\bbreakpoint\s*\(\s*\)|"
    r"\bpdb\.set_trace\s*\()"
)
SAFE_LITERAL_VALUES = frozenset(
    {
        "changeme",
        "dummy-value",
        "example-value",
        "placeholder",
        "redacted",
        "redacted-value",
        "sample-value",
        "test-only",
        "test-only-value",
    }
)
SAFE_ENV_REFERENCE = re.compile(
    r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"process\.env\.[A-Za-z_][A-Za-z0-9_]*|"
    r"os\.environ\[\s*[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\s*\]|"
    r"os\.environ\.get\(\s*[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\s*\)|"
    r"(?:os\.)?getenv\(\s*[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\s*\))",
    re.IGNORECASE,
)
SEVERITY_ORDER = {"blocker": 0, "review": 1}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    scope: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class StagedChange:
    status: str
    path: str
    old_path: str | None
    old_mode: str
    new_mode: str
    new_oid: str

    def public(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "path": self.path,
            "old_path": self.old_path,
            "old_mode": self.old_mode,
            "new_mode": self.new_mode,
        }


class AuditError(RuntimeError):
    pass


def run_git(cwd: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise AuditError(f"cannot run Git in repository candidate: {error}") from error
    if result.returncode != 0:
        diagnostic = result.stderr.decode("utf-8", "replace").strip()
        raise AuditError(diagnostic or f"git {' '.join(args)} failed")
    return result.stdout


def nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in payload.split(b"\0") if item]


def staged_changes(payload: bytes) -> list[StagedChange]:
    fields = payload.split(b"\0")
    changes: list[StagedChange] = []
    index = 0
    while index < len(fields) and fields[index]:
        try:
            header = fields[index].decode("ascii")
        except UnicodeDecodeError as error:
            raise AuditError("invalid non-ASCII staged-change header") from error
        index += 1
        parts = header.removeprefix(":").split()
        if not header.startswith(":") or len(parts) != 5:
            raise AuditError("invalid staged-change record")
        old_mode, new_mode, _old_oid, new_oid, status = parts
        if index >= len(fields) or not fields[index]:
            raise AuditError("staged-change record is missing a path")
        first_path = fields[index].decode("utf-8", "surrogateescape")
        index += 1
        old_path: str | None = None
        path = first_path
        if status[:1] in {"R", "C"}:
            if index >= len(fields) or not fields[index]:
                raise AuditError("rename or copy record is missing its destination path")
            old_path = first_path
            path = fields[index].decode("utf-8", "surrogateescape")
            index += 1
        changes.append(StagedChange(status, path, old_path, old_mode, new_mode, new_oid))
    return changes


def is_safe_secret_value(value: str) -> bool:
    normalized = value.lower()
    return normalized in SAFE_LITERAL_VALUES or SAFE_ENV_REFERENCE.fullmatch(normalized) is not None


def assignment_value(raw: str) -> str:
    candidate = raw.strip()
    if not candidate:
        return ""
    if candidate[0] in {"\"", "'"}:
        quote = candidate[0]
        value: list[str] = []
        escaped = False
        for character in candidate[1:]:
            if escaped:
                value.append(character)
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                return "".join(value)
            else:
                value.append(character)
        return "".join(value)
    without_comment = re.split(r"\s+#", candidate, maxsplit=1)[0]
    return without_comment.rstrip(",;").strip()


def add_path_findings(path: str, scope: str, findings: list[Finding]) -> None:
    normalized = PurePosixPath(path).as_posix()
    if ARTIFACT_PATH.search(normalized):
        findings.append(
            Finding("review", "generated-artifact-path", path, scope, "Generated, cache, log, or temporary path requires justification.")
        )
    if PRODUCTION_DATA_PATH.search(normalized):
        findings.append(
            Finding("blocker", "possible-production-data", path, scope, "Possible production, customer, backup, or dump data must be verified before staging.")
        )
    if ENV_FILE.search(normalized) and not SAFE_ENV_FILE.search(normalized):
        findings.append(
            Finding("blocker", "environment-file", path, scope, "Environment file may contain local credentials or configuration.")
        )


def add_content_findings(
    path: str,
    scope: str,
    data: bytes,
    max_bytes: int,
    findings: list[Finding],
) -> None:
    if len(data) > max_bytes:
        findings.append(
            Finding("review", "large-file", path, scope, f"File is {len(data)} bytes; review provenance and repository policy.")
        )
        return
    if b"\0" in data:
        findings.append(
            Finding("review", "binary-file", path, scope, "Binary content cannot be semantically audited by this scanner.")
        )
        return

    text = data.decode("utf-8", "replace")
    for number, line in enumerate(text.splitlines(), 1):
        if PRIVATE_KEY_HEADER.search(line):
            findings.append(
                Finding("blocker", "private-key-header", path, scope, "Possible private key material; value redacted.", number)
            )
        if KNOWN_SECRET_PREFIX.search(line):
            findings.append(
                Finding("blocker", "known-secret-prefix", path, scope, "Possible credential with a known prefix; value redacted.", number)
            )
        for match in SECRET_ASSIGNMENT.finditer(line):
            value = assignment_value(match.group("value"))
            if len(value) >= 8 and not is_safe_secret_value(value):
                findings.append(
                    Finding("blocker", "secret-assignment", path, scope, "Possible credential assignment; value redacted.", number)
                )
                break
        if DEBUG_MARKER.search(line):
            findings.append(
                Finding("review", "debug-marker", path, scope, "Debug statement requires confirmation or removal.", number)
            )


def add_large_file(path: str, scope: str, size: int, findings: list[Finding]) -> None:
    findings.append(
        Finding("review", "large-file", path, scope, f"File is {size} bytes; review provenance and repository policy.")
    )


def staged_blob(root: Path, oid: str, max_bytes: int) -> tuple[bytes | None, int]:
    try:
        size = int(run_git(root, "cat-file", "-s", oid).decode("ascii").strip())
    except ValueError as error:
        raise AuditError("Git returned an invalid staged-object size") from error
    if size > max_bytes:
        return None, size
    return run_git(root, "cat-file", "blob", oid), size


def repository_path(root: Path, path: str) -> Path:
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise AuditError(f"untracked path escapes repository root: {path}")
    return root.joinpath(*relative.parts)


def inspect_untracked(
    root: Path,
    path: str,
    max_bytes: int,
    findings: list[Finding],
) -> None:
    candidate = repository_path(root, path)
    try:
        initial = candidate.lstat()
    except OSError as error:
        raise AuditError(f"cannot inspect untracked file {path}: {error}") from error

    if stat.S_ISLNK(initial.st_mode):
        findings.append(
            Finding("review", "symlink-file", path, "untracked", "Untracked symlink requires target and staging-intent review.")
        )
        try:
            data = os.fsencode(os.readlink(candidate))
        except OSError as error:
            raise AuditError(f"cannot read untracked symlink {path}: {error}") from error
        add_content_findings(path, "untracked", data, max_bytes, findings)
        return

    if not stat.S_ISREG(initial.st_mode):
        findings.append(
            Finding("review", "special-file", path, "untracked", "Non-regular untracked entry cannot be content-audited safely.")
        )
        return

    if initial.st_size > max_bytes:
        add_large_file(path, "untracked", initial.st_size, findings)
        return

    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino):
            raise AuditError(f"untracked file changed identity during inspection: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(max_bytes + 1)
    except OSError as error:
        raise AuditError(f"cannot read untracked file {path}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if len(data) > max_bytes:
        add_large_file(path, "untracked", max(opened.st_size, len(data)), findings)
        return
    add_content_findings(path, "untracked", data, max_bytes, findings)


def staged_change_is_scannable(change: StagedChange, findings: list[Finding]) -> bool:
    kind = change.status[:1]
    if kind == "D":
        findings.append(
            Finding("review", "staged-deletion", change.path, "staged", "Staged deletion requires scope and intent review.")
        )
        return False
    if kind == "U":
        findings.append(
            Finding("blocker", "unmerged-index", change.path, "staged", "Unmerged index entry blocks candidate verification.")
        )
        return False
    if kind == "T":
        findings.append(
            Finding("review", "staged-type-change", change.path, "staged", "Staged file-type change requires compatibility review.")
        )
    if change.new_mode == "160000":
        findings.append(
            Finding("review", "gitlink-entry", change.path, "staged", "Gitlink change requires submodule provenance and revision review.")
        )
        return False
    if change.new_mode not in {"100644", "100755", "120000"}:
        findings.append(
            Finding("review", "non-blob-staged-entry", change.path, "staged", "Staged entry type cannot be content-audited by this scanner.")
        )
        return False
    if change.new_mode == "120000":
        findings.append(
            Finding("review", "symlink-file", change.path, "staged", "Staged symlink requires target and intent review.")
        )
    return True


def deduplicate(findings: list[Finding]) -> list[Finding]:
    unique = {(
        item.severity,
        item.code,
        item.path,
        item.scope,
        item.message,
        item.line,
    ): item for item in findings}
    return sorted(
        unique.values(),
        key=lambda item: (SEVERITY_ORDER[item.severity], item.path, item.line or 0, item.code),
    )


def repository_root(repo: Path) -> Path:
    payload = run_git(repo, "rev-parse", "--show-toplevel")
    if payload.endswith(b"\r\n"):
        payload = payload[:-2]
    elif payload.endswith(b"\n"):
        payload = payload[:-1]
    if not payload:
        raise AuditError("Git returned an empty repository root")
    return Path(os.fsdecode(payload)).resolve()


def audit(repo: Path, max_bytes: int, max_files: int) -> dict[str, object]:
    root = repository_root(repo)
    staged = staged_changes(
        run_git(root, "diff", "--cached", "--raw", "-z", "--find-renames", "--find-copies", "--no-ext-diff")
    )
    untracked = nul_paths(run_git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    findings: list[Finding] = []

    if len(staged) + len(untracked) > max_files:
        findings.append(
            Finding("blocker", "scan-limit", ".", "repository", f"Candidate contains {len(staged) + len(untracked)} files, exceeding the scan limit of {max_files}.")
        )

    for change in staged[:max_files]:
        if change.status[:1] != "D":
            add_path_findings(change.path, "staged", findings)
        if not staged_change_is_scannable(change, findings):
            continue
        try:
            data, size = staged_blob(root, change.new_oid, max_bytes)
            if data is None:
                add_large_file(change.path, "staged", size, findings)
            else:
                add_content_findings(change.path, "staged", data, max_bytes, findings)
        except AuditError as error:
            findings.append(Finding("review", "unscanned-staged-file", change.path, "staged", str(error)))

    remaining = max(0, max_files - len(staged))
    for path in untracked[:remaining]:
        add_path_findings(path, "untracked", findings)
        try:
            inspect_untracked(root, path, max_bytes, findings)
        except AuditError as error:
            findings.append(Finding("review", "unscanned-untracked-file", path, "untracked", str(error)))

    ordered = deduplicate(findings)
    return {
        "repository": str(root),
        "staged_files": len(staged),
        "staged_changes": [change.public() for change in staged],
        "untracked_files": len(untracked),
        "findings": [asdict(item) for item in ordered],
        "summary": {
            "blockers": sum(item.severity == "blocker" for item in ordered),
            "review": sum(item.severity == "review" for item in ordered),
        },
        "limitations": [
            "Pattern matching can miss secrets and can produce false positives.",
            "The scanner does not determine architectural necessity or inspect prior Git history.",
            "Ignored files are excluded and require separate review when relevant.",
            "Untracked content is a mutable worktree snapshot; re-read the final index before commit.",
        ],
    }


def safe_text(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)[1:-1]


def print_text(result: dict[str, object]) -> None:
    summary = result["summary"]
    assert isinstance(summary, dict)
    print(f"repository: {safe_text(str(result['repository']))}")
    print(f"staged files: {result['staged_files']}")
    print(f"untracked files: {result['untracked_files']}")
    for change in result["staged_changes"]:
        assert isinstance(change, dict)
        rendered = safe_text(str(change["path"]))
        if change["old_path"] is not None:
            rendered = f"{safe_text(str(change['old_path']))} -> {rendered}"
        print(f"staged change: {change['status']} {rendered}")
    print(f"findings: {summary['blockers']} blocker(s), {summary['review']} review item(s)")
    for finding in result["findings"]:
        assert isinstance(finding, dict)
        location = safe_text(str(finding["path"]))
        if finding["line"] is not None:
            location = f"{location}:{finding['line']}"
        print(
            f"[{finding['severity']}] {finding['code']} {finding['scope']} "
            f"{location}: {safe_text(str(finding['message']))}"
        )
    print("limitations:")
    for limitation in result["limitations"]:
        print(f"- {limitation}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Git repository to audit")
    parser.add_argument("--max-bytes", type=int, default=2_000_000, help="maximum bytes scanned per file")
    parser.add_argument("--max-files", type=int, default=1000, help="maximum staged and untracked files scanned")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)
    if args.max_bytes < 1 or args.max_files < 1:
        parser.error("scan limits must be positive")
    try:
        result = audit(args.repo.resolve(), args.max_bytes, args.max_files)
    except AuditError as error:
        print(f"audit error: {safe_text(str(error))}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print_text(result)
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
