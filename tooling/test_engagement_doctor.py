#!/usr/bin/env python3
"""Tests for the engagement doctor, and specifically for REF-20.

The census that preceded this check found three ways it read the WRONG files as the target's
documentation -- our own `02-static/README.md`, a PoC attachment bundle carrying a manifest, and a
dependency's `forge-std/README.md`. Each of those is pinned below, because the failure mode of this
check is not a crash: it is a green report over files nobody in the engagement wrote.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "engagement_doctor", Path(__file__).resolve().parent / "engagement-doctor.py")
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

OK, WARN, GAP, BAD = doctor.OK, doctor.WARN, doctor.GAP, doctor.BAD


def write(p: Path, text: str = "x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.eng = Path(self.tmp.name) / "target-audit"
        (self.eng / "00-triage/prior-audits").mkdir(parents=True)
        (self.eng / "00-triage/potential-risks").mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def checkout(self, rel="repo") -> Path:
        root = self.eng / rel
        write(root / "foundry.toml", "[profile.default]\n")
        return root

    def docs_rows(self):
        return doctor.check_protocol_docs(self.eng)

    def levels(self):
        return [lvl for lvl, _, _ in self.docs_rows()]


class TestDiscovery(Base):
    def test_no_checkout_says_the_check_could_not_run(self):
        """An absent check must never read as a pass -- the register's standing rule."""
        rows = self.docs_rows()
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("could not run", rows[0][1])

    def test_docs_tree_and_root_readme_are_the_doc_set(self):
        root = self.checkout()
        write(root / "README.md")
        write(root / "docs/ARCHITECTURE.md")
        write(root / "docs/deep/FEES.md")
        texts, images = doctor.target_docs(self.eng)
        self.assertEqual({"README.md", "ARCHITECTURE.md", "FEES.md"}, {p.name for p in texts})
        self.assertEqual([], images)

    def test_our_own_working_dirs_are_not_the_targets_docs(self):
        """The first version counted 02-static/README.md -- a file WE wrote -- as target docs."""
        self.checkout()
        write(self.eng / "02-static/README.md")
        write(self.eng / "hunt/stage-a/README.md")
        write(self.eng / "00-triage/protocol-docs/notes.md")
        texts, _ = doctor.target_docs(self.eng)
        self.assertEqual([], texts)

    def test_a_poc_attachment_bundle_is_not_a_checkout(self):
        """engagement 1's 05-submission/*-attachments each carry a manifest and were counted."""
        write(self.eng / "05-submission/C1-attachments/foundry.toml")
        write(self.eng / "05-submission/C1-attachments/README.md")
        self.assertEqual([], doctor.checkout_roots(self.eng))

    def test_dependency_readmes_are_not_target_docs(self):
        root = self.checkout()
        write(root / "README.md")
        write(root / "lib/forge-std/README.md")
        write(root / "foundry-lib/forge-std/README.md")
        write(root / "node_modules/hardhat/README.md")
        texts, _ = doctor.target_docs(self.eng)
        self.assertEqual([root / "README.md"], texts)

    def test_outermost_checkout_wins(self):
        """A monorepo package is part of one target, not a second one."""
        root = self.checkout()
        write(root / "packages/core/package.json", "{}")
        write(root / "packages/core/README.md")
        self.assertEqual([root], doctor.checkout_roots(self.eng))

    def test_engagement_root_can_itself_be_the_checkout(self):
        """engagement 6 keeps foundry.toml at the engagement root."""
        write(self.eng / "foundry.toml", "[profile.default]\n")
        self.assertEqual([self.eng], doctor.checkout_roots(self.eng))


class TestVerdict(Base):
    def test_unextracted_docs_are_a_GAP(self):
        root = self.checkout()
        write(root / "docs/ARCHITECTURE.md")
        rows = self.docs_rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("never extracted", rows[0][1])

    def test_an_extract_clears_it(self):
        root = self.checkout()
        write(root / "docs/ARCHITECTURE.md")
        write(self.eng / "00-triage/protocol-docs/architecture.md", "what the system does")
        self.assertEqual([OK], self.levels())

    def test_an_empty_extract_directory_does_not_clear_it(self):
        """--fix creates the directory; creating it is not reading anything."""
        root = self.checkout()
        write(root / "docs/ARCHITECTURE.md")
        (self.eng / "00-triage/protocol-docs").mkdir(parents=True)
        self.assertEqual([GAP], self.levels())

    def test_the_marker_is_the_escape_hatch(self):
        root = self.checkout()
        write(root / "docs/ARCHITECTURE.md")
        write(self.eng / "00-triage/NO-PROTOCOL-DOCS.md", "target ships no usable docs")
        self.assertEqual([OK], self.levels())

    def test_no_docs_at_all_is_silent(self):
        self.checkout()
        self.assertEqual([], self.docs_rows())

    def test_image_only_docs_warn_rather_than_gap(self):
        """engagement 4 ships twelve PNG diagrams and no text. No script can extract those, so demanding
        an extract would be a gate nobody can satisfy -- but silence would hide them entirely."""
        root = self.checkout()
        write(root / "docs/architecture.png", "PNG")
        rows = self.docs_rows()
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("image/PDF", rows[0][1])

    def test_images_are_still_reported_once_the_text_is_extracted(self):
        root = self.checkout()
        write(root / "README.md")
        write(root / "docs/architecture.png", "PNG")
        write(self.eng / "00-triage/protocol-docs/primer.md", "what the system does")
        rows = self.docs_rows()
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("carry no text", rows[0][2])


class TestFilingCount(Base):
    """O-9. The four-fold overstatement came from summarising PROSE, not from a bad status cell,
    so the half that prevents it is making the count mechanical."""

    def ledger(self, text):
        (self.eng / "ledger").mkdir(parents=True, exist_ok=True)
        write(self.eng / "ledger.md", text)

    def test_filed_and_drafted_are_counted_separately(self):
        self.ledger("""| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a | CONFIRMED | FILED: https://github.com/o/r/issues/2 |
| H2 | b | CONFIRMED | DRAFTED: submissions/H2.md |
| H3 | c | UNTESTED | — |
""")
        rows = doctor.check_filings(self.eng)
        self.assertEqual(1, len(rows))
        self.assertIn("1 filed, 1 drafted", rows[0][1])

    def test_a_row_that_is_both_counts_as_FILED(self):
        """A draft that was then filed is a filing. Counting it twice would re-create the
        ambiguity this whole item exists to remove."""
        self.ledger("""| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a | CONFIRMED | DRAFTED: submissions/H1.md · FILED: https://x/1 |
""")
        self.assertIn("1 filed, 0 drafted", doctor.check_filings(self.eng)[0][1])

    def test_no_filings_is_silent(self):
        """Most of an engagement has zero filings; complaining would fire constantly."""
        self.ledger("""| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a | UNTESTED | — |
""")
        self.assertEqual([], doctor.check_filings(self.eng))

    def test_the_count_is_INFO_so_it_survives_a_messy_engagement(self):
        """An `ok` row is suppressed whenever anything else fires — which is exactly when
        someone would otherwise estimate the count from prose."""
        self.ledger("""| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a | CONFIRMED | FILED: https://x/1 |
""")
        self.assertEqual(doctor.INFO, doctor.check_filings(self.eng)[0][0])

    def test_INFO_never_fails_a_run(self):
        """It is a fact, not a complaint. Putting it in FAILING would make every filed
        engagement exit non-zero."""
        self.assertNotIn(doctor.INFO, doctor.FAILING)


