#!/usr/bin/env python3
"""The match-verdict constants the ledger CLI and the guards share (`tooling/match_rule.py`).

The guards read ATTACK_CLAUSES and CLAUSES (G16); `cli.py dedup-skeleton` reads MATCH_VERDICTS
and SIDECAR_RESULT. These tests pin the relations between them, so a verdict or clause added in
one place and not the other fails here rather than in a sidecar on disk.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match_rule  # noqa: E402


class MatchVerdicts(unittest.TestCase):
    def test_every_verdict_writes_exactly_one_sidecar_result(self):
        self.assertEqual(set(match_rule.MATCH_VERDICTS), set(match_rule.SIDECAR_RESULT))
        self.assertLessEqual(set(match_rule.SIDECAR_RESULT.values()),
                             {"MATCH", "PARTIAL", "NO-MATCH"})

    def test_only_known_is_written_as_a_match(self):
        """A MATCH sidecar is what parks a row; ATTACKS-FIX and PARTIAL must never write it."""
        self.assertEqual(["KNOWN"],
                         [v for v, r in match_rule.SIDECAR_RESULT.items() if r == "MATCH"])

    def test_attack_clauses_are_clauses(self):
        self.assertLess(set(match_rule.ATTACK_CLAUSES), set(match_rule.CLAUSES))
        self.assertNotIn("issue", match_rule.ATTACK_CLAUSES)
        self.assertNotIn("accepted", match_rule.ATTACK_CLAUSES)


if __name__ == "__main__":
    unittest.main()
