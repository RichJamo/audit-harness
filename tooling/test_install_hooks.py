#!/usr/bin/env python3
"""Tests for install-hooks.sh — the recovery path for the one hook that is not in git.

PreToolUse and Stop live in skill/SKILL.md and are version-controlled. SessionStart cannot be
(a skill loads mid-session, so it would never fire), so it lives in ~/.claude/settings.json,
which no repo backs up. These tests pin the three things that make that survivable: the
reference file is installable, it MERGES rather than overwrites, and drift is detectable.
"""
import json, shutil, subprocess, tempfile, unittest
from pathlib import Path

TOOLKIT = Path(__file__).resolve().parents[1]
SCRIPT = TOOLKIT / "tooling" / "install-hooks.sh"
REF = TOOLKIT / "config" / "claude-settings-hooks.json"
EXISTING = {"permissions": {"allow": ["Bash(git add *)"]}, "theme": "dark"}


class TestInstallHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.live = self.tmp / "settings.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_it(self, *args):
        return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True,
                              env={"HOME": str(self.tmp), "PATH": "/usr/bin:/bin:/usr/local/bin",
                                   "CLAUDE_SETTINGS": str(self.live)})

    def test_reference_file_is_valid_json_with_hooks(self):
        ref = json.loads(REF.read_text())
        self.assertIn("SessionStart", ref["hooks"])

    def test_installs_into_a_file_that_does_not_exist(self):
        r = self.run_it()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SessionStart", json.loads(self.live.read_text())["hooks"])

    def test_MERGES_and_leaves_other_settings_alone(self):
        """The whole point: your permissions list must survive a repair."""
        self.live.write_text(json.dumps(EXISTING))
        self.run_it()
        d = json.loads(self.live.read_text())
        self.assertEqual(d["permissions"], EXISTING["permissions"])
        self.assertEqual(d["theme"], "dark")
        self.assertIn("SessionStart", d["hooks"])

    def test_is_idempotent(self):
        self.run_it()
        first = self.live.read_text()
        r = self.run_it()
        self.assertIn("nothing to do", r.stdout)
        self.assertEqual(self.live.read_text(), first)

    def test_check_reports_drift_without_writing(self):
        self.live.write_text(json.dumps(EXISTING))
        r = self.run_it("--check")
        self.assertEqual(r.returncode, 1, "missing hook must be reported as drift")
        self.assertIn("MISSING", r.stderr)
        self.assertEqual(json.loads(self.live.read_text()), EXISTING, "--check must not write")

    def test_check_is_quiet_when_installed(self):
        self.run_it()
        r = self.run_it("--check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("matches the reference", r.stdout)

    def test_backs_up_before_changing_anything(self):
        self.live.write_text(json.dumps(EXISTING))
        self.run_it()
        self.assertTrue(list(self.tmp.glob("settings.json.bak-*")), "no backup written")

    def test_refuses_to_overwrite_unparseable_settings(self):
        """Better to stop than to replace a file we cannot read."""
        self.live.write_text("{ this is not json")
        r = self.run_it()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual(self.live.read_text(), "{ this is not json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