class TestBundledAndStatuslessRows(Base):
    """Both checks were added after engagement 2's H21 — a five-hypothesis bundle, in a table with
    no status column — was found to have swallowed the contest's valid M-2 while sitting
    outside every guard in the repo."""

    LEDGER = """<!-- ledger-format: table-v1 -->
| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a single clean mechanism in one function | UNTESTED | src/A.sol |
| H2 | first thing; second thing; third unrelated thing | UNTESTED | src/B.sol |

| id | hypothesis | note | evidence |
|---|---|---|---|
| H3 | staleness; off-by-one; truncation; scaling; fee-rise | likely OOS | src/C.sol |
"""

    def ledger(self, text=None):
        (self.eng / "ledger").mkdir(parents=True, exist_ok=True)
        write(self.eng / "ledger.md", text if text is not None else self.LEDGER)

    def test_a_bundled_row_warns_and_never_blocks(self):
        self.ledger()
        rows = doctor.check_bundled_rows(self.eng)
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("H2", rows[0][2])

    def test_the_bundle_check_sees_rows_that_have_no_status(self):
        """The regression that motivated the check. Using parse_rows here would exempt H3 —
        which is the H21 shape, i.e. exactly the row the check exists for."""
        self.ledger()
        self.assertIn("H3", doctor.check_bundled_rows(self.eng)[0][2])

    def test_a_clean_ledger_is_silent(self):
        self.ledger("""| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | one mechanism, stated once | UNTESTED | src/A.sol |
""")
        self.assertEqual([], doctor.check_bundled_rows(self.eng))
        self.assertEqual([], doctor.check_statusless_rows(self.eng))

    def test_statusless_rows_are_named(self):
        self.ledger()
        rows = doctor.check_statusless_rows(self.eng)
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("H3", rows[0][2])
        self.assertNotIn("H1", rows[0][2])

    def test_the_escape_entity_does_not_flip_the_semicolon_count(self):
        """REF-30 regression. `cli.py render` writes a `|` as `&#124;`, which carries a
        semicolon, so two pipes in one hypothesis inject two semicolons and this check --
        `len(hyp) >= 25 and hyp.count(";") >= 2` -- would fire on a row that bundles
        nothing. The rows it would have fired on are exactly the ones REF-30 was filed for
        (absolute-value bars such as `|U|` and `|q - p|`), so the escape would have made
        the fix's own evidence look like a bundling problem. A predicate that counts
        characters must count them on the text, not on the transport encoding."""
        self.ledger("""<!-- ledger-format: table-v1 -->
| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | at most one live lock per user: `&#124;{ i : locks[i].amount > 0 }&#124; <= 1` | UNTESTED | src/A.sol |
""")
        self.assertEqual([], doctor.check_bundled_rows(self.eng),
                         "the escape entity's own semicolons must not read as bundling")

    def test_a_genuine_bundle_still_warns_when_the_row_carries_the_escape(self):
        """The other half: decoding must not make the check blind. This row bundles three
        mechanisms AND contains an escaped pipe."""
        self.ledger("""<!-- ledger-format: table-v1 -->
| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | `&#124;U&#124;` grows; the fee rounds down; the oracle goes stale | UNTESTED | src/A.sol |
""")
        self.assertIn("H1", doctor.check_bundled_rows(self.eng)[0][2])

    def test_neither_check_claims_a_guard_will_block(self):
        """WARN must not borrow BAD's authority: no guard refuses on either predicate."""
        self.ledger()
        for rows in (doctor.check_bundled_rows(self.eng), doctor.check_statusless_rows(self.eng)):
            for lvl, head, _ in rows:
                self.assertEqual(WARN, lvl)
                self.assertNotIn("BLOCK", head.upper())


class TestHonesty(Base):
    """A GAP must not borrow the guards' authority. Nothing refuses on REF-20."""

    def test_gap_headline_does_not_claim_a_guard_will_block(self):
        line = doctor.status_line([(GAP, "docs never extracted", "")])
        self.assertNotIn("BLOCK", line)
        self.assertIn("SETUP GAP", line)

    def test_bad_still_claims_it(self):
        self.assertIn("BLOCK", doctor.status_line([(BAD, "potential-risks/ has no .txt", "")]))

    def test_bad_outranks_gap(self):
        self.assertIn("BLOCK", doctor.status_line([(GAP, "a", ""), (BAD, "b", "")]))

    def test_a_gap_fails_the_run(self):
        root = self.checkout()
        write(root / "docs/ARCHITECTURE.md")
        self.assertIn(GAP, doctor.FAILING)
        self.assertEqual([GAP], self.levels())


class TestRecencyGate(Base):
    """In --all mode the docs check is limited to recently-touched engagements, so the dormant
    back-catalogue does not add a paragraph to every SessionStart."""

    def ledger(self, mtime: float | None = None) -> Path:
        led = write(self.eng / "ledger/ledger.md",
                    "<!-- ledger-format: table-v1 -->\n\n| id | hypothesis | status |\n"
                    "|---|---|---|\n| H1 | fee rounds down | `UNTESTED` |\n")
        if mtime is not None:
            os.utime(led, (mtime, mtime))
        return led

    def test_a_fresh_ledger_is_active(self):
        self.ledger()
        self.assertTrue(doctor.recently_active(self.eng))

    def test_a_stale_ledger_is_not(self):
        self.ledger(time.time() - doctor.ACTIVE_WINDOW_S - 60)
        self.assertFalse(doctor.recently_active(self.eng))

    def test_docs_false_skips_the_check_entirely(self):
        root = self.checkout()
        write(root / "docs/ARCHITECTURE.md")
        self.ledger()
        self.assertFalse([r for r in doctor.check(self.eng, docs=False) if r[0] == GAP])
        self.assertTrue([r for r in doctor.check(self.eng, docs=True) if r[0] == GAP])


