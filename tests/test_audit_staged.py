#!/usr/bin/env python3
"""Risk-based tests for the read-only Git candidate audit helper."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "clean-before-commit" / "scripts" / "audit_staged.py"
MODULE_SPEC = importlib.util.spec_from_file_location("audit_staged_under_test", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
AUDIT_MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = AUDIT_MODULE
MODULE_SPEC.loader.exec_module(AUDIT_MODULE)


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


class AuditStagedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.assertEqual(run("git", "init", "-q", cwd=self.repo).returncode, 0)
        self.assertEqual(run("git", "config", "user.email", "test@example.invalid", cwd=self.repo).returncode, 0)
        self.assertEqual(run("git", "config", "user.name", "Test User", cwd=self.repo).returncode, 0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def audit(
        self,
        *extra: str,
        repo: Path | None = None,
        json_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = ["python3", str(SCRIPT), "--repo", str(repo or self.repo), *extra]
        if json_output:
            command.append("--json")
        return run(*command, cwd=self.repo)

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        return json.loads(result.stdout)

    def codes(self, result: subprocess.CompletedProcess[str]) -> set[str]:
        payload = self.payload(result)
        return {item["code"] for item in payload["findings"]}

    def stage(self, path: str, content: str) -> None:
        self.stage_bytes(path, content.encode("utf-8"))

    def stage_bytes(self, path: str, content: bytes) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self.assertEqual(run("git", "add", "--", path, cwd=self.repo).returncode, 0)

    def commit(self) -> None:
        self.assertEqual(run("git", "commit", "-qm", "baseline", cwd=self.repo).returncode, 0)

    # Git-state and compatibility contract.

    def test_clean_staged_addition_preserves_legacy_fields(self) -> None:
        self.stage("src/app.py", "print('hello')\n")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.payload(result)
        self.assertEqual(payload["summary"], {"blockers": 0, "review": 0})
        self.assertEqual(payload["staged_files"], 1)
        self.assertEqual(payload["untracked_files"], 0)
        self.assertEqual(payload["staged_changes"][0]["status"], "A")

    def test_staged_modification_is_inventoried(self) -> None:
        self.stage("app.py", "before\n")
        self.commit()
        self.stage("app.py", "after\n")
        payload = self.payload(self.audit())
        self.assertEqual(payload["staged_changes"][0]["status"], "M")

    def test_staged_deletion_requires_review(self) -> None:
        self.stage("obsolete.txt", "old\n")
        self.commit()
        (self.repo / "obsolete.txt").unlink()
        self.assertEqual(run("git", "add", "-u", "--", "obsolete.txt", cwd=self.repo).returncode, 0)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        payload = self.payload(result)
        self.assertEqual(payload["staged_files"], 1)
        self.assertEqual(payload["staged_changes"][0]["status"], "D")
        self.assertIn("staged-deletion", self.codes(result))

    def test_staged_rename_preserves_source_and_destination(self) -> None:
        self.stage("old-name.txt", "same content\n")
        self.commit()
        self.assertEqual(run("git", "mv", "--", "old-name.txt", "new-name.txt", cwd=self.repo).returncode, 0)
        payload = self.payload(self.audit())
        change = payload["staged_changes"][0]
        self.assertTrue(change["status"].startswith("R"))
        self.assertEqual(change["old_path"], "old-name.txt")
        self.assertEqual(change["path"], "new-name.txt")

    def test_git_reported_copy_preserves_source_and_destination(self) -> None:
        self.stage("source.txt", "original content\n")
        self.commit()
        self.stage("source.txt", "modified content\n")
        self.stage("copy.txt", "original content\n")
        changes = self.payload(self.audit())["staged_changes"]
        copy = next(change for change in changes if change["status"].startswith("C"))
        self.assertEqual(copy["old_path"], "source.txt")
        self.assertEqual(copy["path"], "copy.txt")

    def test_executable_mode_change_preserves_old_and_new_modes(self) -> None:
        self.stage("script.sh", "#!/bin/sh\nexit 0\n")
        self.commit()
        (self.repo / "script.sh").chmod(0o755)
        self.assertEqual(run("git", "add", "--", "script.sh", cwd=self.repo).returncode, 0)
        payload = self.payload(self.audit())
        if not payload["staged_changes"]:
            self.skipTest("Git does not track executable-bit changes on this filesystem")
        change = payload["staged_changes"][0]
        self.assertEqual(change["status"], "M")
        self.assertEqual(change["old_mode"], "100644")
        self.assertEqual(change["new_mode"], "100755")

    def test_gitlink_is_inventoried_and_requires_review(self) -> None:
        self.stage("seed.txt", "seed\n")
        self.commit()
        revision = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        result = run(
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            "160000",
            revision,
            "vendor/dependency",
            cwd=self.repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        audit_result = self.audit()
        self.assertEqual(audit_result.returncode, 1)
        change = self.payload(audit_result)["staged_changes"][0]
        self.assertEqual(change["new_mode"], "160000")
        self.assertIn("gitlink-entry", self.codes(audit_result))

    def test_unmerged_index_blocks_candidate_verification(self) -> None:
        self.stage("conflict.txt", "baseline\n")
        self.commit()
        original_branch = run("git", "branch", "--show-current", cwd=self.repo).stdout.strip()
        self.assertEqual(run("git", "checkout", "-qb", "conflicting-change", cwd=self.repo).returncode, 0)
        self.stage("conflict.txt", "side\n")
        self.commit()
        self.assertEqual(run("git", "checkout", "-q", original_branch, cwd=self.repo).returncode, 0)
        self.stage("conflict.txt", "main\n")
        self.commit()
        merge = run("git", "merge", "--no-edit", "conflicting-change", cwd=self.repo)
        self.assertNotEqual(merge.returncode, 0)
        audit_result = self.audit()
        self.assertEqual(audit_result.returncode, 1)
        self.assertIn("unmerged-index", self.codes(audit_result))

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_staged_type_change_and_symlink_are_reviewed(self) -> None:
        self.stage("entry", "regular\n")
        self.commit()
        (self.repo / "entry").unlink()
        os.symlink("target", self.repo / "entry")
        self.assertEqual(run("git", "add", "--", "entry", cwd=self.repo).returncode, 0)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("staged-type-change", self.codes(result))
        self.assertIn("symlink-file", self.codes(result))

    # Secret detection and redaction contract.

    def test_secret_is_redacted_and_blocks(self) -> None:
        sensitive = "-".join(("this", "is", "a", "realistic", "secret", "value"))
        assignment = "service_to" + f"ken={sensitive}\n"
        self.stage("config.txt", assignment)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(sensitive, result.stdout)
        self.assertIn("secret-assignment", self.codes(result))

    def test_quoted_secret_with_spaces_is_detected_as_complete_value(self) -> None:
        sensitive = " ".join(("short", "but", "material", "credential"))
        assignment = "password=" + '"' + sensitive + '"\n'
        self.stage("config.txt", assignment)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(sensitive, result.stdout)
        self.assertIn("secret-assignment", self.codes(result))
        text_result = self.audit(json_output=False)
        self.assertNotIn(sensitive, text_result.stdout)
        self.assertIn("secret-assignment", text_result.stdout)

    def test_single_quoted_secret_and_escaped_quote_are_detected(self) -> None:
        single_value = "single quoted credential"
        escaped_value = "escaped " + "\\" + '"' + "quoted credential"
        content = "pass" + "word='" + single_value + "'\n" + "to" + "ken=\"" + escaped_value + "\"\n"
        self.stage("config.txt", content)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(single_value, result.stdout)
        self.assertNotIn(escaped_value, result.stdout)
        matches = [item for item in self.payload(result)["findings"] if item["code"] == "secret-assignment"]
        self.assertEqual(len(matches), 2)

    def test_quoted_json_key_and_value_are_detected(self) -> None:
        sensitive = "joined" + "-credential-value"
        assignment = '{"' + "access_key" + '": "' + sensitive + '"}\n'
        self.stage("config.json", assignment)
        self.assertIn("secret-assignment", self.codes(self.audit()))

    def test_unterminated_quoted_secret_is_detected(self) -> None:
        sensitive = "unterminated" + "-credential-value"
        assignment = "password=" + '"' + sensitive + "\n"
        self.stage("config.txt", assignment)
        self.assertIn("secret-assignment", self.codes(self.audit()))

    def test_exact_placeholder_and_environment_reference_are_allowed(self) -> None:
        content = (
            "to" + "ken=placeholder # documented synthetic value\n"
            "pass" + "word=${SAFE_PASSWORD}\n"
            "se" + 'cret=os.environ["SECRET"]\n'
            "api_" + "key=os.environ.get('API_KEY')\n"
            "client_" + "se" + 'cret=os.getenv("CLIENT_SECRET")\n'
            "access_" + "key=getenv('ACCESS_KEY')\n"
            "service_" + "to" + "ken=process.env.SERVICE_TOKEN\n"
        )
        self.stage("config.txt", content)
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_environment_reference_with_suffix_does_not_suppress(self) -> None:
        value = 'os.getenv("TOKEN") + "literal"'
        self.stage("config.txt", "to" + "ken=" + value + "\n")
        self.assertIn("secret-assignment", self.codes(self.audit()))

    def test_placeholder_marker_as_substring_does_not_suppress(self) -> None:
        value = "example" + "-real-credential"
        self.stage("config.txt", "to" + "ken=" + value + "\n")
        self.assertIn("secret-assignment", self.codes(self.audit()))

    def test_known_prefix_is_redacted_and_blocks(self) -> None:
        sensitive = "ghp_" + "A" * 24
        self.stage("config.txt", "value=" + sensitive + "\n")
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(sensitive, result.stdout)
        self.assertIn("known-secret-prefix", self.codes(result))

    def test_private_key_header_blocks(self) -> None:
        header = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-key\n"
        self.stage("keys/id.pem", header)
        self.assertIn("private-key-header", self.codes(self.audit()))

    # File kinds, paths, and bounded-resource contract.

    def test_generated_artifact_requires_review(self) -> None:
        self.stage("dist/app.js", "const answer = 42;\n")
        self.assertIn("generated-artifact-path", self.codes(self.audit()))

    def test_possible_production_data_blocks(self) -> None:
        self.stage("exports/customer-backup.json", "{}\n")
        self.assertIn("possible-production-data", self.codes(self.audit()))

    def test_debug_marker_requires_review(self) -> None:
        marker = "console" + ".log('debug');\n"
        self.stage("app.js", marker)
        self.assertIn("debug-marker", self.codes(self.audit()))

    def test_binary_file_requires_review(self) -> None:
        self.stage_bytes("image.bin", b"prefix\0suffix")
        self.assertIn("binary-file", self.codes(self.audit()))

    def test_invalid_utf8_does_not_hide_ascii_secret_assignment(self) -> None:
        sensitive = "encoded" + "-credential-value"
        self.stage_bytes("config.txt", b"\xfftoken=" + sensitive.encode("ascii") + b"\n")
        result = self.audit()
        self.assertIn("secret-assignment", self.codes(result))
        self.assertNotIn(sensitive, result.stdout)

    def test_invalid_utf8_staged_filename_produces_valid_json_and_text(self) -> None:
        raw_name = b"invalid-\xff.txt"
        descriptor = os.open(os.path.join(os.fsencode(self.repo), raw_name), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, b"safe\n")
        finally:
            os.close(descriptor)
        self.assertEqual(run("git", "add", "--all", cwd=self.repo).returncode, 0)

        json_result = self.audit()
        self.assertEqual(json_result.returncode, 0, json_result.stdout + json_result.stderr)
        json_result.stdout.encode("utf-8", "strict")
        json_result.stdout.encode("ascii", "strict")
        encoded_path = os.fsencode(self.payload(json_result)["staged_changes"][0]["path"])
        self.assertEqual(encoded_path, raw_name)

        text_result = self.audit(json_output=False)
        self.assertEqual(text_result.returncode, 0, text_result.stdout + text_result.stderr)
        text_result.stdout.encode("ascii", "strict")
        self.assertIn("invalid-\\udcff.txt", text_result.stdout)

    def test_invalid_utf8_untracked_filename_produces_valid_json(self) -> None:
        raw_name = b"dist/untracked-\xfe.txt"
        (self.repo / "dist").mkdir()
        descriptor = os.open(os.path.join(os.fsencode(self.repo), raw_name), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, b"safe\n")
        finally:
            os.close(descriptor)
        result = self.audit()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        result.stdout.encode("utf-8", "strict")
        finding = next(item for item in self.payload(result)["findings"] if item["code"] == "generated-artifact-path")
        self.assertEqual(os.fsencode(finding["path"]), raw_name)

    def test_invalid_utf8_repository_root_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_root = os.path.join(os.fsencode(directory), b"repository-\xfd")
            os.mkdir(raw_root)
            root = Path(os.fsdecode(raw_root))
            self.assertEqual(run("git", "init", "-q", cwd=root).returncode, 0)
            result = self.audit(repo=root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result.stdout.encode("utf-8", "strict")
            self.assertEqual(os.fsencode(self.payload(result)["repository"]), raw_root)

    def test_large_staged_file_is_rejected_before_content_scan(self) -> None:
        self.stage("large.txt", "123456789")
        result = self.audit("--max-bytes", "8")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.codes(result), {"large-file"})

    def test_large_untracked_file_is_rejected_before_content_scan(self) -> None:
        (self.repo / "large.txt").write_text("123456789", encoding="utf-8")
        result = self.audit("--max-bytes", "8")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.codes(result), {"large-file"})

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_untracked_symlink_is_not_followed(self) -> None:
        os.symlink("../outside-target", self.repo / "link")
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink-file", self.codes(result))
        self.assertNotIn("unscanned-untracked-file", self.codes(result))

    def test_untracked_environment_file_blocks(self) -> None:
        (self.repo / ".env.local").write_text("SAFE_NAME=value\n", encoding="utf-8")
        result = self.audit()
        finding = next(item for item in self.payload(result)["findings"] if item["code"] == "environment-file")
        self.assertEqual(finding["scope"], "untracked")

    def test_example_environment_file_is_allowed(self) -> None:
        assignment = "SERVICE_TO" + "KEN=placeholder\n"
        (self.repo / ".env.example").write_text(assignment, encoding="utf-8")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # Limits, errors, deterministic output, and misuse resistance.

    def test_scan_limit_blocks_and_reports_total_inventory(self) -> None:
        self.stage("one.txt", "one\n")
        self.stage("two.txt", "two\n")
        result = self.audit("--max-files", "1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.payload(result)["staged_files"], 2)
        self.assertIn("scan-limit", self.codes(result))

    def test_invalid_repository_returns_error_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.audit(repo=Path(directory))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("audit error:", result.stderr)

    def test_invalid_limit_returns_error_exit(self) -> None:
        result = self.audit("--max-files", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("scan limits must be positive", result.stderr)

    def test_findings_have_deterministic_severity_and_path_order(self) -> None:
        (self.repo / ".env.z").write_text("safe=value\n", encoding="utf-8")
        (self.repo / ".env.a").write_text("safe=value\n", encoding="utf-8")
        findings = self.payload(self.audit())["findings"]
        self.assertEqual([item["path"] for item in findings], [".env.a", ".env.z"])

    def test_identical_findings_are_deduplicated(self) -> None:
        finding = AUDIT_MODULE.Finding("review", "example", "path", "staged", "message", 1)
        self.assertEqual(AUDIT_MODULE.deduplicate([finding, finding]), [finding])

    def test_text_output_escapes_control_characters_in_paths(self) -> None:
        path = "odd" + "\n" + "name.py"
        self.stage(path, "print('safe')\n")
        result = self.audit(json_output=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("odd\\nname.py", result.stdout)
        self.assertNotIn("odd\nname.py", result.stdout)

    def test_text_output_escapes_valid_unicode_paths_consistently(self) -> None:
        self.stage("数据.py", "print('safe')\n")
        result = self.audit(json_output=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result.stdout.encode("ascii", "strict")
        self.assertIn("\\u6570\\u636e.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
