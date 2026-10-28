"""Tests for tooling/poc_mentions.py: which ledger rows a PoC test file names definitely.

Both engagement-doctor.py and privileged-screen.py read this module, so these cases fix the one
answer both tools give. The file-name cases came from the doctor; the backtick and split-row cases
are where the screen's former copy disagreed with it (found in review).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import poc_mentions as pm  # noqa: E402


class TestFileName(unittest.TestCase):
    def test_file_name_boundaries(self):
        cases = [("H3-HX-16.t.sol", "HX-16", True), ("HX-16.t.sol", "HX-16", True),
                 ("PoC-HX-16.t.sol", "HX-16", True), ("ESC-A-2.t.sol", "A-2", False),
                 ("HX-16.t.sol", "HX-1", False), ("XCDI-16.t.sol", "HX-16", False),
                 ("S4H1-3.t.sol", "H1-3", False), ("HX-16a.t.sol", "HX-16", False),
                 ("S8H1-20a.t.sol", "S8H1-20a", True)]
        for name, rid, expected in cases:
            with self.subTest(name=name, rid=rid):
                self.assertEqual(expected, pm.filename_names_row(name, rid))

    def test_underscore_spelling_is_not_read(self):
        """`OC_T1H1_2` and `ESC_A_2` have one shape; reading either would misread the other."""
        self.assertFalse(pm.filename_names_row("ESC_A_2.t.sol", "A-2"))
        self.assertFalse(pm.filename_names_row("FS_5.t.sol", "FS-5"))


class TestLine(unittest.TestCase):
    def test_definite_forms_only(self):
        self.assertEqual({"RQ-12"}, pm.rows_named_in_line("// ledger row RQ-12 (sibling of HX-14)"))
        self.assertEqual({"S2H1-9", "S2H1-10", "S2H2-2"},
                         pm.rows_named_in_line("// Representative for S2H1-9, S2H1-10, S2H2-2."))
        self.assertEqual(set(), pm.rows_named_in_line("// see HX-14 too"))

    def test_ids_without_a_hyphen_and_backticked_ids(self):
        """The ledger's ROW_ID allows `H1` and a split letter; the screen's copy read neither."""
        self.assertEqual({"H1"}, pm.rows_named_in_line("// ledger row `H1`"))
        self.assertEqual({"S8H1-20a"}, pm.rows_named_in_line("// ledger row S8H1-20a"))

    def test_list_stops_at_the_first_non_id(self):
        self.assertEqual({"RQ-14", "RQ-15"},
                         pm.rows_named_in_line("// ledger rows RQ-14 and RQ-15 (cluster S4H1-10)"))


class TestFilesNamingRows(unittest.TestCase):
    def setUp(self):
        self.eng = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.eng, ignore_errors=True)

    def write(self, rel: str, text: str = "contract T {}") -> None:
        path = self.eng / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_only_wanted_ids_and_never_an_empty_list(self):
        self.write("poc/H3-HX-16.t.sol")
        self.write("poc/Other.t.sol", "// ledger row RQ-12\n")
        hits = pm.files_naming_rows(self.eng, {"HX-16", "PAD-10"})
        self.assertEqual({"HX-16"}, set(hits))
        self.assertEqual([self.eng / "poc" / "H3-HX-16.t.sol"], hits["HX-16"])

    def test_dependency_trees_and_non_test_files_are_skipped(self):
        self.write("poc/lib/forge-std/PAD-10.t.sol")
        self.write("poc/PAD-10.Harness.sol")          # a harness, not a test file
        self.assertEqual({}, pm.files_naming_rows(self.eng, {"PAD-10"}))

    def test_default_dirs_include_test_poc(self):
        self.write("test/poc/pad_test.go", "// ledger row PAD-10\n")
        self.assertEqual({"PAD-10"}, set(pm.files_naming_rows(self.eng, {"PAD-10"})))
        self.assertEqual({}, pm.files_naming_rows(self.eng, {"PAD-10"}, dirs=("poc",)))


if __name__ == "__main__":
    unittest.main()