class TestGeneratedRowsUnimported(Base):
    """Generated rows sitting in `01-hunt/*.rows.json` / `*.rows.md` that never reached the
    ledger. engagement 18's actual failure: `fix-adjacency.py --json` wrote 73 rows to
    `01-hunt/fix-adjacency.rows.json` and nobody imported them -- the file existed, so
    `check_generators_unrun` (which only asks "did it run") went quiet.

    fix-adjacency and opposite-tail currently emit rows with NO `id` field at all (see their
    docstrings / `--json` output), so there is nothing to compare against a real ledger id --
    every row in that shape counts as missing until it carries one. conduct.py's `.rows.json`
    sidecar and refutation-critic's `--json` output both DO carry a real `id` (an existing
    ledger row id in refutation-critic's case, since it only briefs REFUTED rows already on
    the board) -- those compare directly.
    """

    def hunt(self, name: str, content: str) -> Path:
        p = self.eng / "01-hunt" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def ledger(self, text: str) -> None:
        write(self.eng / "ledger" / "ledger.md", text)

    def rows(self):
        return doctor.check_generated_rows_unimported(self.eng)

    def test_no_rows_files_is_silent(self):
        self.ledger("| id | hypothesis | status |\n|---|---|---|\n| H1 | a | UNTESTED |\n")
        self.assertEqual([], self.rows())

    def test_warnings_in_a_rows_file_are_a_gap_and_silence_otherwise(self):
        """fix-adjacency writes its warnings into the rows file (an HTML comment in `.md`, a
        `warnings` list in `.json`), so they are seen without anyone watching its stderr."""
        self.hunt("fix-adjacency.rows.md", "| id | hypothesis |\n|---|---|\n| FA-1 | a |\n")
        self.hunt("opposite-tail.rows.json", '{"rows": []}')
        self.assertEqual([], doctor.check_generator_warnings(self.eng))
        self.hunt("fix-adjacency.rows.md", "<!-- fix-adjacency warning: report.txt: 2 finding(s) say they "
                                           "were fixed -->\n| id | hypothesis |\n|---|---|\n| FA-1 | a |\n")
        self.hunt("fix-adjacency.rows.json", '{"warnings": ["1 of 3 fix claim(s) found no heading"], "rows": []}')
        rows = doctor.check_generator_warnings(self.eng)
        self.assertEqual([GAP], [lvl for lvl, _, _ in rows])
        self.assertIn("2 generator warning(s)", rows[0][1])
        self.assertIn("fix-adjacency.rows.json", rows[0][1])
        self.assertIn("fix-adjacency.rows.md", rows[0][1])
        self.assertIn(rows[0], doctor.check(self.eng), "check() never runs check_generator_warnings")

    def test_fix_adjacency_shape_with_nothing_imported(self):
        """The real engagement 18 failure, minus the row count: fix-adjacency's own
        {claims, functions_indexed, rows} shape, no `id` field on any row."""
        import json
        self.hunt("fix-adjacency.rows.json", json.dumps({
            "claims": 2, "functions_indexed": 5,
            "rows": [{"kind": "fix-complete", "function": "addLiquidityWeighted"},
                     {"kind": "sibling-unfixed", "function": "addLiquidityExactShares"},
                     {"kind": "fix-complete", "function": "settle"}]}))
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("fix-adjacency.rows.json: 3 of 3 rows not in the ledger", rows[0][2])

    def created_events(self, source: str, ids: list[str]) -> None:
        """The event log `cli.py import` writes: one `created` event per row, carrying
        `imported_from`."""
        import json
        p = self.eng / "ledger" / "events.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            for i in ids:
                fh.write(json.dumps({"event": "created", "id": i, "status": "UNTESTED",
                                     "imported_from": source}) + "\n")

    def test_id_less_json_already_imported_through_a_sibling_table_is_silent(self):
        """engagement 18 AFTER the fix: the 73 id-less rows in fix-adjacency.rows.json
        were hand-converted to fix-adjacency.rows.md and imported as FA-1..FA-73. The JSON
        rows have no id to match, so matching by id reported "73 of 73 missing" forever.
        Id-less rows are counted against the rows imported from files with the same
        generator prefix instead."""
        import json
        self.ledger("| id | hypothesis | status |\n|---|---|---|\n"
                    "| FA-1 | a | UNTESTED |\n| FA-2 | b | UNTESTED |\n| FA-3 | c | UNTESTED |\n")
        self.created_events("01-hunt/fix-adjacency.rows.md", ["FA-1", "FA-2", "FA-3"])
        self.hunt("fix-adjacency.rows.json", json.dumps({
            "claims": 1, "functions_indexed": 5,
            "rows": [{"kind": "fix-complete"}, {"kind": "sibling-unfixed"},
                     {"kind": "fix-complete"}]}))
        self.assertEqual([], self.rows())

    def test_id_less_json_partly_imported_counts_only_the_shortfall(self):
        import json
        self.created_events("01-hunt/fix-adjacency.rows.md", ["FA-1", "FA-2"])
        self.hunt("fix-adjacency.rows.json", json.dumps({
            "rows": [{"kind": "a"}, {"kind": "b"}, {"kind": "c"}]}))
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("fix-adjacency.rows.json: 1 of 3 rows not in the ledger", rows[0][2])

    def test_rows_imported_from_another_generator_do_not_count(self):
        """The prefix is the attribution (bench/PREREG-generator-conversion.md); rows
        imported from opposite-tail must not silence fix-adjacency."""
        import json
        self.created_events("01-hunt/opposite-tail.rows.md", ["OT-1", "OT-2"])
        self.hunt("fix-adjacency.rows.json", json.dumps({"rows": [{"kind": "a"},
                                                                  {"kind": "b"}]}))
        self.assertIn("fix-adjacency.rows.json: 2 of 2 rows not in the ledger",
                      self.rows()[0][2])

    def test_opposite_tail_shape_with_nothing_imported(self):
        """opposite-tail's shape: a bare list, no `id` field either."""
        import json
        self.hunt("opposite-tail.rows.json", json.dumps(
            [{"file": "a.md", "line": 3, "subject": "x", "untested": "ceil"},
             {"file": "a.md", "line": 9, "subject": "y", "untested": "floor"}]))
        rows = self.rows()
        self.assertIn("opposite-tail.rows.json: 2 of 2 rows not in the ledger", rows[0][2])

    def test_a_shape_with_real_ids_is_partly_imported(self):
        """conduct.py / refutation-critic's shape: a bare list where each row DOES carry a
        real `id` -- so this compares directly, and only the ones actually missing count."""
        import json
        self.ledger("| id | hypothesis | status |\n|---|---|---|\n| R1 | a | UNTESTED |\n")
        self.hunt("refutation-critic.rows.json", json.dumps(
            [{"id": "R1", "context": "..."}, {"id": "R2", "context": "..."},
             {"id": "R3", "context": "..."}]))
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("refutation-critic.rows.json: 2 of 3 ids not in the ledger", rows[0][2])

    def test_everything_imported_is_silent(self):
        import json
        self.ledger("| id | hypothesis | status |\n|---|---|---|\n"
                    "| R1 | a | UNTESTED |\n| R2 | b | UNTESTED |\n")
        self.hunt("refutation-critic.rows.json", json.dumps(
            [{"id": "R1"}, {"id": "R2"}]))
        self.assertEqual([], self.rows())

    def test_a_rows_md_file_is_read_as_a_literal_ledger_table(self):
        """`--emit-ledger` (once it exists) writes a markdown table with real ids in the
        first cell -- exactly what `import` reads. This is the shape once it round-trips."""
        self.ledger("| id | hypothesis | status |\n|---|---|---|\n| FA-1 | a | UNTESTED |\n")
        self.hunt("fix-adjacency.rows.md",
                  "| id | hypothesis | entry point + access | invariant |\n|---|---|---|---|\n"
                  "| FA-1 | x | y | z |\n| FA-2 | x | y | z |\n")
        rows = self.rows()
        self.assertIn("fix-adjacency.rows.md: 1 of 2 ids not in the ledger", rows[0][2])

    def test_an_unreadable_shape_is_named_and_not_counted_as_zero(self):
        """REF-21: a tool (or here, a check) that reads nothing must never report as if it
        read everything and found no problem."""
        self.hunt("weird.rows.json", "42")
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("weird.rows.json", rows[0][2])
        self.assertIn("could not be read", rows[0][2])

    def test_invalid_json_is_named_and_not_counted_as_zero(self):
        self.hunt("broken.rows.json", "{not json")
        rows = self.rows()
        self.assertIn("broken.rows.json", rows[0][2])
        self.assertIn("could not be read", rows[0][2])

    def test_an_empty_rows_list_is_silent(self):
        import json
        self.hunt("fix-adjacency.rows.json", json.dumps({"claims": 0, "rows": []}))
        self.assertEqual([], self.rows())

    def test_a_prose_md_file_with_no_table_rows_is_silent(self):
        """refutation-critic's default (non-JSON) output is prose briefs, not a table --
        `### R1\\n- hypothesis...` -- which is not a ledger row shape at all."""
        self.hunt("refutation-critic.rows.md", "### R1\n- hypothesis / location: ...\n")
        self.assertEqual([], self.rows())


class TestPocEmpty(Base):
    """REF-22's first, simple form (decided 2026-09-24): rows on the board with nothing under
    `poc/` means every one of them was closed by argument, not by evidence -- the immovable
    rule the ledger CLI's PoC-suffix checks otherwise take for granted."""

    def ledger(self, text: str) -> None:
        write(self.eng / "ledger" / "ledger.md", text)

    ONE_ROW = "| id | hypothesis | status |\n|---|---|---|\n| H1 | a | UNTESTED |\n"

    def rows(self):
        return doctor.check_poc_empty(self.eng)

    def test_rows_and_an_empty_poc_dir_is_a_gap(self):
        self.ledger(self.ONE_ROW)
        (self.eng / "poc").mkdir()
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("1 row(s), 0 files under poc/", rows[0][1])

    def test_rows_and_no_poc_dir_at_all_is_also_a_gap(self):
        self.ledger(self.ONE_ROW)
        self.assertEqual([GAP], [r[0] for r in self.rows()])

    def test_an_empty_ledger_is_silent_even_with_no_poc(self):
        """The G1b direction already covers files in poc/ before any row is TIER-1; this
        must not fire on an engagement that has not started hunting."""
        self.assertEqual([], self.rows())

    def test_a_file_under_poc_clears_it(self):
        self.ledger(self.ONE_ROW)
        write(self.eng / "poc" / "H1.t.sol", "contract T {}")
        self.assertEqual([], self.rows())

    def test_a_nested_poc_file_clears_it(self):
        self.ledger(self.ONE_ROW)
        write(self.eng / "poc" / "forge" / "test" / "H1.t.sol", "contract T {}")
        self.assertEqual([], self.rows())

    def test_a_dotfile_does_not_count(self):
        self.ledger(self.ONE_ROW)
        write(self.eng / "poc" / ".gitkeep", "")
        self.assertEqual([GAP], [r[0] for r in self.rows()])

    def test_never_claims_a_guard_will_block(self):
        self.ledger(self.ONE_ROW)
        (self.eng / "poc").mkdir()
        self.assertNotIn(doctor.BAD, [r[0] for r in self.rows()])


