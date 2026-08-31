#!/usr/bin/env python3
"""Read-only audit of staged and untracked Git content with redacted findings."""

from __future__ import annotations

import argparse
import json
import re
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
    r"(?i)\b(?:[a-z0-9]+[_-])*(api[_-]?key|secret|token|password|passwd|client[_-]?secret|"
    r"access[_-]?key|connection[_-]?string)\b\s*[:=]\s*[\"']?([^\s\"',;#]{8,})"
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
    r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|process\.env\.[A-Za-z_][A-Za-z0-9_]*|"
    r"os\.environ(?:\[|\.get\()|(?:os\.)?getenv\()",
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


class AuditError(RuntimeError):
    pass


def run_git(cwd: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = result.stderr.decode("utf-8", "replace").strip()
        raise AuditError(diagnostic or f"git {' '.join(args)} failed")
    return result.stdout


def nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in payload.split(b"\0") if item]


def is_safe_secret_value(value: str) -> bool:
    normalized = value.lower()
    return normalized in SAFE_LITERAL_VALUES or SAFE_ENV_REFERENCE.fullmatch(normalized) is not None


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
            value = match.group(2)
            if not is_safe_secret_value(value):
                findings.append(
                    Finding("blocker", "secret-assignment", path, scope, "Possible credential assignment; value redacted.", number)
                )
                break
        if DEBUG_MARKER.search(line):
            findings.append(
                Finding("review", "debug-marker", path, scope, "Debug statement requires confirmation or removal.", number)
            )


def staged_blob(root: Path, path: str) -> bytes:
    return run_git(root, "show", f":{path}")


def working_blob(root: Path, path: str) -> bytes:
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise AuditError(f"untracked path escapes repository root: {path}") from error
    try:
        return candidate.read_bytes()
    except OSError as error:
        raise AuditError(f"cannot read untracked file {path}: {error}") from error


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


def audit(repo: Path, max_bytes: int, max_files: int) -> dict[str, object]:
    root = Path(run_git(repo, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()).resolve()
    staged = nul_paths(run_git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"))
    untracked = nul_paths(run_git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    findings: list[Finding] = []

    if len(staged) + len(untracked) > max_files:
        findings.append(
            Finding("blocker", "scan-limit", ".", "repository", f"Candidate contains {len(staged) + len(untracked)} files, exceeding the scan limit of {max_files}.")
        )

    for path in staged[:max_files]:
        add_path_findings(path, "staged", findings)
        try:
            add_content_findings(path, "staged", staged_blob(root, path), max_bytes, findings)
        except AuditError as error:
            findings.append(Finding("review", "unscanned-staged-file", path, "staged", str(error)))

    remaining = max(0, max_files - len(staged))
    for path in untracked[:remaining]:
        add_path_findings(path, "untracked", findings)
        try:
            candidate = root / path
            if candidate.is_file():
                add_content_findings(path, "untracked", working_blob(root, path), max_bytes, findings)
        except AuditError as error:
            findings.append(Finding("review", "unscanned-untracked-file", path, "untracked", str(error)))

    ordered = deduplicate(findings)
    return {
        "repository": str(root),
        "staged_files": len(staged),
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
        ],
    }


def print_text(result: dict[str, object]) -> None:
    summary = result["summary"]
    assert isinstance(summary, dict)
    print(f"repository: {result['repository']}")
    print(f"staged files: {result['staged_files']}")
    print(f"untracked files: {result['untracked_files']}")
    print(f"findings: {summary['blockers']} blocker(s), {summary['review']} review item(s)")
    for finding in result["findings"]:
        assert isinstance(finding, dict)
        location = finding["path"]
        if finding["line"] is not None:
            location = f"{location}:{finding['line']}"
        print(f"[{finding['severity']}] {finding['code']} {finding['scope']} {location}: {finding['message']}")
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
        print(f"audit error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(result)
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
