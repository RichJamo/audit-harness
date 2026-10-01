"""Tests for the prior-art section extractor.

The bug these pin down: ChainSecurity and Cantina number every heading, so the
original exact-match list extracted 0 sections from all 12 reports on the engagement 16
engagement -- silently, leaving potential-risks/ empty and G1 blocking every
TIER-1 promotion with no hint as to why.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_prior_art import _heading_key, find_sections, main


class PriorArtExtractionTests(unittest.TestCase):
    def test_numbered_heading_reduces_to_the_bare_heading(self):
        assert _heading_key("8 Notes") == "Notes"
        assert _heading_key("2.1.1 Excluded from scope") == "Excluded from scope"
        assert _heading_key("2.4 Trust Model") == "Trust Model"

    def test_unnumbered_heading_is_untouched(self):
        """The pre-existing Hacken/Cantina-prose formats must keep working."""
        assert _heading_key("Potential Risks") == "Potential Risks"

    def test_table_of_contents_line_still_does_not_match(self):
        """The regression the exact match was protecting against.

        A ToC line keeps its trailing page number, so it must not reduce to the bare
        heading -- otherwise extraction starts at the contents page and yields nothing.
        """
        assert _heading_key("8 Notes                                    19") != "Notes"
        assert _heading_key("5 Open Findings . . . . . . . . . 15") != "Open Findings"

    def test_extracts_a_numbered_section_body_verbatim(self):
        text = "\n".join([
            "8 Notes                                        19",   # ToC line, must be skipped
            "1 Executive Summary",
            "blah",
            "8 Notes",                                              # the real section
            "8.1 Configuration Soft Deprecation",
            "The admin may leave a stale config in BeamState.",
            "3 Limitations and use of report",                      # a STOP heading
            "not part of the section",
        ])
        got = find_sections(text)
        assert "Notes" in got, got.keys()
        body = got["Notes"]
        assert "Configuration Soft Deprecation" in body
        assert "stale config" in body
        assert "not part of the section" not in body

    def test_stop_heading_terminates_even_when_numbered(self):
        text = "\n".join([
            "2.1.1 Excluded from scope",
            "The deployment scripts are not in scope.",
            "2.2 System Overview",                                  # numbered STOP heading
            "should not be captured",
        ])
        got = find_sections(text)
        assert "Excluded from scope" in got
        assert "should not be captured" not in got["Excluded from scope"]

    def test_a_csv_json_corpus_is_named_and_the_fallback_is_stated(self):
        """REF-24: one engagement's real corpus is CodeHawks CSV/JSON, and the old
        'no PDFs in ...' error said nothing about what to do instead. A 2026-09 census of
        every engagement's 00-triage/prior-audits/ found no CSV/JSON corpus actually
        living there (fewer than the two the entry's own disconfirmer asks for), so the
        fix is the error message naming the hand-written fallback G1 accepts -- not a
        parser for a shape nothing on disk currently uses."""
        with tempfile.TemporaryDirectory() as d:
            eng = Path(d) / "scratch-eng"
            pa = eng / "00-triage" / "prior-audits"
            pa.mkdir(parents=True)
            (pa / "issues.csv").write_text("id,title\n1,x\n")
            (pa / "raw.json").write_text("{}")

            raised = None
            try:
                main([str(eng)])
            except SystemExit as e:
                raised = e

        assert raised is not None, "must exit rather than silently produce nothing"
        msg = str(raised.code)
        assert "no PDFs" in msg
        assert ".csv" in msg and ".json" in msg, msg
        assert "potential-risks/<name>.txt" in msg, "must name the hand-written fallback"
        assert "NO-PRIOR-ART.md" in msg, "must name the other G1-accepted exit"


if __name__ == "__main__":
    unittest.main()