class TestUntestedAtCloseout(Base):
    """REF-22's full form: once an engagement has declared close-out -- PHASES.md records
    Phase 5, done or skipped (Rich, 2026-10-21) -- every row still UNTESTED was closed by
    argument, not by one of the four legitimate exits. Before that this must stay silent:
    Phases 1-2 generate wide and every fresh row lands UNTESTED by design, and a
    submissions/ directory or a CONFIRMED row is routine mid-hunt."""

    def ledger(self, text: str) -> None:
        write(self.eng / "ledger" / "ledger.md", text)

    def rows(self):
        return doctor.check_untested_at_closeout(self.eng)

    UNTESTED_AND_REFUTED = ("| id | hypothesis | status |\n|---|---|---|\n"
                            "| H1 | a | UNTESTED |\n| H2 | b | REFUTED |\n")
    UNTESTED_AND_CONFIRMED = ("| id | hypothesis | status |\n|---|---|---|\n"
                              "| H1 | a | UNTESTED |\n| H2 | b | CONFIRMED |\n")
    ALL_CLOSED = ("| id | hypothesis | status |\n|---|---|---|\n"
                  "| H1 | a | REFUTED |\n| H2 | b | CONFIRMED |\n")

    # (name, submissions/ present, PHASES.md text or None, ledger text, expected to fire)
    CASES = [
        ("no PHASES.md, no submissions/ -- silent",
         False, None, UNTESTED_AND_REFUTED, False),
        ("submissions/ with no Phase 5 line -- silent", True, None, UNTESTED_AND_REFUTED, False),
        ("a CONFIRMED row with no Phase 5 line -- silent",
         False, "Phase 4: done\n", UNTESTED_AND_CONFIRMED, False),
        ("Phase 5 done with an UNTESTED row -- fires, names the id",
         False, "Phase 5: done\n", UNTESTED_AND_REFUTED, True),
        ("Phase 5 skipped with an UNTESTED row -- fires",
         False, "Phase 5: skipped -- no submission\n", UNTESTED_AND_REFUTED, True),
        ("Phase 5 done with zero UNTESTED -- silent", False, "Phase 5: done\n", ALL_CLOSED, False),
    ]

    def test_declared_close_out_and_untested_rows(self):
        for name, has_submissions, phases_text, ledger_text, expect_fires in self.CASES:
            with self.subTest(case=name):
                submissions = self.eng / "submissions"
                shutil.rmtree(submissions, ignore_errors=True)
                (self.eng / "PHASES.md").unlink(missing_ok=True)
                if has_submissions:
                    submissions.mkdir()
                if phases_text is not None:
                    write(self.eng / "PHASES.md", phases_text)
                self.ledger(ledger_text)
                rows = self.rows()
                if expect_fires:
                    self.assertEqual([doctor.GAP], [r[0] for r in rows])
                    self.assertIn("H1", rows[0][1])
                    self.assertNotIn("H2", rows[0][1])
                else:
                    self.assertEqual([], rows)

    def test_an_empty_ledger_is_silent_even_past_close_out(self):
        write(self.eng / "PHASES.md", "Phase 5: done\n")
        self.assertEqual([], self.rows())

    def test_the_same_id_in_two_ledger_files_is_not_silently_merged(self):
        """engagement 3 on disk: EX-3 sits UNTESTED in ledger.md and SCOPE-HELD in
        composition-pass.md -- a real id collision, not a hypothetical. Merging on the
        bare id and keeping whichever file is read first would silently drop a real
        UNTESTED row depending on file order; namespacing by ledger filename (the same
        convention check_bundled_rows already uses) keeps both readings visible."""
        write(self.eng / "ledger" / "a.md",
              "| id | hypothesis | status |\n|---|---|---|\n| H1 | a | UNTESTED |\n")
        write(self.eng / "ledger" / "b.md",
              "| id | hypothesis | status |\n|---|---|---|\n| H1 | a | SCOPE-HELD |\n")
        write(self.eng / "PHASES.md", "Phase 5: done\n")
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("a.md:H1", rows[0][1])
        self.assertNotIn("b.md:H1", rows[0][1])

    def test_fires_through_check_even_with_docs_false(self):
        """The reason this check sits OUTSIDE check()'s `if docs:` block: --all mode passes
        docs=False for an engagement that is not recently active (main()), and a closed
        engagement is normally the least recently active one. Exercise `check()` itself,
        not just the bare function, so a future refactor that moves the call back inside
        `if docs:` fails a test instead of passing silently."""
        self.ledger(self.UNTESTED_AND_CONFIRMED)
        write(self.eng / "PHASES.md", "Phase 5: done\n")
        results = doctor.check(self.eng, docs=False)
        gaps = [r for r in results if r[0] == doctor.GAP and "UNTESTED past close-out" in r[1]]
        self.assertEqual(1, len(gaps))
        self.assertIn("H1", gaps[0][1])


class TestScopeExclusionsFile(Base):
    """Richard, 2026-10-26: exclusion quoting (G20) reads 00-triage/scope-exclusions.md and is silent
    where it is missing, so the doctor says when an engagement that records Phase 0 has none. Engagements
    from before phases were recorded stay silent: they record no Phase 0."""

    def test_the_table(self):
        # (case, PHASES.md text or None, exclusion file present, fires)
        for case, phases, present, fires in [
            ("no PHASES.md: an older engagement, silent", None, False, False),
            ("Phase 0 recorded and no exclusion file: fires", "Phase 0: done\n", False, True),
            ("Phase 0 skipped and no exclusion file: fires", "Phase 0: skipped -- x\n", False, True),
            ("Phase 0 recorded with the file: silent", "Phase 0: done\n", True, False),
            ("only Phase -1 recorded: silent until Phase 0", "Phase -1: done\n", False, False),
        ]:
            with self.subTest(case=case):
                (self.eng / "PHASES.md").unlink(missing_ok=True)
                (self.eng / "00-triage" / "scope-exclusions.md").unlink(missing_ok=True)
                if phases is not None:
                    write(self.eng / "PHASES.md", phases)
                if present:
                    write(self.eng / "00-triage" / "scope-exclusions.md", "- front-running is out of scope\n")
                rows = doctor.check_scope_exclusions_file(self.eng)
                self.assertEqual([GAP] if fires else [], [r[0] for r in rows])
                if fires:
                    self.assertIn("scope-exclusions.md", rows[0][1])


class TestKnownUnreviewedAtCloseout(Base):
    """Richard, 2026-10-26: every row the matcher called KNOWN goes in front of him before Phase 5
    (`cli.py known-review`), and his answer is recorded per row. A KNOWN row is ranked last and in
    practice never tested, so once close-out is declared an unreviewed one is a finding nobody
    looked at again. Silent before Phase 5 is recorded, as the UNTESTED-at-close-out check is."""

    LEDGER = ("| id | hypothesis | status | evidence |\n|---|---|---|---|\n"
              "| H1 | a | UNTESTED | |\n| H2 | b | UNTESTED | |\n| H3 | c | REFUTED | |\n")

    def setUp(self):
        super().setUp()
        write(self.eng / "ledger" / "ledger.md", self.LEDGER)
        for rid, result in (("H1", "MATCH"), ("H2", "MATCH"), ("H3", "PARTIAL")):
            write(self.eng / "ledger" / "dedup" / f"{rid}.md", f"result: {result}\n")

    # (case, PHASES.md text or None, review file text or None, ids expected in the GAP, or None)
    CASES = [
        ("no PHASES.md -- silent", None, None, None),
        ("Phase 4 done only -- silent", "Phase 4: done\n", None, None),
        ("Phase 5 done, none reviewed -- fires on both KNOWN rows",
         "Phase 5: done\n", None, ["H1", "H2"]),
        ("Phase 5 skipped, one reviewed -- fires on the other",
         "Phase 5: skipped -- no submission\n", "H1: agree, KNOWN\n", ["H2"]),
        ("Phase 5 done, every KNOWN row reviewed -- silent",
         "Phase 5: done\n", "H1: agree\nH2: test it, PARTIAL on the keeper caller\n", None),
    ]

    def test_unreviewed_known_rows_after_close_out(self):
        for case, phases, review, expected in self.CASES:
            with self.subTest(case=case):
                (self.eng / "PHASES.md").unlink(missing_ok=True)
                (self.eng / "03-evidence" / "known-review.md").unlink(missing_ok=True)
                if phases is not None:
                    write(self.eng / "PHASES.md", phases)
                if review is not None:
                    write(self.eng / "03-evidence" / "known-review.md", review)
                rows = doctor.check_known_unreviewed(self.eng)
                if expected is None:
                    self.assertEqual([], rows)
                    continue
                self.assertEqual([GAP], [r[0] for r in rows])
                self.assertIn(f"{len(expected)} KNOWN row(s)", rows[0][1])
                for rid in ("H1", "H2", "H3"):
                    (self.assertIn if rid in expected else self.assertNotIn)(rid, rows[0][1])

    def test_fires_through_check_even_with_docs_false(self):
        """A closed engagement is normally the least recently active one, which --all checks
        with docs=False, so this sits outside check()'s `if docs:` block like REF-22's check."""
        write(self.eng / "PHASES.md", "Phase 5: done\n")
        gaps = [r for r in doctor.check(self.eng, docs=False) if "KNOWN row(s)" in r[1]]
        self.assertEqual([GAP], [r[0] for r in gaps])


