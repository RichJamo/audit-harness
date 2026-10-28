#!/usr/bin/env python3
"""The one place the ledger's cell encoding is pinned (REF-30).

The row generators and the ledger CLI share `tooling/table_cell.py`, so this file is
what stops the encoding drifting under any of them. The cases are the six the fix was
specified against -- a pipe, a newline, a tab, a run of spaces, text that already reads
`&#124;`, and plain text -- plus the two properties that matter to the guards: a value
survives a write-then-read round trip, and a value that never went through the escape
decodes to itself.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from table_cell import PIPE_ENTITY, escape_cell, unescape_cell  # noqa: E402

# (name, input, escaped, decoded-back). `decoded` is what a guard sees after the round
# trip: the input with whitespace collapsed, EXCEPT where the escape is lossy.
CASES = [
    ("a bare pipe",        "a | b",            "a &#124; b",       "a | b"),
    ("a newline",          "a\nb",             "a b",              "a b"),
    ("a tab",              "a\tb",             "a b",              "a b"),
    ("a run of spaces",    "a     b",          "a b",              "a b"),
    ("leading/trailing ws", "  a b \n",        "a b",              "a b"),
    ("an existing entity", "a &#124; b",       "a &#124; b",       "a | b"),
    ("plain text",         "reverts on zero",  "reverts on zero",  "reverts on zero"),
    ("pipe and newline",   "left | right\nand more",
                           "left &#124; right and more",
                           "left | right and more"),
    ("a hand-escaped pipe", r"a \| b",         r"a \&#124; b",     r"a \| b"),
    ("empty",              "",                 "",                 ""),
]


class EscapeEncoding(unittest.TestCase):
    def test_escape_and_round_trip(self):
        for name, raw, escaped, decoded in CASES:
            with self.subTest(name):
                self.assertEqual(escaped, escape_cell(raw), "escape")
                self.assertEqual(decoded, unescape_cell(escape_cell(raw)), "round trip")

    def test_escaped_text_can_never_resplit_a_row(self):
        """The whole point: no `|` and no newline survives, whatever went in."""
        for name, raw, _, _ in CASES:
            with self.subTest(name):
                out = escape_cell(raw)
                self.assertNotIn("|", out)
                self.assertEqual([out], out.splitlines() or [""])

    def test_unescape_leaves_text_that_was_never_escaped_alone(self):
        """Why every ledger already on disk reads exactly as before: text written
        before the escape holds no `&#124;`, and text without one decodes to itself."""
        for untouched in ("a | b", "ledger/dedup/R-6.md", r"a \| b", "", "x" * 500,
                          "REASON: the clamp holds · DEDUP: ledger/dedup/R-6.md"):
            with self.subTest(untouched):
                self.assertEqual(untouched, unescape_cell(untouched))

    def test_escape_accepts_non_strings(self):
        """The row generators passed `str(s)` through their own copies, so the shared
        helper must keep doing it or their rows break on an int."""
        self.assertEqual("7", escape_cell(7))
        self.assertEqual("None", escape_cell(None))

    def test_the_entity_constant_is_pinned(self):
        """Not a check that GitHub renders it -- a unit test cannot see GitHub. This
        pins the constant, so changing it fails here and in the byte-identical render
        test rather than quietly rewriting every board at the next `render`."""
        self.assertEqual("&#124;", PIPE_ENTITY)


if __name__ == "__main__":
    unittest.main()
