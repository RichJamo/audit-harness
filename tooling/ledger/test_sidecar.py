"""Tests for tooling/ledger/sidecar.py and its CLI commands `dedup-skeleton` and `find-quote`.

Engagement 23: three sidecars were refused for their form alone. The skeleton must give
valid YAML that G1 still refuses until it is filled; the quote finder must return text G1 accepts.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "guards")]
import cli  # noqa: E402
import sidecar  # noqa: E402
import yaml  # noqa: E402
from ledger_guard import check_g1, check_g17  # noqa: E402

PASSAGE = ("The redemption path rounds the shares burned in favour of the redeemer, and the "
           "vault takes advantage of the rounding direction of a thinly funded queue.")
# The same passage as pdftotext writes it: wrapped, and one word broken across lines.
PDF_TEXT = ("Findings\n\nThe redemption path rounds the shares burned in favour of the\n"
            "redeemer, and the vault takes advan-\ntage of the rounding direction of a\n"
            "thinly funded queue.\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.eng = Path(tempfile.mkdtemp(prefix="sidecar-test-"))
        self.addCleanup(shutil.rmtree, self.eng, ignore_errors=True)
        (self.eng / "00-triage" / "prior-audits").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audits" / "r.pdf").write_text("stub")
        pr = self.eng / "00-triage" / "potential-risks"
        pr.mkdir(parents=True)
        (pr / "notes.txt").write_text(PDF_TEXT)
        txt = self.eng / "00-triage" / "prior-audits-text"
        txt.mkdir(parents=True)
        (txt / "report.txt").write_text("Report body.\n" + PDF_TEXT)
        (self.eng / "ledger" / "dedup").mkdir(parents=True)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--engagement", str(self.eng), *argv])
        return code, out.getvalue(), err.getvalue()


class TestSkeleton(Base):
    ENTRY = "`Vault.seizeCollateral` by any liquidator"

    def test_valid_yaml_that_lists_the_corpus_but_does_not_claim_it_was_searched(self):
        """A tool-written "searched every file" would satisfy G14 with no reading (review finding)."""
        text = sidecar.skeleton(self.eng, "R-1", self.ENTRY, "NEW")
        data = yaml.safe_load(text)
        self.assertEqual(1, len(data["searched"]))
        self.assertIn("<FILL IN>", data["searched"][0])
        for f in ("00-triage/potential-risks/notes.txt", "00-triage/prior-audits-text/report.txt"):
            self.assertIn(f'#   - "{f}"', text, "the corpus is listed, as comments, for the agent to move up")
        self.assertEqual("seizeCollateral", data["terms"][0], "the entry's bare names come first")
        self.assertGreaterEqual(len(data["terms"]), 3)

    def test_a_known_skeleton_leaves_result_unfilled(self):
        """G19 is silent only while result: holds a placeholder, so for KNOWN the skeleton leaves it
        unfilled: writing MATCH is the last edit, and that edit is judged in full (found in review)."""
        result = yaml.safe_load(sidecar.skeleton(self.eng, "R-1", "", "KNOWN"))["result"]
        self.assertTrue(result.startswith(sidecar.TODO), result)
        self.assertIn("MATCH", result)

    def test_result_comes_from_the_match_rule(self):
        for verdict, result in sidecar.match_rule.SIDECAR_RESULT.items():
            if verdict == "KNOWN":
                continue   # left unfilled: test_a_known_skeleton_leaves_result_unfilled
            with self.subTest(verdict=verdict):
                self.assertEqual(result, yaml.safe_load(sidecar.skeleton(self.eng, "R-1", "", verdict))["result"])
        with self.assertRaises(ValueError):
            sidecar.skeleton(self.eng, "R-1", "", "DUPLICATE")

    def test_a_match_skeleton_holds_the_claims_list_g19_asks_for(self):
        for verdict in (None, *sidecar.match_rule.MATCH_VERDICTS):
            with self.subTest(verdict=verdict):
                data = yaml.safe_load(sidecar.skeleton(self.eng, "R-1", "", verdict))
                if verdict in (None, "KNOWN"):
                    self.assertEqual([["caller", "quote"], ["impact", "quote"]],
                                     [list(c) for c in data["claims"]])
                else:
                    self.assertNotIn("claims", data)

    def test_g1_refuses_an_unfilled_skeleton_even_with_its_comments_deleted(self):
        """The refusal reads the fields, not the comment lines (review finding: a header comment
        once satisfied this test while the fields were pre-filled)."""
        entry = "`Vault.seizeCollateral` then `Pool.repayDebt()` via `_settleFee()`"
        for verdict in (None, *sidecar.match_rule.MATCH_VERDICTS):
            with self.subTest(verdict=verdict):
                text = sidecar.skeleton(self.eng, "R-1", entry, verdict)
                no_comments = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
                (self.eng / "ledger/dedup/R-1.md").write_text(no_comments)
                errs = check_g1("R-1", "ledger/dedup/R-1.md", "a row", self.eng, with_terms=True)
                self.assertTrue(any("<FILL IN>" in e for e in errs), errs)

    def test_a_comment_holding_the_placeholder_word_is_not_refused(self):
        (self.eng / "ledger/dedup/R-1.md").write_text(
            "# an old note: <FILL IN> was here\nsearched:\n  - 00-triage/potential-risks/notes.txt\n"
            "terms: [a, b, c]\nresult: NO-MATCH\n")
        self.assertFalse([e for e in check_g1("R-1", "ledger/dedup/R-1.md", "a row", self.eng)
                          if "<FILL IN>" in e])

    def test_g17_hits_are_listed_and_still_need_a_note(self):
        (self.eng / "target").mkdir()
        (self.eng / "target" / "README.md").write_text("Liquidators call seizeCollateral.\n")
        text = sidecar.skeleton(self.eng, "R-1", self.ENTRY, "NEW")
        self.assertEqual([{"name": "seizeCollateral", "file": "target/README.md", "note": ""}],
                         yaml.safe_load(text)["name_hits_read"])
        (self.eng / "ledger/dedup/R-1.md").write_text(text)
        self.assertTrue(check_g17("R-1", "ledger/dedup/R-1.md", self.ENTRY, self.eng),
                        "an empty note does not answer the hit")


class TestFindQuote(Base):
    def test_finds_across_wraps_and_a_hyphen_break_and_g1_accepts_it(self):
        found = sidecar.find_quote(self.eng, PASSAGE)
        self.assertEqual(["00-triage/potential-risks/notes.txt", "00-triage/prior-audits-text/report.txt"],
                         [f for f, _ in found])
        quote = found[0][1]
        self.assertIn("advan- tage", quote, "returned as the file has it, which is what G1 compares")
        (self.eng / "ledger/dedup/R-1.md").write_text(yaml.safe_dump({
            "searched": ["00-triage/potential-risks/notes.txt"], "terms": ["a", "b", "c"],
            "result": "PARTIAL", "quote": quote,
            "unmatched": "the entry covers the seized collateral, not the debt side of the same call"}))
        self.assertEqual([], [e for e in check_g1("R-1", "ledger/dedup/R-1.md", "a row", self.eng)
                              if "quote" in e])

    def test_the_typed_passage_alone_would_fail_g1(self):
        """Why the finder exists: the passage as a reader types it is not an exact substring."""
        (self.eng / "ledger/dedup/R-1.md").write_text(yaml.safe_dump({
            "searched": ["00-triage/potential-risks/notes.txt"], "terms": ["a", "b", "c"],
            "result": "PARTIAL", "quote": PASSAGE,
            "unmatched": "the entry covers the seized collateral, not the debt side of the same call"}))
        self.assertTrue([e for e in check_g1("R-1", "ledger/dedup/R-1.md", "a row", self.eng)
                         if "quote" in e])

    def test_a_compound_word_broken_at_its_own_hyphen(self):
        (self.eng / "00-triage/potential-risks/notes.txt").write_text("a high-\nvalue reserve\n")
        found = dict(sidecar.find_quote(self.eng, "a high-value reserve"))
        self.assertEqual("a high- value reserve", found["00-triage/potential-risks/notes.txt"])

    def test_absent_and_case_sensitive(self):
        self.assertEqual([], sidecar.find_quote(self.eng, "a passage that is not there at all"))
        self.assertEqual([], sidecar.find_quote(self.eng, PASSAGE.upper()))


class TestCommands(Base):
    def setUp(self):
        super().setUp()
        self.cli("add", "--id", "R-1", "--hypothesis", "rounding favours the liquidator",
                 "--entry", "`Vault.seizeCollateral`")

    def test_dedup_skeleton_writes_once(self):
        code, out, _ = self.cli("dedup-skeleton", "--id", "R-1", "--match-verdict", "NEW")
        self.assertEqual(0, code)
        self.assertTrue((self.eng / "ledger/dedup/R-1.md").is_file())
        code, _, err = self.cli("dedup-skeleton", "--id", "R-1")
        self.assertEqual(2, code, "an existing sidecar is never overwritten silently")
        self.assertIn("--force", err)
        self.assertEqual(0, self.cli("dedup-skeleton", "--id", "R-1", "--force")[0])

    def test_dedup_skeleton_refuses_an_unknown_row(self):
        self.assertEqual(2, self.cli("dedup-skeleton", "--id", "R-404")[0])
        self.assertFalse((self.eng / "ledger/dedup/R-404.md").exists())

    def test_dedup_skeleton_never_replaces_a_discharged_record(self):
        from store import append
        append(self.eng, {"id": "R-1", "event": "promote", "to": "TIER-1",
                          "dedup": "ledger/dedup/R-1.md", "satisfied": ["G1"], "by": "test"})
        code, _, err = self.cli("dedup-skeleton", "--id", "R-1", "--force")
        self.assertEqual(2, code)
        self.assertIn("already passed G1", err)

    def test_find_quote(self):
        code, out, _ = self.cli("find-quote", PASSAGE)
        self.assertEqual(0, code)
        self.assertIn("advan- tage", out)
        self.assertEqual(1, self.cli("find-quote", "nowhere in the corpus")[0])


if __name__ == "__main__":
    unittest.main()