class TestUntestedRowsWithTests(Base):
    """Engagement 22, 2026-10-20: two priority-1 rows had been tested a day earlier but still
    read UNTESTED, so a later screen re-queued them. The check flags an UNTESTED row only when
    a PoC test file names it DEFINITELY. The comment lines below keep the naming forms of that
    engagement's PoC comments, where the check flagged exactly the expected rows and none of the
    passing mentions; the ids and the descriptive words are replaced."""

    # Every id that appears in a fixture below, all UNTESTED.
    IDS = ["PAD-10", "HX-8", "RQ-14", "RQ-15", "S4H1-10", "S2H1-9", "S2H1-10", "S2H2-2",
           "S4H1-7", "HX-16", "HX-30", "S1H1-2", "PAD-1", "PAD-2", "S3H2-17", "S3H1-20",
           "S1H1-25", "OT-4", "OT-13", "S8H1-14", "A-2", "HX-27"]

    # (file name under poc/tests/, comment line) -- the naming forms of engagement 22's PoC comments.
    FILES = [
        ("H3-PAD-10.t.sol", "// Final-pass hunt H3, ledger row PAD-10 (rounding probe ...)"),
        ("B4-HX-8.t.sol", "// Second pass, part 2 (batch 4 rows). "
                           "Ledger row HX-8 (cluster HX-8)."),
        ("H1-queue.t.sol", "// Final-pass hunt H1 (queue ordering) for ledger rows "
                               "RQ-14 and RQ-15 (cluster S4H1-10)"),
        ("S2H2-1.t.sol", "// Representative for S2H1-9, S2H1-10, S2H2-2."),
        ("HOT-E1.t.sol", "// Final-pass evidence test HOT-E1 (backs existing ledger row "
                         "S4H1-7; not a new row)"),
        ("H3-HX-16.t.sol", "// HX-16 (PRIOR)."),
        ("Cost.t.sol", "// also gives the cost asked about by HX-30."),
        ("Fork.t.sol", "// PoC for ledger row S1H1-2 (cluster: PAD-1, PAD-2). FORK test"),
        ("Cluster.t.sol", "// (cluster S3H2-17); also bears on S3H1-20, S1H1-25, OT-4, OT-13."),
        ("Prior.t.sol", "// Prior-art: whether the owner role HAS a delay is "
                        "S8H1-14 (PRIOR)."),
        ("ESC-A-2.t.sol", "// escalation test"),
        ("MP1-HX-27.t.sol", "// no naming comment; the file name is the evidence"),
    ]
    EXPECTED = {"PAD-10", "HX-8", "RQ-14", "RQ-15", "S2H1-9", "S2H1-10", "S2H2-2", "S4H1-7",
                "HX-16", "S1H1-2", "HX-27"}
    PASSING_MENTIONS = {"S4H1-10", "HX-30", "PAD-1", "PAD-2", "S3H2-17", "S3H1-20",
                        "S1H1-25", "OT-4", "OT-13", "S8H1-14", "A-2"}

    def ledger(self, statuses: dict[str, str]) -> None:
        body = "".join(f"| {rid} | h | {st} |\n" for rid, st in statuses.items())
        write(self.eng / "ledger" / "ledger.md", "| id | hypothesis | status |\n|---|---|---|\n" + body)

    def poc(self, name: str, text: str) -> None:
        write(self.eng / "poc" / "tests" / name, text + "\ncontract T {}\n")

    def rows(self):
        return doctor.check_untested_rows_with_tests(self.eng)

    def flagged(self) -> set[str]:
        rows = self.rows()
        if not rows:
            return set()
        self.assertEqual([WARN], [r[0] for r in rows])
        listed = rows[0][1].split(": ", 1)[1]
        return {item.split(" (")[0] for item in listed.split(", ")}

    def test_regression_on_real_comment_forms(self):
        self.ledger({rid: "UNTESTED" for rid in self.IDS})
        for name, text in self.FILES:
            self.poc(name, text)
        flagged = self.flagged()
        self.assertEqual(self.EXPECTED, flagged)
        self.assertFalse(flagged & self.PASSING_MENTIONS)
        self.assertIn(f"{len(self.EXPECTED)} UNTESTED row(s) already named by a test file",
                      self.rows()[0][1])
        self.assertIn("RQ-14 (H1-queue.t.sol)", self.rows()[0][1])

    def test_rows_no_longer_untested_are_not_flagged(self):
        """The check reads the status cell: a row the test already promoted is not stale."""
        self.ledger({"PAD-10": "REFUTED", "HX-8": "CONFIRMED"})
        self.poc("H3-PAD-10.t.sol", self.FILES[0][1])
        self.poc("B4-HX-8.t.sol", self.FILES[1][1])
        self.assertEqual([], self.rows())

    def test_silent_with_no_poc_files(self):
        self.ledger({"PAD-10": "UNTESTED"})
        self.assertEqual([], self.rows())

    def test_silent_with_no_ledger(self):
        self.poc("H3-PAD-10.t.sol", self.FILES[0][1])
        self.assertEqual([], self.rows())

    def test_dependency_trees_are_not_read(self):
        """forge-std and friends live under poc/lib; nothing there names our rows."""
        self.ledger({"PAD-10": "UNTESTED"})
        write(self.eng / "poc" / "lib" / "forge-std" / "PAD-10.t.sol", "contract T {}")
        self.assertEqual([], self.rows())

    def test_test_poc_dir_and_other_languages_are_read(self):
        self.ledger({"PAD-10": "UNTESTED", "HX-8": "UNTESTED"})
        write(self.eng / "test" / "poc" / "pad_test.go", "// ledger row PAD-10\n")
        write(self.eng / "poc" / "src" / "lib.rs", "// Representative for HX-8.\n")
        self.assertEqual({"PAD-10", "HX-8"}, self.flagged())

    def test_advisory_through_check(self):
        """Wired into check() and never at a failing level: an advisory must not block a run."""
        self.ledger({"PAD-10": "UNTESTED"})
        self.poc("H3-PAD-10.t.sol", self.FILES[0][1])
        hits = [r for r in doctor.check(self.eng) if "already named by a test file" in r[1]]
        self.assertEqual([WARN], [r[0] for r in hits])


class TestQueuesComplete(Base):
    """Engagement 22: RQ-14 fell through every work queue. When 03-evidence/queues.md
    exists, every UNTESTED row must appear in it exactly once."""

    LEDGER = ("| id | hypothesis | status |\n|---|---|---|\n"
              "| H1 | a | UNTESTED |\n| H2 | b | UNTESTED |\n| H3 | c | REFUTED |\n")

    def setUp(self):
        super().setUp()
        write(self.eng / "ledger" / "ledger.md", self.LEDGER)

    def queues(self, *rows: str) -> None:
        body = "".join(f"| {rid} | queue-{i} |\n" for i, rid in enumerate(rows))
        write(self.eng / "03-evidence" / "queues.md",
              "Queues note.\n\n| row | queue |\n|---|---|\n" + body)

    def rows(self):
        return doctor.check_queues_complete(self.eng)

    def test_no_queues_file_is_silent(self):
        self.assertEqual([], self.rows())

    def test_clean_queues_is_silent(self):
        self.queues("H1", "H2")
        self.assertEqual([], self.rows())

    def test_a_missing_untested_row_is_a_gap(self):
        self.queues("H1")
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("1 UNTESTED row(s) missing: H2", rows[0][1])

    def test_a_row_listed_twice_is_a_gap(self):
        self.queues("H1", "H2", "H1")
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("listed more than once: H1", rows[0][1])
        self.assertNotIn("missing", rows[0][1])

    def test_a_row_no_longer_untested_is_a_warn(self):
        self.queues("H1", "H2", "H3")
        rows = self.rows()
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("no longer UNTESTED: H3", rows[0][1])

    def test_missing_and_stale_together_give_one_of_each(self):
        self.queues("H1", "H3")
        self.assertEqual([GAP, WARN], [r[0] for r in self.rows()])

    def test_queues_file_is_not_read_as_a_ledger(self):
        """Its status-less rows must not trip the statusless-row or pre-migration checks."""
        self.queues("H1", "H2")
        write(self.eng / "ledger" / "events.jsonl", '{"event":"created","id":"H1"}\n')
        self.assertEqual([], doctor.check_statusless_rows(self.eng))
        self.assertEqual([OK], [r[0] for r in doctor.check_ledger_is_cli_managed(self.eng)])

    def test_template_parses_as_an_empty_queues_table(self):
        template = Path(__file__).resolve().parent.parent / "templates" / "queues.template.md"
        text = template.read_text()
        self.assertIn("| row | queue |", text)
        self.assertEqual([], doctor.queue_entries(text))

    def test_wired_into_check(self):
        self.queues("H1")
        self.assertTrue(any(r[0] == GAP and "queues.md is incomplete" in r[1]
                            for r in doctor.check(self.eng)))


