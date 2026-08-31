#!/usr/bin/env python3
"""Tests for the read-only staged-content audit helper."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "clean-before-commit" / "scripts" / "audit_staged.py"


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

    def audit(self) -> subprocess.CompletedProcess[str]:
        return run("python3", str(SCRIPT), "--repo", str(self.repo), "--json", cwd=self.repo)

    def stage(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.assertEqual(run("git", "add", "--", path, cwd=self.repo).returncode, 0)

    def test_clean_staged_file_passes(self) -> None:
        self.stage("src/app.py", "print('hello')\n")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"], {"blockers": 0, "review": 0})

    def test_secret_is_redacted_and_blocks(self) -> None:
        sensitive = "-".join(("this", "is", "a", "realistic", "secret", "value"))
        assignment = "service_to" + f"ken={sensitive}\n"
        self.stage("config.txt", assignment)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(sensitive, result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn("secret-assignment", {item["code"] for item in payload["findings"]})

    def test_private_key_header_blocks(self) -> None:
        header = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-key\n"
        self.stage("keys/id.pem", header)
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("private-key-header", {item["code"] for item in payload["findings"]})

    def test_generated_artifact_requires_review(self) -> None:
        self.stage("dist/app.js", "const answer = 42;\n")
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("generated-artifact-path", {item["code"] for item in payload["findings"]})

    def test_untracked_environment_file_blocks(self) -> None:
        (self.repo / ".env.local").write_text("SAFE_NAME=value\n", encoding="utf-8")
        result = self.audit()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        finding = next(item for item in payload["findings"] if item["code"] == "environment-file")
        self.assertEqual(finding["scope"], "untracked")

    def test_example_environment_file_is_allowed(self) -> None:
        assignment = "SERVICE_TO" + "KEN=placeholder\n"
        (self.repo / ".env.example").write_text(assignment, encoding="utf-8")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
