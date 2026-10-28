#!/usr/bin/env python3
"""Tests for tooling/prior_corpus.py: is every prior-audit report read into an extract and a key?

THE FAILURE THIS EXISTS FOR (REF-31, engagement 22). The client's internal audit had two rounds in one
folder; only round 1 was extracted and keyed, and a finding in round 2 duplicated one we filed.
That shape is pinned below, and so are the ways the check must stay quiet: engagements
without an index, files that are not reports, and extracts renamed by hand.
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("prior_corpus", REPO / "tooling" / "prior_corpus.py")
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


class Engagement(unittest.TestCase):
    def setUp(self):
        self.eng = Path(tempfile.mkdtemp(prefix="prior-corpus-"))
        self.tri = self.eng / "00-triage"
        for d in ("prior-audits", "prior-audits-text", "prior-audit-keys"):
            (self.tri / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def put(self, rel: str, text: str = "x") -> None:
        p = self.tri / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def index(self, *lines: str) -> None:
        (self.tri / pc.INDEX).write_text("# Prior-audit index\n\n" + "\n".join(lines) + "\n")

    def read(self, stem: str) -> None:
        self.put(f"prior-audits-text/{stem}.txt")
        self.put(f"prior-audit-keys/{stem}.json", "{}")


class Units(Engagement):
    def test_every_report_file_is_its_own_unit(self):
        self.put("prior-audits/hacken.pdf")
        self.put("prior-audits/internal-audit/audit/findings/F1.md")
        self.put("prior-audits/internal-audit/audit/v2/findings/F1.md")
        self.put("prior-audits/sherlock-fixes/H1.patch")          # not a report suffix
        self.assertEqual(pc.reports(self.eng), [
            "hacken.pdf", "internal-audit/audit/findings/F1.md", "internal-audit/audit/v2/findings/F1.md"])

    def test_the_index_does_not_live_in_prior_audits(self):
        # A file in prior-audits/ satisfies G1's "corpus on disk"; the index must not.
        self.index()
        self.assertEqual(pc.reports(self.eng), [])
        self.assertFalse(any((self.tri / "prior-audits").iterdir()))


class Coverage(Engagement):
    def test_silent_without_an_index(self):
        self.put("prior-audits/hacken.pdf")
        self.assertFalse(pc.enforced(self.eng))
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_a_report_with_a_same_named_extract_and_key_is_covered(self):
        self.index()
        self.put("prior-audits/hacken.pdf")
        self.assertEqual([r for r, _ in pc.uncovered(self.eng)], ["hacken.pdf"])
        self.read("hacken")
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_a_second_round_in_one_folder_is_named_unread(self):
        self.put("prior-audits/internal-audit/audit/F1.md")
        self.put("prior-audits/internal-audit/audit/findings/F2.md")
        self.put("prior-audits/internal-audit/audit/v2/F1.md")
        self.put("prior-audits/internal-audit/round2-per-issue/F1.md")   # seen on engagement 22
        self.read("internal-r1")
        self.index("- internal-audit | text: internal-r1.txt | key: internal-r1.json")
        self.assertEqual([r for r, _ in pc.uncovered(self.eng)],
                         ["internal-audit/audit/v2/F1.md", "internal-audit/round2-per-issue/F1.md"])
        self.read("internal-r2")
        self.index("- internal-audit | text: internal-r1.txt | key: internal-r1.json",
                   "- internal-audit/audit/v2 | text: internal-r2.txt | key: internal-r2.json",
                   "- internal-audit/round2-per-issue | text: internal-r2.txt | key: internal-r2.json")
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_a_folder_line_never_covers_its_pdfs(self):
        """A folder of separate review PDFs: one line must not read them all."""
        for n in range(1, 4):
            self.put(f"prior-audits/firm-reviews/review-{n}.pdf")
        self.read("firm")
        self.index("- firm-reviews | text: firm.txt | key: firm.json")
        self.assertEqual(len(pc.uncovered(self.eng)), 3)
        for n in range(1, 4):
            self.read(f"review-{n}")
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_an_index_line_must_name_plain_files_that_exist(self):
        self.put("prior-audits/Final Report 10001.pdf")
        self.put("prior-audits-text/collab.txt")
        self.put("other.json", "{}")
        for bad in ("text: collab.txt | key: ../other.json", "text: collab.txt | key: /etc/hosts",
                    "context: collab.txt | key: collab.json"):
            with self.subTest(line=bad):
                self.index(f"- Final Report 10001.pdf | {bad}")
                self.assertEqual(len(pc.uncovered(self.eng)), 1)
        self.put("prior-audit-keys/collab.json", "not json")
        self.index("- Final Report 10001.pdf | text: collab.txt | key: collab.json")
        self.assertIn("not valid JSON", pc.uncovered(self.eng)[0][1])
        self.put("prior-audit-keys/collab.json", "[]")
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_not_a_report_needs_a_reason(self):
        self.put("prior-audits/README.md")
        self.index("- README.md | not a report:")
        self.assertEqual([r for r, _ in pc.uncovered(self.eng)], ["README.md"])
        self.index("- README.md | not a report: the contest's own readme")
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_only_the_canonical_no_prior_art_marker_silences_it(self):
        self.index()
        self.put("prior-audits/hacken.pdf")
        self.put("prior-audits/NO-PRIOR-ART.md", "none")     # beside real reports: must not switch it off
        self.assertIn("hacken.pdf", [r for r, _ in pc.uncovered(self.eng)])
        (self.tri / "NO-PRIOR-ART.md").write_text("none")     # where G1 and the doctor read it
        self.assertEqual(pc.uncovered(self.eng), [])

    def test_the_scaffold_template_lines_are_not_real_entries(self):
        template = (REPO / "tooling" / "new-engagement.sh").read_text()
        body = template.split("<<'INDEX'\n", 1)[1].split("\nINDEX\n", 1)[0]
        (self.tri / pc.INDEX).write_text(body)
        self.put("prior-audits/hacken.pdf")
        self.assertEqual([r for r, _ in pc.uncovered(self.eng)], ["hacken.pdf"])

    def test_the_summary_groups_a_folder(self):
        missing = [(f"internal/v2/F{n}.md", "x") for n in range(5)] + [("hacken.pdf", "x")]
        self.assertEqual(pc.summary(missing), "internal/v2/ (5 files); hacken.pdf")


if __name__ == "__main__":
    unittest.main()