class TestPhasesRecorded(Base):
    """Which phases (`skill/SKILL.md`'s own headings: -1, 0, 1, 2, 3, 4, 5) ran, and which were
    skipped and why. engagement 18 skipped Phase 2 (static analysis) and Phase 3 (PoC) and
    nothing on disk said so."""

    ONE_ROW = "| id | hypothesis | status |\n|---|---|---|\n| H1 | a | UNTESTED |\n"
    COMPLETE = "\n".join([
        "Phase -1: done", "Phase 0: done", "Phase 1: done",
        "Phase 2: skipped — no static tooling for this target's VM",
        "Phase 3: done", "Phase 4: done", "Phase 5: done"]) + "\n"

    def ledger(self, text: str) -> None:
        write(self.eng / "ledger" / "ledger.md", text)

    def phases(self, text: str) -> None:
        write(self.eng / "PHASES.md", text)

    def rows(self):
        return doctor.check_phases_recorded(self.eng)

    def test_no_rows_is_silent_even_with_no_phases_file(self):
        self.assertEqual([], self.rows())

    def test_rows_and_no_phases_file_is_a_gap(self):
        self.ledger(self.ONE_ROW)
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("no PHASES.md", rows[0][1])

    def test_a_complete_file_is_silent(self):
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE)
        self.assertEqual([], self.rows())

    def test_a_missing_phase_is_named(self):
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE.replace("Phase 3: done\n", ""))
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("Phase 3", rows[0][2])

    def test_a_skip_with_no_reason_is_named(self):
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE.replace(
            "Phase 2: skipped — no static tooling for this target's VM", "Phase 2: skipped"))
        rows = self.rows()
        self.assertIn("Phase 2", rows[0][2])
        self.assertIn("no reason", rows[0][2])

    def test_done_needs_no_reason(self):
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE)
        self.assertEqual([], self.rows())

    def test_a_parenthetical_reason_counts(self):
        """Found in review: the first version only recognised a leading -/–/—/: separator,
        so "skipped (reason)" read as carrying NO reason -- indistinguishable from a skip
        that never explained itself."""
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE.replace(
            "Phase 2: skipped — no static tooling for this target's VM",
            "Phase 2: skipped (no static tooling for this target's VM)"))
        self.assertEqual([], self.rows())

    def test_a_comma_separated_reason_counts(self):
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE.replace(
            "Phase 2: skipped — no static tooling for this target's VM",
            "Phase 2: skipped, no static tooling for this target's VM"))
        self.assertEqual([], self.rows())

    def test_a_bare_trailing_period_is_still_no_reason(self):
        self.ledger(self.ONE_ROW)
        self.phases(self.COMPLETE.replace(
            "Phase 2: skipped — no static tooling for this target's VM", "Phase 2: skipped."))
        rows = self.rows()
        self.assertIn("Phase 2", rows[0][2])
        self.assertIn("no reason", rows[0][2])

    def test_never_claims_a_guard_will_block(self):
        self.ledger(self.ONE_ROW)
        self.assertNotIn(doctor.BAD, [r[0] for r in self.rows()])


class TestShadowCandidateRecorded(Base):
    """Phase -1's shadow-audit candidate check (skill/phases/phase-m1-triage.md): once Phase -1 is
    done and a prior-audit report is on disk, the triage file must record whether the report's
    audited commits are reachable."""

    SECTION = "## Shadow-audit candidate check\nNot a candidate: commits are private.\n"

    def phases(self, text: str = "Phase -1: done\n") -> None:
        write(self.eng / "PHASES.md", text)

    def report(self) -> None:
        write(self.eng / "00-triage/prior-audits/hacken.pdf", "%PDF")

    def triage(self, text: str) -> None:
        write(self.eng / "00-triage/target-triage.md", "# Phase -1 target triage\n" + text)

    def rows(self):
        return doctor.check_shadow_candidate_recorded(self.eng)

    def test_missing_section_is_a_gap(self):
        self.phases(); self.report(); self.triage("## EV verdict\nLow.\n")
        rows = self.rows()
        self.assertEqual([GAP], [r[0] for r in rows])
        self.assertIn("shadow-audit candidate check", rows[0][1])

    def test_missing_triage_file_is_a_gap(self):
        self.phases(); self.report()
        self.assertEqual([GAP], [r[0] for r in self.rows()])

    def test_recorded_section_is_silent(self):
        self.phases(); self.report(); self.triage(self.SECTION)
        self.assertEqual([], self.rows())

    def test_heading_match_ignores_case_and_level(self):
        self.phases(); self.report()
        self.triage("### shadow-audit candidate check (added later)\nNothing reachable.\n")
        self.assertEqual([], self.rows())

    def test_heading_text_in_prose_does_not_count(self):
        """Only a heading counts: a sentence mentioning the check is not the recorded result."""
        self.phases(); self.report()
        self.triage("We still owe the Shadow-audit candidate check.\n")
        self.assertEqual([GAP], [r[0] for r in self.rows()])

    def test_phase_m1_skipped_is_silent(self):
        """A shadow audit skips Phase -1; it is the shadow audit."""
        self.phases("Phase -1: skipped -- assigned shadow audit\n"); self.report()
        self.assertEqual([], self.rows())

    def test_phase_m1_not_recorded_is_silent(self):
        self.report()
        self.assertEqual([], self.rows())

    def test_no_report_is_silent(self):
        self.phases()
        write(self.eng / "00-triage/prior-audits/.DS_Store")
        self.assertEqual([], self.rows())

    def test_never_claims_a_guard_will_block(self):
        self.phases(); self.report()
        self.assertNotIn(BAD, [r[0] for r in self.rows()])

    def test_wired_into_check(self):
        self.phases(); self.report()
        self.assertTrue(any("shadow-audit candidate check" in r[1] for r in doctor.check(self.eng)))


class TestLedgerHeader(Base):
    """REF-23. `ledger/HEADER.md` carries the impact bar, materiality basis and RUN/CUTOFF
    provenance the Phase 4 scope gate and bench/ both read. Of the six real HEADER.md files on
    disk 2026-09-25, five spell the fields `IMPACT BAR  value`; a sixth writes
    `- **Impact bar:** value` for two of them. Both forms are tested below."""

    ONE_ROW = "| id | hypothesis | status |\n|---|---|---|\n| H1 | a | UNTESTED |\n"
    COMPLETE = (
        "```\n"
        "TARGET      org/repo @ deadbeef\n"
        "IMPACT BAR  theft / permanent lock\n"
        "MATERIALITY strict-as-deployed — ruled 2026-09-01\n"
        "RUN         model=claude-opus-5 · effort=high\n"
        "CUTOFF      not recorded\n"
        "```\n")

    def ledger(self, text: str) -> None:
        write(self.eng / "ledger" / "ledger.md", text)

    def header(self, text: str) -> None:
        write(self.eng / "ledger" / "HEADER.md", text)

    def rows(self):
        return doctor.check_ledger_header(self.eng)

    def test_no_rows_is_silent_even_with_no_header(self):
        self.assertEqual([], self.rows())

    def test_rows_and_no_header_is_bad(self):
        """BAD, not GAP: `cli.py promote --to TIER-1` genuinely refuses on this (a fresh
        row can always be created, since creation is ungated), so this must not claim "no
        guard refuses on this" the way a GAP does."""
        self.ledger(self.ONE_ROW)
        rows = self.rows()
        self.assertEqual([doctor.BAD], [r[0] for r in rows])
        self.assertIn("HEADER.md", rows[0][1])

    def test_a_complete_header_is_silent(self):
        self.ledger(self.ONE_ROW)
        self.header(self.COMPLETE)
        self.assertEqual([], self.rows())

    def test_not_recorded_is_a_legal_value(self):
        """CUTOFF above is literally `not recorded` and must NOT be flagged -- an honest
        gap is a legal answer; the field being absent entirely is not."""
        self.ledger(self.ONE_ROW)
        self.header(self.COMPLETE)
        self.assertEqual([], self.rows())

    def test_the_markdown_bullet_form_one_engagement_uses_counts_as_present(self):
        """One engagement's real HEADER.md writes two fields as markdown bullets,
        `- **Impact bar:** ...` -- mixed case, bold, colon inside the bold. Read as absent,
        this refused a TIER-1 promotion on a header that has every field."""
        self.ledger(self.ONE_ROW)
        self.header("- **Impact bar:** theft or permanent lock for High.\n"
                    "- **Materiality:** no % bar published.\n"
                    "```\nRUN         model=claude-opus-5 · effort=not recorded\n"
                    "CUTOFF      N/A (live contest)\n```\n")
        self.assertEqual([], self.rows())

    def test_a_prose_line_starting_with_run_does_not_count_as_the_run_field(self):
        """Case-insensitive matching is only for the `Label:` form. Without the colon, a
        sentence that happens to start with "Run" must not satisfy RUN."""
        self.ledger(self.ONE_ROW)
        self.header(self.COMPLETE.replace("RUN         model=claude-opus-5 · effort=high\n",
                                          "Run the generators before Phase 2.\n"))
        detail = self.rows()[0][1]
        self.assertIn("RUN", detail)

    def test_a_missing_field_is_named(self):
        self.ledger(self.ONE_ROW)
        self.header(self.COMPLETE.replace("CUTOFF      not recorded\n", ""))
        rows = self.rows()
        self.assertEqual([doctor.BAD], [r[0] for r in rows])
        self.assertIn("CUTOFF", rows[0][1])
        self.assertNotIn("IMPACT BAR", rows[0][1])

    def test_several_missing_fields_are_all_named(self):
        self.ledger(self.ONE_ROW)
        self.header("```\nTARGET org/repo\n```\n")
        detail = self.rows()[0][1]
        for f in ("IMPACT BAR", "MATERIALITY", "RUN", "CUTOFF"):
            self.assertIn(f, detail)

    def test_a_colon_separated_field_counts_as_present(self):
        """Found in review: the first version only accepted `LABEL  value` (two spaces, the
        shape every real header on disk uses today) and read `LABEL: value` as the field
        being entirely absent -- which would have wrongly refused a real TIER-1 promotion."""
        self.ledger(self.ONE_ROW)
        self.header(self.COMPLETE.replace("CUTOFF      not recorded\n", "CUTOFF: not recorded\n"))
        self.assertEqual([], self.rows())

    def test_it_claims_a_guard_will_block(self):
        self.ledger(self.ONE_ROW)
        self.assertIn(doctor.BAD, [r[0] for r in self.rows()])


