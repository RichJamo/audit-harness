#!/usr/bin/env python3
"""Tests for bootstrap.sh -- text-only, because RUN-CONTRACT forbids running it (it installs
tools system-wide). REF-19: Slither had no standalone compiler to fall back on when
crytic-compile's build-info parser broke on a current forge repo, and half the Phase-2
static baseline silently did not exist. This pins that the fix -- solc-select, pinned to a
version -- actually landed in the script text, plus `bash -n` syntax-checks it.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("bootstrap.sh")
TEXT = SCRIPT.read_text()


class TestSolcSelect(unittest.TestCase):
    def test_solc_select_is_installed(self):
        self.assertIn("solc-select", TEXT)
        self.assertIn("pip3 install --user solc-select", TEXT)

    def test_a_version_is_pinned_and_selected(self):
        self.assertIn('SOLC_VERSION="0.8.26"', TEXT)
        self.assertIn('install "$SOLC_VERSION"', TEXT)
        self.assertIn('use "$SOLC_VERSION"', TEXT)

    def test_it_installs_before_the_other_tools_notes_run(self):
        """Ordering, not just presence: the solc-select block must land before the shared
        PATH-hints heredoc, matching how Slither/Aderyn are set up first."""
        self.assertLess(TEXT.index("solc-select"), TEXT.index("PATH hints"))

    def test_the_fallback_path_is_not_hardcoded_to_one_python_version(self):
        """Code-review finding: a hardcoded ~/Library/Python/3.9/bin/solc-select fallback
        silently no-ops the whole install/select block on any machine whose `pip3 --user`
        targets a different Python minor version -- reproducing REF-19's own failure shape
        (a missing tool that looks like a clean bootstrap) for the fix meant to close it.
        The fallback must be derived, not a literal 3.9 path."""
        self.assertNotIn("Library/Python/3.9/bin/solc-select", TEXT)
        self.assertIn("python3 -m site --user-base", TEXT)

    def test_a_missing_solc_select_after_install_warns_instead_of_failing_silent(self):
        """The old code's failure mode was total silence: the guard was false, the block
        was skipped, and the script still printed 'solc: not on PATH' and exited 0."""
        self.assertIn("WARNING: solc-select not found", TEXT)


class TestSyntax(unittest.TestCase):
    def test_bash_n(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