class TestPriorCorpus(Base):
    """REF-31: BAD (a guard refuses TIER-1) while a prior-audit report has no extract and key,
    where the engagement keeps 00-triage/prior-audit-index.md; silent where it does not."""

    def test_silent_without_the_index(self):
        write(self.eng / "00-triage/prior-audits/hacken.pdf")
        self.assertEqual(doctor.check_prior_corpus(self.eng), [])

    def test_bad_and_named_with_the_index(self):
        write(self.eng / "00-triage/prior-audit-index.md", "# index\n")
        write(self.eng / "00-triage/prior-audits/internal/audit/F1.md")
        write(self.eng / "00-triage/prior-audits/internal/audit/v2/F1.md")
        rows = doctor.check_prior_corpus(self.eng)
        self.assertEqual([r[0] for r in rows], [BAD])
        self.assertIn("2 prior-audit report file(s)", rows[0][1])
        self.assertIn("internal/audit/v2", rows[0][2])
        self.assertIn("blocks every TIER-1", rows[0][2])


if __name__ == "__main__":
    unittest.main()


class TestLedgerIsCliManaged(unittest.TestCase):
    """The bootstrap half of G11: the hook cannot see an engagement that never made a log."""

    def setUp(self):
        self.eng = Path(tempfile.mkdtemp(prefix="doctor-g11-"))
        (self.eng / "00-triage").mkdir(parents=True)
        (self.eng / "ledger").mkdir(parents=True)
        (self.eng / "ledger" / "ledger.md").write_text(
            "<!-- ledger-format: table-v1 -->\n| id | h | e | i | status |\n|---|---|---|---|---|\n"
            "| H1 | x | y | z | UNTESTED |\n")

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def rows(self):
        return doctor.check_ledger_is_cli_managed(self.eng)

    def test_no_event_log_is_a_gap(self):
        lvl, msg, detail = self.rows()[0]
        self.assertEqual(doctor.GAP, lvl)
        self.assertIn("not in an event log", msg)
        self.assertIn("import", detail)      # a report must name the fix

    def test_a_migrated_ledger_is_ok(self):
        (self.eng / "ledger" / "events.jsonl").write_text('{"id":"H1","event":"created"}\n')
        (self.eng / "ledger" / "ledger.md").unlink()
        (self.eng / "ledger" / "ledger.md").write_text("generated")
        lvl, msg, _ = self.rows()[0]
        self.assertEqual(doctor.OK, lvl)

    def test_dual_state_warns(self):
        """engagement 9's actual condition: an event log alongside the old markdown."""
        (self.eng / "ledger" / "events.jsonl").write_text('{"id":"H1","event":"created"}\n')
        (self.eng / "ledger" / "hypothesis-ledger.md").write_text(
            "<!-- ledger-format: table-v1 -->\n| id | h | e | i | status |\n|---|---|---|---|---|\n"
            "| H1 | x | y | z | UNTESTED |\n")
        lvl, msg, detail = self.rows()[0]
        self.assertEqual(doctor.WARN, lvl)
        self.assertIn("pre-migration", msg)
        self.assertIn("two sources of truth", detail)

    def test_an_unscaffolded_engagement_says_nothing(self):
        """Silence where the check does not apply -- new-engagement.sh covers that case."""
        (self.eng / "ledger" / "ledger.md").unlink()
        self.assertEqual([], self.rows())


class TestFindingBodies(Base):
    """G14/REF-3 reported at session start rather than at the promotion it will refuse.

    engagement 16 is the case on disk: 7 sidecars, every one searched only the Notes and Trust Model
    extracts, while 12 full ChainSecurity/Cantina reports sat unread in prior-audits-text/.
    """

    BODY = "".join(f"F-2026-100{i} Medium\n\n" + ("prose about this finding. " * 45) + "\n\n"
                   for i in range(1, 4))
    SECTION = "00-triage/potential-risks/notes.txt"

    def setup_corpus(self, searched):
        write(self.eng / self.SECTION, "Notes\n  the trust model assumes an honest configurator\n")
        write(self.eng / "00-triage/prior-audits-text/report.txt", self.BODY)
        write(self.eng / "ledger/dedup/H7.md",
              "searched:\n" + "".join(f"  - {s}\n" for s in searched)
              + "terms:\n  - a\n  - b\n  - c\nresult: NO-MATCH\n")

    def test_sidecars_that_never_touched_a_body_warn(self):
        self.setup_corpus([self.SECTION])
        rows = doctor.check_finding_bodies(self.eng)
        self.assertEqual([WARN], [r[0] for r in rows])
        self.assertIn("prior-audits-text/report.txt", rows[0][2])

    def test_one_sidecar_touching_a_body_silences_it(self):
        """Engagement-level, deliberately: the per-row obligation is G14's, and repeating it
        here would make the doctor fire on rows a guard is already refusing."""
        self.setup_corpus([self.SECTION, "00-triage/prior-audits-text/report.txt"])
        self.assertEqual([], doctor.check_finding_bodies(self.eng))

    def test_no_bodies_on_disk_is_silent(self):
        write(self.eng / self.SECTION, "Notes\n  nothing here\n")
        write(self.eng / "ledger/dedup/H7.md",
              f"searched:\n  - {self.SECTION}\nterms:\n  - a\n  - b\n  - c\nresult: NO-MATCH\n")
        self.assertEqual([], doctor.check_finding_bodies(self.eng))

    def test_no_sidecars_yet_is_silent(self):
        """Before any dedup exists there is no omission to report, only an unstarted engagement."""
        write(self.eng / "00-triage/prior-audits-text/report.txt", self.BODY)
        self.assertEqual([], doctor.check_finding_bodies(self.eng))

    def test_it_never_claims_to_block(self):
        self.setup_corpus([self.SECTION])
        self.assertNotIn(WARN, doctor.FAILING)

    def test_flow_style_searched_agrees_with_G14(self):
        """The doctor must read the sidecar the way G14 does, not with a `- <line>` regex.

        `searched: [a, b]` is valid YAML that G14 accepts and a line regex cannot see, so the
        old parser claimed "G14 will refuse the next NO-MATCH promotion" on a row G14 passes.
        A doctor row that contradicts the guard it names is worse than no row at all.
        """
        body = "00-triage/prior-audits-text/report.txt"
        write(self.eng / self.SECTION, "Notes\n  the trust model assumes an honest configurator\n")
        write(self.eng / body, self.BODY)
        write(self.eng / "ledger/dedup/H7.md",
              f"searched: [{self.SECTION}, {body}]\n"
              "terms: [a, b, c]\nresult: NO-MATCH\n")
        self.assertEqual([], doctor.check_finding_bodies(self.eng))
        # The same sidecar through the guard, so the two are pinned to ONE answer.
        sys.path.insert(0, str(Path(doctor.__file__).resolve().parent / "guards"))
        from ledger_guard import check_g14
        self.assertEqual([], check_g14("H7", "ledger/dedup/H7.md", self.eng))

    def test_a_body_path_in_free_text_does_not_silence_it(self):
        """The other direction of the same defect: the regex matched any `- <text>` bullet
        with no idea which key it sat under, so a body path listed under `still_to_read:`
        counted as having been searched -- silencing the WARN while G14 fires."""
        body = "00-triage/prior-audits-text/report.txt"
        write(self.eng / self.SECTION, "Notes\n  nothing\n")
        write(self.eng / body, self.BODY)
        write(self.eng / "ledger/dedup/H7.md",
              f"searched:\n  - {self.SECTION}\n"
              "terms:\n  - a\n  - b\n  - c\nresult: NO-MATCH\n"
              # A list under ANY other key. The old regex matched `- <text>` lines with no
              # idea which key they belonged to, so this counted as "searched".
              f"still_to_read:\n  - {body}\n")
        rows = doctor.check_finding_bodies(self.eng)
        self.assertEqual([WARN], [r[0] for r in rows], rows)


class RuntimeBranchCheck(unittest.TestCase):
    """The runtime worktree must be on main, because the hooks resolve it by absolute path.

    Every ambiguous case abstains on purpose. A setup check that guesses is worse than one
    that says nothing -- it trains the reader to ignore it.
    """

    def _repo(self, branch: str) -> Path:
        d = Path(tempfile.mkdtemp())
        sh = lambda *a: subprocess.run(["git", "-C", str(d), *a], capture_output=True)
        sh("init", "-q", "-b", "main")
        sh("config", "user.email", "t@t"); sh("config", "user.name", "t")
        (d / "f").write_text("x")
        sh("add", "f"); sh("commit", "-qm", "init")
        if branch != "main":
            sh("checkout", "-q", "-b", branch)
        return d

    def test_silent_on_main(self):
        self.assertEqual(doctor.check_runtime_branch(self._repo("main")), [])

    def test_warns_on_a_feature_branch(self):
        out = doctor.check_runtime_branch(self._repo("engagement-4/zk-scope-trap"))
        self.assertTrue(out, "a feature branch in the runtime must be reported")
        self.assertIn("engagement-4/zk-scope-trap", out[0])
        # the warning has to say WHY, or a reader reasonably treats it as pedantry
        joined = " ".join(out)
        self.assertIn("EVERY engagement", joined)
        self.assertIn("checkout main", joined)

    def test_abstains_when_not_a_repo(self):
        self.assertEqual(doctor.check_runtime_branch(Path(tempfile.mkdtemp())), [])

    def test_abstains_when_missing(self):
        self.assertEqual(doctor.check_runtime_branch(Path("/nonexistent-runtime-xyz")), [])

    def test_abstains_on_detached_head(self):
        d = self._repo("main")
        sha = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(d), "checkout", "-q", sha], capture_output=True)
        self.assertEqual(doctor.check_runtime_branch(d), [],
                         "detached HEAD is ambiguous -- mid-rebase is not a misconfiguration")

    def test_RUNTIME_ROOT_honours_AUDIT_HARNESS_HOME(self):
        """RUNTIME_ROOT is computed once at import, exactly like the hooks' own shell
        expansion ${AUDIT_HARNESS_HOME:-$HOME/audit-toolkit} -- so this reloads the module
        per case instead of mutating the already-imported constant."""
        doctor_path = Path(__file__).resolve().parent / "engagement-doctor.py"

        def load(env):
            saved = os.environ.pop("AUDIT_HARNESS_HOME", None)
            try:
                os.environ.update(env)
                spec = importlib.util.spec_from_file_location("engagement_doctor_envcheck", doctor_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
            finally:
                os.environ.pop("AUDIT_HARNESS_HOME", None)
                if saved is not None:
                    os.environ["AUDIT_HARNESS_HOME"] = saved

        cases = [
            ({}, Path.home() / "audit-toolkit"),
            ({"AUDIT_HARNESS_HOME": "/tmp/some-other-checkout"}, Path("/tmp/some-other-checkout")),
        ]
        for env, want in cases:
            with self.subTest(env=env):
                self.assertEqual(load(env).RUNTIME_ROOT, want)


class TestGeneratorsUnrun(Base):
    """The check exists so `bench/PREREG-generator-conversion.md` can ever be evaluated: it
    scores each generator after two engagements, and a generator nobody runs is never scored
    and so never retired. Reports; never gates (row creation stays ungated by design)."""

    def ledger(self, text):
        write(self.eng / "ledger" / "ledger.md", text)

    LEDGER = """| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a | REFUTED | poc/H1.t.sol |
| H2 | b | UNTESTED | — |
"""

    def test_silent_when_there_is_nothing_to_read(self):
        # The engagement has no REFUTED rows, no hunter files and no prior-audit text, so
        # all three generators would have nothing to work on. A prompt here is pure noise.
        self.ledger("""| id | hypothesis | status | evidence |
|---|---|---|---|
| H1 | a | UNTESTED | — |
""")
        self.assertEqual([], doctor.check_generators_unrun(self.eng))

    def test_a_refuted_row_prompts_the_refutation_critic(self):
        self.ledger(self.LEDGER)
        rows = doctor.check_generators_unrun(self.eng)
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(GAP, rows[0][0])
        self.assertIn("1 REFUTED row(s)", rows[0][1])
        self.assertIn("refutation-critic.py", rows[0][2])

    def test_every_applicable_generator_lands_in_ONE_row(self):
        # Not one row each: three GAPs carrying the same explanation is how a check earns a
        # place on the ignore list (CLAUDE.md, "a gate that fires often gets disabled").
        self.ledger(self.LEDGER)
        write(self.eng / "01-hunt" / "core.md")
        write(self.eng / "00-triage/prior-audits-text" / "zellic.txt")
        rows = doctor.check_generators_unrun(self.eng)
        self.assertEqual(1, len(rows), rows)
        self.assertIn("3 row generator(s)", rows[0][1])
        for name in ("refutation-critic", "opposite-tail", "fix-adjacency"):
            self.assertIn(name, rows[0][2])

    def test_both_hunter_directory_names_are_recognised(self):
        """`hunters/` and `01-hunt/` are BOTH in use on disk -- engagement 8 uses the first,
        engagement 14's 48 files and engagement 17 the second. Reading opposite-tail.py's
        docstring alone would have made this check silent where it matters most."""
        for d in ("hunters", "01-hunt"):
            with self.subTest(d=d):
                self.setUp()
                self.ledger(self.LEDGER)
                write(self.eng / d / "core.md")
                detail = doctor.check_generators_unrun(self.eng)[0][2]
                self.assertIn("opposite-tail", detail)

    def test_an_output_file_counts_as_having_run(self):
        """And the output must not then be mistaken for a HUNTER file. The brief lands in
        01-hunt/ beside them, so without a filter running refutation-critic would silence its
        own prompt and raise opposite-tail's on an engagement holding no hunter files."""
        self.ledger(self.LEDGER)
        write(self.eng / "01-hunt" / "refutation-critic-briefs.md")
        self.assertEqual([], doctor.check_generators_unrun(self.eng))

    def test_an_attributed_ledger_row_counts_as_having_run(self):
        """The prereg attributes rows through `imported_from`, so the same filename prefix
        answers both questions -- did it run, and did its rows reach the ledger."""
        self.ledger(self.LEDGER)
        write(self.eng / "ledger" / "events.jsonl",
              json.dumps({"id": "R1", "status": "UNTESTED",
                          "imported_from": "/x/01-hunt/refutation-critic.rows.md"}) + "\n")
        self.assertEqual([], doctor.check_generators_unrun(self.eng))

    def test_an_unrelated_output_file_does_not_count(self):
        # Prefix match, not substring: a file merely MENTIONING the generator is not evidence
        # it ran, and treating it as such would silence the prompt on the engagement that
        # most needs it.
        self.ledger(self.LEDGER)
        write(self.eng / "01-hunt" / "notes-on-refutation-critic.md")
        self.assertEqual(1, len(doctor.check_generators_unrun(self.eng)))

    def test_files_under_code_are_ignored(self):
        """The target's own tree is not our output. A vendored file whose name happens to
        start with a generator's would otherwise silence the check."""
        self.ledger(self.LEDGER)
        write(self.eng / "code" / "src" / "fix-adjacency.sol")
        write(self.eng / "00-triage/prior-audits-text" / "zellic.txt")
        detail = doctor.check_generators_unrun(self.eng)[0][2]
        self.assertIn("fix-adjacency", detail)


class TestPriorArtAlias(Base):
    """The reports landed in prior-art/ on two engagements while G1 reads prior-audits/. The
    scaffold now links prior-art to prior-audits; the doctor must still catch a real misplaced
    corpus, and must not report the link itself as the mistake."""

    MISPLACED = "corpus is in 00-triage/prior-art/"

    def test_the_link_is_silent_and_a_real_misplaced_corpus_is_not(self):
        cases = [
            # (name, how prior-art is set up, expect the BAD row)
            ("real folder holding the reports", "dir", True),
            ("link to prior-audits, as the scaffold makes it", "link-to-pa", False),
            ("link to some other folder holding the reports", "link-elsewhere", True),
        ]
        for name, shape, expect in cases:
            with self.subTest(name):
                self.setUp()          # a fresh engagement per case; Base registers its cleanup
                alias = self.eng / "00-triage/prior-art"
                if shape == "dir":
                    write(alias / "report.pdf")
                elif shape == "link-to-pa":
                    alias.symlink_to("prior-audits")
                else:
                    write(self.eng / "elsewhere" / "report.pdf")
                    alias.symlink_to(self.eng / "elsewhere")
                messages = [m for _, m, _ in doctor.check(self.eng, docs=False)]
                self.assertEqual(expect, any(self.MISPLACED in m for m in messages), messages)
