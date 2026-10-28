"""Golden and POISONED fixtures for the ledger CLI.

Shape borrowed from GSE (`research/README.md` section 3), whose five-step gate is
MEASURED in production (61.4% F1) -- not from CAAF's Meta-Validation, which reads well
in the paper and has no implementation in OpenCAAF at all. Step 1 is the part that
applies here: a proposed change must be replayed against the case that motivated it.

The rule this file enforces: **a CLI that ACCEPTS a poisoned event fails the build.**
A guard suite that only ever feeds itself valid input is the "green suite that never ran
the code under test" the guards handover warns about.

Fixtures build in $TMPDIR. They must NOT be written under ~/engagements (a test run
there grandfathers real violations) and must NOT sit inside the toolkit repo (paths
there are exempt from the hook, so 11 cases once flipped to ALLOW having run nothing).
"""
from __future__ import annotations
import contextlib, importlib.util, io, re, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cli  # noqa: E402
from table_cell import unescape_cell  # noqa: E402
from store import append, replay, read_events, events_path, HEADER  # noqa: E402

REAL_QUOTE = ("The vault accounting path credits shares before the transfer settles, "
              "which allows a caller to observe an inflated balance mid-transaction.")

# REF-26: a kill states the argument it rests on, so every REFUTED promotion below carries
# one. What each of those cases is testing is the OTHER field -- the reason is scaffolding.
KILL_REASON = ("the checkpoint search clamps the index before the read, so the wrong-value "
               "claim cannot hold; test_R6 pins it")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.eng = Path(tempfile.mkdtemp(prefix="ledger-cli-test-"))
        (self.eng / "00-triage" / "prior-audits").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audits" / "hacken.pdf").write_text("stub")
        pr = self.eng / "00-triage" / "potential-risks"
        pr.mkdir(parents=True)
        (pr / "potential-risks.txt").write_text(
            "Potential Risks\n\n" + REAL_QUOTE + "\n\nOther observations follow.\n")
        (self.eng / "ledger" / "dedup").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def sidecar(self, rid: str, body: str) -> str:
        rel = f"ledger/dedup/{rid}.md"
        (self.eng / rel).write_text(body)
        return rel

    def header(self) -> None:
        """A complete ledger/HEADER.md (REF-23) -- not written by default, because a bare
        Fixture is also what TestVerifyWarnsOnMissingHeader below needs to exercise the
        engagement that never wrote one."""
        (self.eng / HEADER).write_text(
            "```\n"
            "IMPACT BAR  theft / permanent lock\n"
            "MATERIALITY strict-as-deployed -- ruled 2026-09-01\n"
            "RUN         model=not recorded\n"
            "CUTOFF      not recorded\n"
            "```\n")

    def run_cli(self, *argv) -> int:
        return cli.main(["--engagement", str(self.eng), *argv])

    def add(self, rid="R-6", hyp="Checkpoints.sol trace library returns a wrong value"):
        self.run_cli("add", "--id", rid, "--hypothesis", hyp)

    def poc(self, name="test/R6.t.sol") -> str:
        p = self.eng / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("contract T { function test_R6() public {} }")
        return name

    def tier1(self, rid="R-6") -> str:
        """Write the header and pay the dedup obligation, so `rid` sits at the mandatory
        waypoint. Returns the sidecar path."""
        self.header()
        rel = self.sidecar(rid, (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        assert self.run_cli("promote", "--id", rid, "--to", "TIER-1", "--dedup", rel) == 0
        return rel


class TestGolden(Fixture):
    def test_a_well_formed_promotion_is_accepted(self):
        self.header()
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_row_creation_is_ungated(self):
        """Phases 1-2 generate wide and suppress nothing. A gate here would throttle
        the sweep and damage recall -- CLAUDE.md constraint 1."""
        self.add()
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])


class TestRenderIsLossless(Fixture):
    """The render must be able to satisfy the guards that read it.

    Found on engagement 16 2026-09-04: `promote --to SCOPE-HELD --human "..."` was ACCEPTED and the
    human record was stored correctly in events.jsonl -- but render_text emitted only
    evidence/dedup, so the rendered row carried no `HUMAN:` key and the Stop-hook state guard
    then failed G2 on the CLI's own output. The only way out would have been to hand-edit the
    render, which G11 forbids. A lossy render turns a satisfied precondition into a blocked one.
    """

    def _scope_held(self, rid="R-9"):
        self.add(rid)
        self.run_cli("promote", "--id", rid, "--to", "SCOPE-HELD",
                     "--human", "RJ: admin-gated, program rule 4.2")
        self.run_cli("render")
        return (self.eng / "ledger" / "ledger.md").read_text()

    def test_scope_held_render_carries_the_human_record(self):
        self.assertIn("HUMAN: RJ: admin-gated, program rule 4.2", self._scope_held())

    def test_rendered_scope_held_row_passes_the_state_guard(self):
        """The end-to-end property: a promotion the CLI accepted must survive its own render."""
        self._scope_held()
        sys.path.insert(0, str(Path(cli.__file__).parent.parent / "guards"))
        import ledger_guard
        rendered = self.eng / "ledger" / "ledger.md"
        errs = ledger_guard.evaluate(rendered, rendered.read_text())
        self.assertEqual([], [e for e in errs if "G2" in e],
                         f"G2 fired on the CLI's own render: {errs}")

    def test_below_bar_render_carries_the_reason(self):
        self.add("R-10")
        self.run_cli("promote", "--id", "R-10", "--to", "BELOW-BAR",
                     "--reason", "Critical-only contest; griefing DoS, not theft of principal")
        self.run_cli("render")
        self.assertIn("REASON: Critical-only contest",
                      (self.eng / "ledger" / "ledger.md").read_text())


class TestBoardStaysCurrent(Fixture):
    """`add`, `import` and `promote` write to the log; the board (`ledger/ledger.md`) is
    what a human reads to make scope and submission decisions. On a live contest the board
    went three days missing four hypotheses and every status change since, because only
    `render` redraws it and nobody remembered to run it by hand. The board must never be
    able to disagree with the log -- these commands redraw it themselves."""

    def test_add_leaves_the_board_stale(self):
        self.add("R-6")
        self.run_cli("render")
        rendered = self.eng / "ledger" / "ledger.md"
        self.assertIn("R-6", rendered.read_text())
        self.add("R-7", hyp="second idea")
        self.assertIn("R-7", rendered.read_text(),
                       "board is stale: R-7 was written to the log but the board on disk "
                       "was not redrawn")

    def test_import_leaves_the_board_stale(self):
        self.run_cli("render")
        src = self.eng / "hunt.md"
        src.write_text("| H1 | first idea | mint() | supply cap | UNTESTED |\n")
        self.run_cli("import", str(src))
        rendered = self.eng / "ledger" / "ledger.md"
        self.assertIn("H1", rendered.read_text(),
                       "board is stale: H1 was imported into the log but the board on "
                       "disk was not redrawn")

    def test_promote_leaves_the_board_stale(self):
        self.header()
        self.add("R-6")
        self.run_cli("render")
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.run_cli("promote", "--id", "R-6", "--to", "TIER-1", "--dedup", rel)
        rendered = self.eng / "ledger" / "ledger.md"
        self.assertIn("TIER-1", rendered.read_text(),
                       "board is stale: R-6 was promoted to TIER-1 in the log but the "
                       "board on disk was not redrawn")


class TestRenderComposesTheHeader(Fixture):
    """REF-23: `render` emitted marker + banner + table and NOTHING else, so it silently
    deleted any header a human wrote into ledger.md -- the impact bar, materiality basis,
    scope exclusions, and RUN/CUTOFF provenance bench/ needs to compare one run to
    another. A render must COMPOSE a hand-owned header file, not replace it."""

    def test_a_hand_written_header_survives_render(self):
        header = self.eng / "ledger" / "HEADER.md"
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text(
            "# Hypothesis Ledger -- Example Protocol\n\n"
            "- **Impact bar:** theft / permanent lock\n"
            "- **RUN** model=opus effort=high CUTOFF=2026-09-01\n")
        self.add("R-6")
        self.run_cli("render")
        rendered = (self.eng / "ledger" / "ledger.md").read_text()
        self.assertIn("Impact bar", rendered)
        self.assertIn("RUN** model=opus", rendered)
        self.assertIn("R-6", rendered)   # composed, not replaced -- the table is still there

    def test_no_header_file_renders_exactly_as_before(self):
        """The common path (no header written yet) must stay silent -- a gate that fires
        on everything gets disabled."""
        self.add("R-6")
        self.run_cli("render")
        rendered = (self.eng / "ledger" / "ledger.md").read_text()
        self.assertIn("R-6", rendered)


class TestPoisoned(Fixture):
    """Each case MUST be refused. An accept here is a build failure."""

    def test_p1_no_dedup_sidecar_at_all(self):
        self.add()
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1"))
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])

    def test_p2_paraphrased_quote_is_not_verbatim(self):
        """The engagement 3 catch. A digest compressed the mechanism to one phrase and the
        engagement lost its only submission. Exact matching is the whole point."""
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\nresult: MATCH\n"
            "quote: \"The vault credits shares early which lets a caller see a bigger balance.\"\n"))
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))

    def test_p3_searched_file_does_not_exist(self):
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/nonexistent.txt\n"
            "terms: [checkpoint, trace, sentinel]\nresult: NO-MATCH\n"))
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))

    def test_p4_digest_only_never_satisfies_dedup(self):
        """`searched:` must include at least one file under potential-risks/."""
        (self.eng / "00-triage" / "prior-art-digest.md").write_text("a summary")
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/prior-art-digest.md\n"
            "terms: [checkpoint, trace, sentinel]\nresult: NO-MATCH\n"))
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))

    def test_p6_no_header_at_all_is_refused_even_with_a_good_dedup(self):
        """REF-23: sixteen rows went into engagement 18's ledger with no
        ledger/HEADER.md. A clean dedup must not be enough on its own."""
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])

    def test_p7_a_header_missing_a_required_field_is_refused(self):
        (self.eng / HEADER).write_text("```\nTARGET org/repo\nIMPACT BAR theft\n```\n")
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))

    def test_a_complete_header_in_bullet_form_clears_it(self):
        """One engagement's real spelling: `- **Impact bar:** ...`. Reading that as
        absent refused a promotion on a header that has all four fields."""
        (self.eng / HEADER).write_text(
            "- **Impact bar:** theft or permanent lock for High.\n"
            "- **Materiality:** no % bar published.\n"
            "```\nRUN         model=claude-opus-5\nCUTOFF      N/A (live contest)\n```\n")
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))

    def test_a_complete_header_clears_it(self):
        self.header()
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_p5_skipping_the_tier1_waypoint_is_refused(self):
        """UNTESTED -> CONFIRMED/REFUTED implies harness spend, and the dedup obligation
        is owed BEFORE that spend. In phase 1 this exited on a scope limit ("TIER-1 only");
        phase 2 makes it a real guard refusal, which is a different and stronger claim."""
        self.add()
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "CONFIRMED"))
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])

    def test_p5b_an_unknown_status_is_rejected(self):
        self.add()
        with self.assertRaises(SystemExit):
            self.run_cli("promote", "--id", "R-6", "--to", "PROBABLY-FINE")

    def test_p6_a_transition_cannot_invent_a_row(self):
        with self.assertRaises(SystemExit):
            self.run_cli("promote", "--id", "GHOST-1", "--to", "TIER-1")

    def test_p7_editing_the_render_does_not_change_state(self):
        """The whole point of the inversion: the markdown is a printout. Writing
        CONFIRMED into it must not move the row."""
        self.add()
        self.run_cli("render")
        p = self.eng / "ledger" / "ledger.md"
        p.chmod(0o644)
        p.write_text(p.read_text().replace("UNTESTED", "CONFIRMED"))
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])

    def test_p8_truncating_the_log_is_detected(self):
        """Append-only is a convention, not a property -- `>` still truncates. The hash
        chain does not PREVENT rewriting; verify() is what makes it visible."""
        self.add()
        self.add(rid="R-7", hyp="second row")
        ev = self.eng / "ledger" / "events.jsonl"
        lines = ev.read_text().splitlines()
        ev.write_text(lines[1] + "\n")           # drop the first event, keep the second
        self.assertEqual(1, self.run_cli("verify"))


class TestStateLocking(Fixture):
    def test_a_discharged_precondition_is_not_recharged(self):
        """G1 already worked this way by convention. Enforced from the log, it is CAAF's
        Pillar 3 -- which their own repo implements as a sentence in a prompt."""
        self.header()
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\n"
            f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n"))
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))
        (self.eng / rel).unlink()   # sidecar gone; the discharge stands
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1"))
        self.assertIn("G1", replay(self.eng)["R-6"]["satisfied"])

    def test_verify_is_clean_and_reports_no_oscillation(self):
        self.add()
        self.assertEqual(0, self.run_cli("verify"))


class TestBulkPath(Fixture):
    def test_import_reads_a_markdown_table(self):
        """Built on day one: if adding a row costs a CLI call each, the sweep gets
        routed around, which is how every gate dies."""
        src = self.eng / "hunt.md"
        src.write_text(
            "| id | hypothesis | entry | invariant | status |\n|---|---|---|---|---|\n"
            "| H1 | first idea | mint() | supply cap | UNTESTED |\n"
            "| H2 | second idea | burn() | conservation | UNTESTED |\n")
        self.run_cli("import", str(src))
        rows = replay(self.eng)
        self.assertEqual({"H1", "H2"}, set(rows))
        self.assertTrue(all(r["status"] == "UNTESTED" for r in rows.values()))

    def test_import_refuses_rows_it_cannot_parse_and_says_which(self):
        """REF-21. Five refutation-critic files on engagement 20 emitted ids like
        `RC-L03-1`; ROW_RE allows ONE hyphen, so all 24 rows were skipped and `import`
        printed "imported 0 rows" five times. The operator could not tell "found nothing"
        from "read nothing". Nothing is imported now until the ids are fixed.
        """
        src = self.eng / "refutation-critic-a.md"
        src.write_text(
            "| id | hypothesis | entry | invariant | status |\n|---|---|---|---|---|\n"
            "| RC-L03-1 | the clamp is off by one | mint() | supply cap | UNTESTED |\n"
            "| RC-L03-2 | the fee rounds down | burn() | conservation | UNTESTED |\n")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.assertEqual(2, self.run_cli("import", str(src)))
        err = buf.getvalue()
        self.assertNotIn("imported 0 rows", err)
        self.assertIn("2 table row(s) do not parse", err)
        self.assertIn("'RC-L03-1'", err)
        self.assertIn("line 3", err)
        self.assertIn("ONE optional hyphen", err)
        self.assertEqual({}, replay(self.eng), "a refused import must add nothing")

    def test_import_ignores_the_header_and_separator_rows(self):
        """The half that keeps the refusal usable: the two lines every markdown table
        carries are table-shaped and are not rows, so they must never be reported."""
        src = self.eng / "hunt.md"
        src.write_text(
            "| id | hypothesis (one line) | entry point | invariant | status |\n"
            "|----|-----------------------|-------------|-----------|--------|\n"
            "| H1 | first idea | mint() | supply cap | UNTESTED |\n")
        self.assertEqual(0, self.run_cli("import", str(src)))
        self.assertEqual({"H1"}, set(replay(self.eng)))

    def test_tables_are_judged_by_their_header(self):
        """Hunters write a coverage map or a call-site inventory beside their row table (3 of
        70 import sources on disk did). A table whose first column is not `id` is skipped
        and said to be skipped; a row table stays strict; real rows under the wrong header,
        or a file with no row table at all, refuse rather than vanish."""
        rows = ("| id | hypothesis | entry | invariant | status |\n|---|---|---|---|---|\n"
                "| H1 | first idea | mint() | supply cap | UNTESTED |\n")
        inventory = ("| # | file:line | call | target chosen by | guard | rows |\n"
                     "|---|---|---|---|---|---|\n"
                     "| 1 | `V.sol:38` | helper.check | manager role | nonReentrant | H1 |\n")
        misheaded = ("| row | hypothesis | entry | invariant | status |\n|---|---|---|---|---|\n"
                     "| H2 | second idea | burn() | conservation | UNTESTED |\n")
        cases = [
            # (name, file text, exit code, rows after, text expected on stdout or stderr)
            ("inventory beside the rows", inventory + "\n" + rows, 0, {"H1"},
             "skipped a table at line 1"),
            ("rows beside the inventory", rows + "\n" + inventory, 0, {"H1"},
             "skipped a table at line 5"),
            ("real rows under a wrong header", misheaded, 2, set(), "first column is 'row'"),
            ("no row table at all", inventory, 2, set(), "no ledger table found"),
        ]
        for name, text, code, want, message in cases:
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                src = self.eng / "hunt.md"
                src.write_text(text)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(code, self.run_cli("import", str(src)))
                self.assertEqual(want, set(replay(self.eng)))
                self.assertIn(message, out.getvalue() + err.getvalue())

    def test_import_is_idempotent(self):
        src = self.eng / "hunt.md"
        src.write_text("| H1 | idea | mint() | cap | UNTESTED |\n")
        self.run_cli("import", str(src))
        self.run_cli("import", str(src))
        self.assertEqual(1, len(read_events(self.eng)))


class TestRenderDrift(Fixture):
    def test_hand_editing_the_render_is_detected_by_verify(self):
        """Weakness 1 in the design note: the markdown still LOOKS editable. This is the
        detection layer -- it compares two strings rather than parsing, so format drift
        cannot out-run it."""
        self.add()
        self.run_cli("render")
        p = self.eng / "ledger" / "ledger.md"
        p.chmod(0o644)
        p.write_text(p.read_text().replace("UNTESTED", "CONFIRMED"))
        self.assertEqual(1, self.run_cli("verify"))

    def test_a_freshly_rendered_ledger_verifies_clean(self):
        self.add()
        self.run_cli("render")
        self.assertEqual(0, self.run_cli("verify"))

    def test_the_render_is_written_read_only(self):
        self.add()
        self.run_cli("render")
        self.assertFalse((self.eng / "ledger" / "ledger.md").stat().st_mode & 0o222)


class TestEngagementResolution(Fixture):
    def test_cwd_can_itself_be_the_engagement(self):
        """engagement_root() walks parents only -- correct for the hook, which is handed
        a file path, and wrong for a CLI run from inside the engagement directory."""
        import os
        prev = os.getcwd()
        try:
            os.chdir(self.eng)
            self.assertEqual(0, cli.main(["add", "--id", "R-1", "--hypothesis", "x"]))
        finally:
            os.chdir(prev)
        self.assertIn("R-1", replay(self.eng))


class Promoted(Fixture):
    """A row already at TIER-1, so downstream transitions can be tested in isolation."""
    def setUp(self):
        super().setUp()
        self.add()
        self.tier1()

    def answer_residue(self, text="none — the listed issue names the only cause, "
                                   "the statement has one leg, and it states the worst impact.",
                       clause="issue", attacks_entry="no") -> None:
        """Append an `unmatched:` answer to the fixture's sidecar. G12 checks that the
        three questions were ASKED; `none` is a legal conclusion. Also answers G16's two
        (REF-31) as a plain known issue: the row's claim is about the entry's issue clause and
        was not generated to attack it. Pass None to leave either unanswered."""
        p = self.eng / "ledger" / "dedup" / "R-6.md"
        extra = f"\nunmatched: |\n  {text}\n"
        if clause is not None:
            extra += f"clause: {clause}\n"
        if attacks_entry is not None:
            extra += f"attacks_entry: {attacks_entry}\n"
        p.write_text(p.read_text().rstrip() + extra)


class TestWaypoint(Fixture):
    def test_untested_to_refuted_skips_the_waypoint(self):
        """The rule that would have caught engagement 9: seven rows closed by reading, none
        of which ever passed through TIER-1."""
        self.add()
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "REFUTED"))
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])

    def test_untested_to_confirmed_skips_the_waypoint(self):
        self.add()
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "CONFIRMED"))

    def test_blocked_needs_no_waypoint(self):
        """BLOCKED means no PoC could be built, so no spend happened and nothing is owed.
        A residual blind spot, surfaced rather than hidden."""
        self.add()
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "BLOCKED",
                                         "--reason", "requires a mainnet fork we do not have"))


class TestArgumentKills(Promoted):
    def test_refuted_with_no_evidence_is_an_argument_kill(self):
        """G2. engagement 9 R-6 closed a 403-line checkpoint library with 'Refuted on every
        arm read' and four paragraphs. The guard existed; the ledger format hid the row."""
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "REFUTED"))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_refuted_naming_a_poc_that_does_not_exist(self):
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "REFUTED",
                                         "--evidence", "test/NoSuchFile.t.sol"))

    def test_refuted_with_a_resolving_poc_is_accepted(self):
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "REFUTED",
                                         "--evidence", self.poc() + "::test_R6",
                                         "--reason", KILL_REASON))

    def test_confirmed_with_no_poc_is_an_unbacked_claim(self):
        """G10. Same predicate as G2, opposite failure -- and on a platform where the PoC
        field is optional, this is the only thing enforcing no-PoC-no-submission."""
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "CONFIRMED"))

    def test_confirmed_with_a_resolving_poc_is_accepted(self):
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "CONFIRMED",
                                         "--evidence", self.poc() + "::test_R6"))


class TestForgeEvidenceNamesTheTestFunction(Promoted):
    """REF-1. Evidence named a test FILE, and one file holds many rows' tests, so a row could
    read as tested because a different row's test in that file ran the line. REF-25 measured it:
    on one engagement nine rows cite the same file and one of them is covered only by another
    row's test (bench/yb6-refutation-coverage-2026-09.md, PR #89). A Forge citation must now
    name the function too. Nothing else changes: non-Forge evidence is accepted as before.
    """
    def other(self, name: str, body: str = "x") -> str:
        p = self.eng / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return name

    def cases(self) -> list[tuple[str, str, int]]:
        """(what the citation is, the --evidence value, the expected exit code)."""
        forge = self.poc()                       # test/R6.t.sol, declaring test_R6()
        return [
            ("a bare .t.sol file", forge, 2),
            ("a .t.sol naming a function that exists", f"{forge}::test_R6", 0),
            ("a .t.sol naming a function that does not exist", f"{forge}::test_ghost", 2),
            ("a Rust PoC, no function named", self.other("poc/h7.rs"), 0),
            ("a static-analysis log, no function named", self.other("02-static/slither.txt"), 0),
        ]

    def test_the_function_is_required_for_forge_evidence_only(self):
        for status in ("REFUTED", "CONFIRMED"):
            for what, evidence, expected_exit in self.cases():
                refused = expected_exit != 0
                with self.subTest(status=status, citation=what):
                    self.assertEqual(expected_exit, self.run_cli(
                        "promote", "--id", "R-6", "--to", status, "--evidence", evidence,
                        "--reason", KILL_REASON))
                    self.assertEqual("TIER-1" if refused else status,
                                     replay(self.eng)["R-6"]["status"])
                    if refused:                   # the row stayed where it was
                        continue
                    cli.main(["--engagement", str(self.eng), "promote", "--id", "R-6",
                              "--to", "TIER-1", "--dedup", "ledger/dedup/R-6.md"])

    def test_the_refusal_says_what_to_write(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.run_cli("promote", "--id", "R-6", "--to", "REFUTED", "--evidence", self.poc())
        self.assertIn("G15", buf.getvalue())
        self.assertIn("::test_H7_refuted", buf.getvalue())


class TestExistingRowsAreNotReJudged(Promoted):
    """The main risk this rule carries. The state guard runs at `Stop` on EVERY engagement on
    the machine, so a rule that re-judged closed rows would block every live engagement the
    moment the runtime pulled it. A row already REFUTED citing a bare `.t.sol` file -- 186 of
    them exist across the engagements on disk -- must keep passing every check unchanged.
    """
    def test_a_preexisting_bare_file_citation_passes_verify_and_the_state_guard(self):
        import ledger_state_guard as LSG
        append(self.eng, {"id": "R-6", "event": "promote", "to": "REFUTED",
                          "evidence": self.poc(), "by": "promoted-before-REF-1"})
        cli.redraw(self.eng)
        self.assertEqual("REFUTED", replay(self.eng)["R-6"]["status"])
        self.assertEqual(0, self.run_cli("verify"))
        self.assertEqual([m for _, m in LSG.state_violations(self.eng) if "G15" in m], [],
                         "the state guard must never re-judge a row closed before the rule")

    def test_a_preexisting_refuted_row_with_no_reason_passes_verify_and_the_state_guard(self):
        """REF-26's half of the same risk. The reason requirement reaches new promotions
        only: of the 237 `REFUTED` rows on disk today, 236 carry no reason (counted
        2026-09-29; the one that does is engagement 14 H7), so a rule that re-judged them
        would block every live engagement the moment the runtime pulled it."""
        import ledger_state_guard as LSG
        append(self.eng, {"id": "R-6", "event": "promote", "to": "REFUTED",
                          "evidence": self.poc() + "::test_R6", "by": "promoted-before-REF-26"})
        cli.redraw(self.eng)
        board = (self.eng / "ledger" / "ledger.md").read_text()
        self.assertNotIn("REASON:", board, "the fixture must be a row with no reason at all")
        self.assertEqual(0, self.run_cli("verify"))
        self.assertEqual([m for _, m in LSG.state_violations(self.eng) if "REFUTED [" in m], [],
                         "the state guard must never re-judge a kill closed before the rule")


class TestFreeTextSurvivesTheRender(Promoted):
    """REF-30: a `|` or a newline in free text must not re-split or break the row.

    A ledger row IS a markdown table line, so an unescaped `|` in a hypothesis or in a
    prose kill reason adds cells: `import` then reads the wrong columns, and
    `ledger_guard.field()` cuts the value off at that pipe -- while `verify` sees nothing
    wrong, because it compares the board with a fresh render and the corruption
    round-trips. Hypotheses written with absolute-value bars (`|U|`) have been split this
    way on hand-written boards. Since REF-26 every REFUTED promotion carries a prose
    `--reason`, and prose is where a pipe comes from.

    The write half is `escape_cell` in `_render_parts`; the read half is `unescape_cell`
    in `field()`. This is the test that pins them to each other.
    """

    # A hypothesis, an entry point and an invariant with pipes, then a kill reason with
    # a pipe AND a newline -- every shape the fix has to survive, in one row.
    HYP = "at most one live lock per user: `|{ i : locks[i].amount > 0 }| <= 1`"
    ENTRY = "VaultQueue.withdraw | external | any holder"
    INV = "|locks| is monotone under withdraw"
    REASON = ("the search clamps the index before the read, so `|q - p|` stays 0 and the\n"
              "wrong-value claim cannot hold; test_R6 pins it")
    HUMAN = "RJ 2026-09-30: admin-gated | sponsor rule 4.2 | not our call"

    RENDER_COLUMNS = 6                      # id | hypothesis | entry | invariant | status | evidence

    def _row(self) -> str:
        board = (self.eng / "ledger" / "ledger.md").read_text()
        rows = [ln for ln in board.splitlines() if ln.startswith("| R-6 ")]
        self.assertEqual(1, len(rows), f"R-6 is not exactly one line of the board:\n{board}")
        return rows[0]

    def _cells(self, row: str) -> list[str]:
        return [c.strip() for c in row.strip().strip("|").split("|")]

    def test_piped_free_text_round_trips_through_render_verify_and_field(self):
        import ledger_guard
        # `add` cannot be re-run for R-6 (rows are never recreated), so the piped
        # hypothesis, entry and invariant go on a second row promoted the same way.
        self.run_cli("add", "--id", "R-7", "--hypothesis", self.HYP,
                     "--entry", self.ENTRY, "--invariant", self.INV)
        self.tier1("R-7")
        poc = self.eng / "test" / "R7.t.sol"
        poc.parent.mkdir(parents=True, exist_ok=True)
        poc.write_text("contract T { function test_R7() public {} }")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-7", "--to", "REFUTED",
                                         "--evidence", "test/R7.t.sol::test_R7",
                                         "--reason", self.REASON))
        self.run_cli("render")

        board = (self.eng / "ledger" / "ledger.md").read_text()
        row = [ln for ln in board.splitlines() if ln.startswith("| R-7 ")]
        self.assertEqual(1, len(row), f"R-7 is not exactly one line of the board:\n{board}")
        cells = self._cells(row[0])
        self.assertEqual(self.RENDER_COLUMNS, len(cells),
                         f"free text re-split the row into {len(cells)} cells: {cells}")
        self.assertEqual(0, self.run_cli("verify"))

        # Each free-text value comes back as written, normalised ONLY in whitespace.
        # The positional cells are read by position; the inline fields through field(),
        # which is what every guard uses.
        for name, written, read_back in (
            # The positional cells have no reader of their own, so they are decoded here.
            ("hypothesis", self.HYP, unescape_cell(cells[1])),
            ("entry", self.ENTRY, unescape_cell(cells[2])),
            ("invariant", self.INV, unescape_cell(cells[3])),
            # field() decodes already -- that is the half under test.
            ("REASON", self.REASON, ledger_guard.field(row[0], "REASON")),
        ):
            with self.subTest(name):
                self.assertEqual(" ".join(written.split()), read_back)

        # The EVENT LOG is the state, and it holds the prose the human typed -- pipes,
        # newline and all -- never the transport encoding.
        logged = replay(self.eng)["R-7"]["fields"]
        self.assertEqual(self.REASON, logged["reason"])
        self.assertEqual(self.HYP, logged["hypothesis"])

    def test_a_piped_human_record_survives_the_state_guard(self):
        """The same round trip on the other prose field, through the guard that runs at
        `Stop` on every engagement -- not just through `verify`."""
        import ledger_guard
        import ledger_state_guard as LSG
        self.answer_residue()
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", self.HUMAN))
        self.run_cli("render")
        row = self._row()
        self.assertEqual(self.RENDER_COLUMNS, len(self._cells(row)))
        self.assertEqual(" ".join(self.HUMAN.split()), ledger_guard.field(row, "HUMAN"))
        self.assertEqual([], [m for _, m in LSG.state_violations(self.eng) if "G2" in m],
                         "a piped HUMAN record must still satisfy G2")

    def test_an_imported_escaped_cell_is_stored_as_the_text_it_means(self):
        """The generators (`conduct.py`, `fix-adjacency.py`, `opposite-tail.py`) escape on
        their way into the table `import` reads. The log stores prose, so it decodes."""
        src = self.eng / "01-hunt" / "rows.md"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("| id | hypothesis | entry point + access | invariant |\n"
                       "|---|---|---|---|\n"
                       "| FA-1 | `&#124;U&#124;` grows without bound | mint | none |\n")
        self.assertEqual(0, self.run_cli("import", str(src)))
        self.assertEqual("`|U|` grows without bound",
                         replay(self.eng)["FA-1"]["fields"]["hypothesis"])
        # and the board it re-renders is back to the escaped form, on one row of 6 cells
        row = [ln for ln in (self.eng / "ledger" / "ledger.md").read_text().splitlines()
               if ln.startswith("| FA-1 ")][0]
        self.assertIn("`&#124;U&#124;`", row)
        self.assertEqual(self.RENDER_COLUMNS, len(self._cells(row)))


class TestPreFixRowsReadExactlyAsBefore(Promoted):
    """REF-30's half of the main risk. `field()` now decodes `&#124;`, and it is the reader
    the Stop-hook state guard uses on EVERY engagement on the machine -- so a decode that
    changed what an existing value means would re-judge closed rows the moment the runtime
    pulled it. What makes this safe is that a row written before the escape holds no
    `&#124;`. These two cases pin the two ways that could stop being true.
    """

    # A row of the shape already on disk: a raw `|` inside the HUMAN value, no entity
    # anywhere. Rows hand-written before the escape look like this.
    PRE_FIX_ROW = ("| R-6 | at most one live lock per user | VaultQueue | monotone | "
                   "`SCOPE-HELD` | HUMAN: RJ: sponsor rule 4.2 | out of scope |")

    def test_a_raw_pipe_in_an_old_row_still_reads_the_way_it_always_did(self):
        """The decode must be a NO-OP on text that never went through the escape. It does
        not repair an old row -- `field()` still ends the value at the raw `|`, exactly as
        it did before -- because repairing it would change what a closed row means."""
        import ledger_guard
        self.assertEqual("RJ: sponsor rule 4.2",
                         ledger_guard.field(self.PRE_FIX_ROW, "HUMAN"))
        self.assertNotIn("&#124;", self.PRE_FIX_ROW)

    def test_a_row_with_no_pipes_renders_byte_identically(self):
        """The other way it could break: the escape must not touch text without a pipe.
        The expected line is written out in full, so a change to the encoding fails here
        rather than silently rewriting every board on disk at the next `render`."""
        import ledger_state_guard as LSG
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "REFUTED",
                                         "--evidence", self.poc() + "::test_R6",
                                         "--reason", "the clamp holds; test_R6 pins it"))
        board = (self.eng / "ledger" / "ledger.md").read_text()
        self.assertIn(
            "| R-6 | Checkpoints.sol trace library returns a wrong value |  |  | "
            "`REFUTED` | EVIDENCE: test/R6.t.sol::test_R6 \u00b7 DEDUP: ledger/dedup/R-6.md "
            "\u00b7 REASON: the clamp holds; test_R6 pins it |",
            board)
        self.assertEqual(0, self.run_cli("verify"))
        self.assertEqual([], [m for _, m in LSG.state_violations(self.eng)],
                         "a plain row must raise nothing new")


class TestScopeIsTheHumansCall(Promoted):
    def test_scope_held_without_a_human_record_is_refused(self):
        """A model recording its own reasoning here IS the failure mode."""
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD"))

    def test_scope_held_with_a_human_record_is_accepted(self):
        """The fixture's sidecar is `result: MATCH` with no `unmatched:`, which is the
        shape that cost a real engagement its paid findings, so G12 refuses it until the residue
        question is answered. Answering
        it is what makes this a legitimate scope hold rather than a silent retirement."""
        self.answer_residue()
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", "RJ 2026-08-31: admin-gated, sponsor rule 4.2"))


class TestG3IsStructural(Promoted):
    def test_a_row_cannot_vanish(self):
        """G3 needed a guard when state was a mutable table -- a row could be deleted or
        have its status token removed. In an append-only log a row is unreachable by
        construction: there is no delete verb and replay() folds every event ever written."""
        self.run_cli("promote", "--id", "R-6", "--to", "REFUTED",
                     "--evidence", self.poc() + "::test_R6", "--reason", KILL_REASON)
        self.assertEqual("REFUTED", replay(self.eng)["R-6"]["status"])
        self.assertEqual(0, self.run_cli("verify"))


class TestOscillation(Promoted):
    def test_a_row_that_changes_status_twice_is_counted(self):
        """The measurement from the design note section 2. CAAF Finding 8 reports a
        deterministic validator failing at commodity reasoning because the model repaired
        one constraint while re-breaking another. Our preconditions are independent per
        row, so we expect this to stay at zero -- expecting is not measuring."""
        from store import status_changes, revisits
        self.run_cli("promote", "--id", "R-6", "--to", "REFUTED",
                     "--evidence", self.poc() + "::test_R6", "--reason", KILL_REASON)
        row = replay(self.eng)["R-6"]
        # A healthy row: two transitions, and NO revisit. The first cut of this metric
        # counted creation as a change and scored this 3, which would have flagged every
        # correctly-processed row as oscillating.
        self.assertEqual(2, status_changes(row))   # UNTESTED -> TIER-1 -> REFUTED
        self.assertEqual(0, revisits(row))

    def test_a_row_driven_back_to_a_prior_status_is_flagged(self):
        """The real oscillation signature: re-entering a status already left. engagement 9's
        seven rows were demoted REFUTED -> UNTESTED by hand, which is exactly this."""
        from store import revisits
        self.run_cli("promote", "--id", "R-6", "--to", "BLOCKED",
                     "--reason", "requires a mainnet fork we do not have")
        self.run_cli("promote", "--id", "R-6", "--to", "TIER-1")
        row = replay(self.eng)["R-6"]
        self.assertEqual(1, revisits(row))         # TIER-1 -> BLOCKED -> TIER-1


class TestG12KnownIssueResidue(Promoted):
    """REF-2. A Known Issue is one finding and retires one claim; the row asserts a grid.

    On one engagement, cut from this release, most of the ledger was retired as SCOPE-HELD,
    every sidecar recorded MATCH on the root cause alone, and every finding the contest paid
    for lived in the residue. Measured before building: this fires on all but one of those
    rows (the exception being the worked example) and on ZERO rows in every other engagement
    on disk.
    """

    def test_match_with_empty_unmatched_is_refused(self):
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", "RJ: matches KI M-75"))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_unmatched_none_is_a_legal_answer(self):
        """The check enforces that the question was ASKED, not what was concluded.
        Shipping the verdict instead would be shipping an unvalidated behavioural claim."""
        self.answer_residue("none")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", "RJ: matches KI M-75, no residue"))

    def test_a_recorded_residue_passes(self):
        self.answer_residue("KI M-75 covers ONE user's historical read drifting. It does "
                            "not reach the aggregate case: numerators exceeding the stored "
                            "denominator, oversubscribing the pot.")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", "RJ: partial cover, residue filed"))

    def test_the_message_names_all_three_axes(self):
        """A block is information, not an obstacle. Each axis is the one a real instance
        turned on: cause (X-2), clause (R-5), consequence (R-6)."""
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD", "--human", "x")
        msg = err.getvalue()
        for axis in ("CAUSE", "CLAUSE", "CONSEQUENCE"):
            self.assertIn(axis, msg)
        self.assertIn("legal answer", msg)

    def test_no_sidecar_means_no_G12(self):
        """A SCOPE-HELD row with no dedup sidecar is a SCOPE judgement, not a dedup
        retirement — dedup was never the reason. 22 such rows exist across 6 engagements
        and all are legitimate; firing there would be 22 false positives."""
        self.add(rid="R-9", hyp="admin can rug via privileged setter")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-9", "--to", "SCOPE-HELD",
                                         "--human", "RJ: rogue-admin exclusion, sponsor rule 4.2"))

    def test_partial_is_untouched_by_g12_and_g16(self):
        """PARTIAL already requires `unmatched:` through G1. G12 must not double-report."""
        p = self.eng / "ledger" / "dedup" / "R-6.md"
        p.write_text(p.read_text().replace("result: MATCH", "result: PARTIAL")
                     + "\nunmatched: the impact leg is not covered by the listed issue at all\n")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", "RJ: partial"))


class TestG16AttacksOnAFix(Promoted):
    """REF-31. On engagement 22 rows generated as attacks on a known issue's mitigation or fix
    shared its root cause and were retired against it; other researchers then filed them. A row
    whose claim is about an entry's fix, mitigation or bound ATTACKS the entry: it is tested,
    never parked as a duplicate of it."""

    HUMAN = "RJ: matches KI 3"

    def scope_held(self) -> int:
        import io, contextlib
        self.err = io.StringIO()
        with contextlib.redirect_stderr(self.err), contextlib.redirect_stdout(io.StringIO()):
            return self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD", "--human", self.HUMAN)

    def test_a_plain_known_issue_match_is_parked(self):
        self.answer_residue(clause="issue", attacks_entry="no")
        self.assertEqual(0, self.scope_held())
        self.assertEqual("SCOPE-HELD", replay(self.eng)["R-6"]["status"])

    def test_a_match_on_the_mitigation_fix_or_bound_is_refused(self):
        for clause in ("mitigation", "fix", "bound"):
            with self.subTest(clause=clause):
                self.tier1()                   # a fresh sidecar each time
                self.answer_residue(clause=clause, attacks_entry="no")
                self.assertEqual(2, self.scope_held())
                self.assertIn("G16", self.err.getvalue())
                self.assertIn("TIER-1", self.err.getvalue())
                self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_a_row_generated_to_attack_the_entry_is_refused(self):
        self.answer_residue(clause="issue", attacks_entry="yes")
        self.assertEqual(2, self.scope_held())
        self.assertIn("generated to attack", self.err.getvalue())

    def test_new_promotions_must_answer_both(self):
        for missing in ({"clause": None}, {"attacks_entry": None}):
            with self.subTest(missing=missing):
                self.tier1()
                self.answer_residue(**missing)
                self.assertEqual(2, self.scope_held())
                self.assertIn("attacks_entry", self.err.getvalue())

    def test_the_stop_backstop_is_silent_on_old_unanswered_sidecars(self):
        """Sidecars written before REF-31 carry neither answer; the Stop hook must not fire on
        them (one engagement alone has dozens), or it gets disabled. It still refuses where the
        answers exist and say the row attacks the entry."""
        import ledger_guard
        rel = "ledger/dedup/R-6.md"
        self.answer_residue(clause=None, attacks_entry=None)
        self.assertEqual([], ledger_guard.check_g16("R-6", rel, self.eng))
        self.assertTrue(ledger_guard.check_g16("R-6", rel, self.eng, require_answers=True))
        p = self.eng / rel
        p.write_text(p.read_text() + "clause: mitigation\nattacks_entry: no\n")
        self.assertTrue(ledger_guard.check_g16("R-6", rel, self.eng))

    def test_the_stop_backstop_calls_g16(self):
        """Wiring, not the predicate: a sidecar edited after parking to say the row attacks the
        entry's mitigation must surface at Stop. Fails if the state guard's call is removed."""
        import ledger_state_guard as LSG
        self.answer_residue(clause="issue", attacks_entry="no")
        self.assertEqual(0, self.scope_held())
        self.run_cli("render")
        p = self.eng / "ledger" / "dedup" / "R-6.md"
        p.write_text(p.read_text().replace("clause: issue", "clause: mitigation"))
        self.assertTrue([m for _, m in LSG.state_violations(self.eng) if "G16" in m])

    def test_yaml_booleans_are_read_as_answers(self):
        """`attacks_entry: yes` loads as True in YAML; it must still count as yes."""
        import ledger_guard
        self.answer_residue(clause="issue", attacks_entry="yes")
        self.assertTrue(ledger_guard.check_g16("R-6", "ledger/dedup/R-6.md", self.eng))


class TestRenderIsGuardClean(Fixture):
    def test_the_render_declares_its_format_on_line_1(self):
        """G0c wants `<!-- ledger-format: table-v1 -->` as line 1. A generated ledger that
        omitted it would make the CLI emit a file its own guard family warns about --
        found on the engagement 9 migration, not by a fixture."""
        self.add()
        self.run_cli("render")
        first = (self.eng / "ledger" / "ledger.md").read_text().splitlines()[0]
        self.assertIn("ledger-format", first)

    def test_the_rendered_ledger_passes_the_guards(self):
        """End to end: what the CLI writes must satisfy the parser-based guards, or the
        two layers disagree about the same file."""
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent.parent / "guards"))
        from ledger_guard import evaluate, parse_rows
        self.add()
        self.run_cli("render")
        led = self.eng / "ledger" / "ledger.md"
        content = led.read_text()
        self.assertTrue(parse_rows(content), "rendered ledger parses no rows")
        self.assertEqual([], [e for e in evaluate(led, content) if not e.startswith("G11")])


class TestReasonRequiredToDecline(Fixture):
    """Every status that takes a row off the board must record why, in a field.

    BELOW-BAR, BLOCKED and BLOCKED-OUT-OF-HARNESS close a row with no PoC spend owed (no
    waypoint, no evidence), so REF-22 requires `--reason` on each -- the same shape
    `check_below_bar` already enforced for BELOW-BAR alone. REFUTED joined them (REF-26,
    decided 2026-09-24, built once REF-22's close-out check shipped): its evidence says a
    test ran, not what the tester concluded, so without the reason the refutation critic has
    nothing to attack. A bare status on any of the four is the silent-drop channel the
    immovable rules forbid.
    """
    REASONS = {
        "BELOW-BAR": "Critical-only program; this is griefing DoS, not theft or permanent "
                     "lock of principal",
        "BLOCKED": "Requires a mainnet fork with pinned oracle state this harness does not have",
        "BLOCKED-OUT-OF-HARNESS": "The exploit needs an off-chain relayer this harness "
                                  "cannot drive",
        "REFUTED": KILL_REASON,
    }
    # REFUTED is the one of the four that also owes the TIER-1 waypoint and a PoC, because
    # it is a kill BY evidence rather than a decline. `row_for` pays those; `evidence_for`
    # supplies the citation. The reason is what REF-26 adds on top of both.
    RESTING = {"REFUTED": "TIER-1"}

    def row_for(self, status: str) -> str:
        rid = f"R-{status.lower().replace('-', '')}"
        self.add(rid=rid)
        if status == "REFUTED":
            self.tier1(rid)
        return rid

    def evidence_for(self, status: str) -> list[str]:
        return ["--evidence", self.poc() + "::test_R6"] if status == "REFUTED" else []

    def test_without_a_reason_is_refused(self):
        """A bare status is the silent-drop channel the immovable rules forbid."""
        for status in self.REASONS:
            with self.subTest(status=status):
                rid = self.row_for(status)
                self.assertEqual(2, self.run_cli("promote", "--id", rid, "--to", status,
                                                 *self.evidence_for(status)))
                self.assertEqual(self.RESTING.get(status, "UNTESTED"),
                                 replay(self.eng)[rid]["status"])

    def test_a_bare_too_small_reason_is_refused(self):
        """The length floor exists so 'too small' cannot pass as a citation."""
        for status in self.REASONS:
            with self.subTest(status=status):
                rid = self.row_for(status)
                self.assertEqual(2, self.run_cli("promote", "--id", rid, "--to", status,
                                                 *self.evidence_for(status),
                                                 "--reason", "too small"))

    def test_a_cited_reason_is_accepted(self):
        """The three declines need no waypoint and no PoC -- nothing was spent, so they go
        direct from UNTESTED. REFUTED pays both first and still needs the reason."""
        for status, reason in self.REASONS.items():
            with self.subTest(status=status):
                rid = self.row_for(status)
                self.assertEqual(0, self.run_cli("promote", "--id", rid, "--to", status,
                                                 *self.evidence_for(status),
                                                 "--reason", reason))
                self.assertEqual(status, replay(self.eng)[rid]["status"])
                self.assertEqual(0, self.run_cli("verify"))

    def test_the_below_bar_reason_can_come_from_the_sidecar(self):
        """The citation may live in the dedup sidecar's `below_bar_reason:` key. BLOCKED
        has no equivalent sidecar fallback (out of scope for REF-22), so this stays
        BELOW-BAR-only."""
        rid = self.row_for("BELOW-BAR")
        rel = self.sidecar(rid,
            "result: NO-MATCH\nbelow_bar_reason: |\n  Critical-only; a griefing revert-DoS, "
            "not theft or permanent lock of user principal.\n")
        self.assertEqual(0, self.run_cli("promote", "--id", rid, "--to", "BELOW-BAR",
                                         "--dedup", rel))



class TestG14IsChargedAtPromote(Fixture):
    """G14 (REF-3) runs as a precondition of the mutation, not only as a document-edit hook.

    Wiring is the thing that needed a test: a guard that no call site reaches enforces nothing
    and says nothing, which is how G4-G9 came to have register rows and no code.
    """

    BODY = "".join(f"F-2026-100{i} Medium\n\n" + ("prose about this finding. " * 45) + "\n\n"
                   for i in range(1, 4))

    def dedup(self):
        return self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "terms: [checkpoint, trace, sentinel]\nresult: NO-MATCH\n"))

    def test_a_no_match_over_unread_bodies_is_refused_and_the_row_does_not_move(self):
        (self.eng / "00-triage" / "prior-audits-text").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audits-text" / "hacken.txt").write_text(self.BODY)
        self.add()
        self.assertEqual(2, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", self.dedup()))
        self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])

    def test_the_same_promotion_passes_once_the_body_is_searched(self):
        self.header()
        (self.eng / "00-triage" / "prior-audits-text").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audits-text" / "hacken.txt").write_text(self.BODY)
        self.add()
        rel = self.sidecar("R-6", (
            "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
            "  - 00-triage/prior-audits-text/hacken.txt\n"
            "terms: [checkpoint, trace, sentinel]\nresult: NO-MATCH\n"))
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", rel))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_an_engagement_with_no_bodies_is_untouched(self):
        """The common path stays silent: G14 asks whether a corpus was READ, never whether
        one exists. G1 already owns the acquisition question."""
        self.header()
        self.add()
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1",
                                         "--dedup", self.dedup()))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])


class TestEveryReportAndEveryBody(Fixture):
    """REF-31 (engagement 22): a second internal-audit round was never read, and a PARTIAL against the
    known issues hid a full MATCH in it. At TIER-1 the CLI now refuses (a) while a prior-audit
    report has no extract and key, where the engagement keeps 00-triage/prior-audit-index.md, and
    (b) a PARTIAL or NO-MATCH that did not search EVERY finding-body file."""

    BODY = TestG14IsChargedAtPromote.BODY

    def bodies(self, *names):
        d = self.eng / "00-triage" / "prior-audits-text"
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / f"{n}.txt").write_text(self.BODY)

    def promote(self, result, searched, extra=""):
        rel = self.sidecar("R-6", "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
                           + "".join(f"  - 00-triage/prior-audits-text/{s}.txt\n" for s in searched)
                           + f"terms: [checkpoint, trace, sentinel]\nresult: {result}\n" + extra)
        return self.run_cli("promote", "--id", "R-6", "--to", "TIER-1", "--dedup", rel)

    def test_an_unread_report_refuses_tier1_where_the_index_exists(self):
        self.header()
        self.add()
        (self.eng / "00-triage" / "prior-audit-index.md").write_text("# Prior-audit index\n")
        self.bodies("hacken")
        self.assertEqual(2, self.promote("NO-MATCH", ["hacken"]))       # hacken.pdf has no key
        (self.eng / "00-triage" / "prior-audit-keys").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audit-keys" / "hacken.json").write_text("{}")
        self.assertEqual(0, self.promote("NO-MATCH", ["hacken"]))
        self.assertEqual("TIER-1", replay(self.eng)["R-6"]["status"])

    def test_without_the_index_unread_reports_do_not_refuse(self):
        """Engagements created before 2026-10-19 keep no index and stay silent."""
        self.header()
        self.add()
        self.assertEqual(0, self.promote("NO-MATCH", []))

    def test_a_partial_or_no_match_must_search_every_body(self):
        unmatched = "unmatched: the listed issue covers one user's read, not the aggregate case at all\n"
        quote = f"quote: \"{REAL_QUOTE}\"\n"
        for result, extra in (("NO-MATCH", ""), ("PARTIAL", quote + unmatched)):
            with self.subTest(result=result):
                self.tearDown(); self.setUp(); self.header(); self.add()
                self.bodies("round1", "round2")
                self.assertEqual(2, self.promote(result, ["round1"], extra))
                self.assertEqual("UNTESTED", replay(self.eng)["R-6"]["status"])
                self.assertEqual(0, self.promote(result, ["round1", "round2"], extra))

    def test_a_folder_in_searched_covers_every_body_under_it(self):
        self.header()
        self.add()
        self.bodies("round1", "round2")
        rel = self.sidecar("R-6", "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
                           "  - 00-triage/prior-audits-text\n"
                           "terms: [checkpoint, trace, sentinel]\nresult: NO-MATCH\n")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "TIER-1", "--dedup", rel))

    def test_the_stop_backstop_keeps_the_old_any_body_rule(self):
        import ledger_guard
        self.bodies("round1", "round2")
        rel = self.sidecar("R-6", "searched:\n  - 00-triage/prior-audits-text/round1.txt\n"
                           "terms: [a, b, c]\nresult: NO-MATCH\n")
        self.assertEqual([], ledger_guard.check_g14("R-6", rel, self.eng))
        self.assertTrue(ledger_guard.check_g14("R-6", rel, self.eng, every=True))


class TestG17IsChargedAtPromote(Fixture):
    """G17 (engagement 22): each function the row's entry names is searched on its own, by
    the tool, and every hit in a source document is answered in `name_hits_read:`. Charged by the
    CLI only, with the dedup obligation, so it never re-judges a row whose G1 is discharged."""

    ENTRY = "`IPool.openPosition` by the pool owner, forwarded to `Registry.openPosition`"

    def promote(self, terms, to="TIER-1", rid="AB-20", result="PARTIAL", answered=False, **flags):
        """AB-20's own sidecar recorded PARTIAL. `answered` adds the README hit's answer."""
        answer = ("name_hits_read:\n  - name: openPosition\n    file: target/README.md\n"
                  "    note: \"describes the owner path, not the forwarded registry call\"\n"
                  if answered else "")
        rel = self.sidecar(rid, "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
                           f"terms: [{terms}]\nresult: {result}\nquote: \"{REAL_QUOTE}\"\n"
                           "unmatched: the listed issue covers the owner path, not the forwarded "
                           "registry call\nclause: issue\nattacks_entry: no\n" + answer)
        argv = ["promote", "--id", rid, "--to", to, "--dedup", rel]
        for k, v in flags.items():
            argv += [f"--{k}", v]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = self.run_cli(*argv)
        return code, err.getvalue()

    def setUp(self):
        super().setUp()
        self.header()
        self.run_cli("add", "--id", "AB-20", "--hypothesis", "owner picks a JIT lock period",
                     "--entry", self.ENTRY)
        (self.eng / "target").mkdir(exist_ok=True)
        (self.eng / "target" / "README.md").write_text(
            "Opening a position calls the pool's `openPosition`, which passes the initial "
            "lock period explicitly.\n")

    def test_the_ab_20_promotion_is_refused_and_the_row_does_not_move(self):
        code, err = self.promote('"openPosition lockPeriod", "JIT lock", "owner-chosen lock"')
        self.assertEqual(2, code)
        self.assertIn("G17 [AB-20]", err)
        self.assertIn("openPosition", err)
        self.assertEqual("UNTESTED", replay(self.eng)["AB-20"]["status"])

    def test_it_passes_once_the_readme_hit_is_answered(self):
        code, err = self.promote('"openPosition lockPeriod", "JIT lock", "owner-chosen lock"',
                                 answered=True)
        self.assertEqual(0, code, err)
        self.assertEqual("TIER-1", replay(self.eng)["AB-20"]["status"])

    def test_listing_the_bare_name_as_a_term_does_not_discharge_it(self):
        code, err = self.promote('"openPosition lockPeriod", "JIT lock", openPosition')
        self.assertEqual(2, code)
        self.assertIn("G17 [AB-20]", err)
        self.assertIn("target/README.md:1", err)

    def test_a_match_is_silent(self):
        code, err = self.promote('"openPosition lockPeriod", "JIT lock", "owner-chosen lock"',
                                 result="MATCH")
        self.assertEqual(0, code, err)

    def test_a_sidecar_cited_on_a_no_waypoint_exit_is_charged_too(self):
        """UNTESTED -> SCOPE-HELD cites a sidecar without passing TIER-1, so G1 was never
        discharged and this is the first time the sidecar is judged."""
        code, err = self.promote('"openPosition lockPeriod", "JIT lock", "owner-chosen lock"',
                                 to="SCOPE-HELD", human="RJ 2026-10-20: known issue K-29")
        self.assertEqual(2, code)
        self.assertIn("G17 [AB-20]", err)

    def test_an_entry_with_no_identifier_is_silent(self):
        self.run_cli("add", "--id", "R-9", "--hypothesis", "x", "--entry", "anyone, permissionless")
        code, err = self.promote("checkpoint, trace, sentinel", rid="R-9")
        self.assertEqual(0, code, err)

    def test_a_row_whose_g1_was_discharged_before_the_rule_is_not_rejudged(self):
        """The grandfathering. A row that reached TIER-1 with a phrase-only sidecar before G17
        existed carries G1 in its satisfied set; promoting it onward must not re-open the dedup,
        and neither verify nor the Stop-hook backstop may report it."""
        import ledger_state_guard as LSG
        rel = self.sidecar("AB-20", "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
                           "terms: [\"openPosition lockPeriod\", a, b]\nresult: NO-MATCH\n")
        append(self.eng, {"id": "AB-20", "event": "promote", "to": "TIER-1", "dedup": rel,
                          "satisfied": ["G1"], "by": "promoted-before-G17"})
        cli.redraw(self.eng)
        poc = self.poc("test/AB20.t.sol")
        (self.eng / poc).write_text("contract T { function test_AB20() public {} }")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = self.run_cli("promote", "--id", "AB-20", "--to", "CONFIRMED",
                                "--evidence", poc + "::test_AB20")
        self.assertEqual(0, code, err.getvalue())
        self.assertNotIn("G17", err.getvalue())
        self.assertEqual(0, self.run_cli("verify"))
        self.assertEqual([m for _, m in LSG.state_violations(self.eng) if "G17" in m], [])


class TestG18PrivilegedTestBeforeScopeHeld(Fixture):
    """G18 (REF-33, engagement 23): a row naming a privileged action does not leave the work on a ruling
    (SCOPE-HELD or BELOW-BAR) without the privileged-action test's verdict and real evidence. Silent
    without a filled roles file."""

    ROLES = ("# Privileged actors\n\n## Trusted roles\n\n| role | privileged functions | source (file:line) |\n"
             "|---|---|---|\n| GUARDIAN | `setLtv` | contracts/PoolRoles.sol:12 |\n")
    GOOD = "FAIL (c): the harm is the documented effect, src/Vault.sol:3"

    def setUp(self):
        super().setUp()
        self.header()
        (self.eng / "target" / "src").mkdir(parents=True)
        (self.eng / "target" / "src" / "Vault.sol").write_text("// a\n// b\n/// pausing blocks this market only\n")
        self.run_cli("add", "--id", "A-1", "--hypothesis", "GUARDIAN pauses one market and liquidations of "
                     "unrelated collateral revert", "--entry", "anyone")
        self.run_cli("add", "--id", "A-2", "--hypothesis", "rounding favours the borrower", "--entry", "anyone")

    def roles(self, text=None):
        d = self.eng / "01-scope"
        d.mkdir(exist_ok=True)
        (d / "privileged-actors.md").write_text(text or self.ROLES)

    def hold(self, rid, *extra, to="SCOPE-HELD"):
        err = io.StringIO()
        ruling = ["--human", "RJ 2026-10-20: trusted role"] if to == "SCOPE-HELD" else \
                 ["--reason", "program bar: admin actions are out of scope (rules p.2)"]
        with contextlib.redirect_stderr(err):
            code = self.run_cli("promote", "--id", rid, "--to", to, *ruling, *extra)
        return code, err.getvalue()

    def test_refused_without_the_test(self):
        self.roles()
        code, err = self.hold("A-1")
        self.assertEqual(2, code)
        self.assertIn("G18 [A-1]", err)
        self.assertIn("GUARDIAN", err)
        self.assertEqual("UNTESTED", replay(self.eng)["A-1"]["status"])

    def test_the_verdict_must_lead_and_be_alone(self):
        self.roles()
        for value in ("FAIL", "the admin is trusted", "FAILED (c), src/Vault.sol:3", "PASSING src/Vault.sol:3",
                      "NOT FAIL src/Vault.sol:3", "PASS or FAIL, src/Vault.sol:3"):
            with self.subTest(value=value):
                self.assertEqual(2, self.hold("A-1", "--privileged-test", value)[0])

    def test_the_evidence_must_exist(self):
        """Review of G18: any `a.b:1` once counted as a citation."""
        self.roles()
        notes = self.eng / "01-scope" / "privileged-actors.md"
        for value in ("FAIL (c): Pool.sol:1", "FAIL (c): src/Vault.sol:99", "FAIL (c): e.g:1",
                      'FAIL (c): "a quote that appears nowhere at all in this engagement"',
                      f"FAIL (c): {notes.relative_to(self.eng)}:1"):
            with self.subTest(value=value):
                self.assertEqual(2, self.hold("A-1", "--privileged-test", value)[0])

    def test_passes_with_a_real_citation_and_is_recorded(self):
        self.roles()
        code, err = self.hold("A-1", "--privileged-test", self.GOOD)
        self.assertEqual(0, code, err)
        promote = [e for e in replay(self.eng)["A-1"]["history"] if e["event"] == "promote"][-1]
        self.assertIn("src/Vault.sol:3", promote["privileged_test"])

    def test_evidence_is_checked_per_verdict_as_phase_4_defines_it(self):
        """Richard, 2026-10-21. FAIL, the verdict that lets an admin row out, must cite the audited code or
        the programme's own documents; NO-ACTION must quote the matched words from the row; the other
        verdicts set nothing aside on admin grounds, so recording them is enough."""
        self.roles()
        triage = self.eng / "00-triage"
        triage.mkdir(exist_ok=True)
        (triage / "brief.md").write_text("# Brief\nThe guardian may pause any single market at will.\n")
        cases = [
            ("FAIL (c): src/Vault.sol:3", 0),                                  # audited code
            ("FAIL (c): the brief says so, 00-triage/brief.md:2", 0),          # programme document
            ('FAIL (c): "The guardian may pause any single market"', 0),        # quote from it
            ('FAIL (c): "pauses one market and liquidations"', 2),              # the row itself: no
            ('NO-ACTION: matched only "pauses one market and liquidations"', 0),  # quote of the row
            ("NO-ACTION: the word is incidental", 2),                           # no quote
            ('NO-ACTION: "a quote that is in no row at all here"', 2),          # not from the row
        ]
        for i, (value, want) in enumerate(cases):
            rid = f"V-{i}"
            self.run_cli("add", "--id", rid, "--hypothesis", "GUARDIAN pauses one market and liquidations of "
                         "unrelated collateral revert", "--entry", "anyone")
            with self.subTest(value=value):
                self.assertEqual(want, self.hold(rid, "--privileged-test", value)[0])
        for i, verdict in enumerate(("PASS", "UNCLEAR", "BOUND-CITED", "SEMI-TRUSTED")):
            rid = f"W-{i}"
            self.run_cli("add", "--id", rid, "--hypothesis", "GUARDIAN pauses again", "--entry", "anyone")
            with self.subTest(verdict=verdict):
                self.assertEqual(0, self.hold(rid, "--privileged-test", f"{verdict}: see the screen worklist")[0])
        (self.eng / "notes.md").write_text("pausing one market is documented here at length\n")
        self.assertEqual(2, self.hold("A-1", "--privileged-test",
                                      'FAIL (c): "pausing one market is documented here"')[0])
        self.run_cli("add", "--id", "A-3", "--hypothesis", "GUARDIAN pauses the market", "--entry", "anyone")
        self.assertEqual(0, self.hold("A-3", "--privileged-test",
                                      'FAIL (c): "pausing blocks this market only"')[0])

    def test_a_no_action_quote_matches_the_row_as_screeners_write_it(self):
        """Replay of engagement 21's 194 screen cells (2026-10-21): real NO-ACTION quotes drop the row's
        backticks, skip words with "...", and are often just the matched words ("any borrower")."""
        self.roles()
        cases = [('NO-ACTION: quote: "During an outer Router.execute REBALANCE the GUARDIAN"', 0),
                 ('NO-ACTION: quote: "During an outer ... GUARDIAN pauses"', 0),
                 ('NO-ACTION: quote: "GUARDIAN pauses"', 0),
                 ('NO-ACTION: quote: "the guardian pauses nothing"', 0),        # any case, as roles match
                 ('NO-ACTION: matched "guardian" here; actor is "someone not in the row"', 0),  # two quotes
                 ('NO-ACTION: quote: "GUARDIAN ... During"', 2)]     # the pieces must appear in order
        for i, (value, want) in enumerate(cases):
            rid = f"Q-{i}"
            self.run_cli("add", "--id", rid, "--hypothesis", "During an outer `Router.execute` REBALANCE the "
                         "GUARDIAN pauses nothing; any borrower can call it", "--entry", "anyone")
            with self.subTest(value=value):
                self.assertEqual(want, self.hold(rid, "--privileged-test", value)[0])

    def test_auditor_written_and_test_code_is_not_audited_source(self):
        """Review of the tightening (2026-10-21): a PoC comment, a target's own test or mock, and the
        engagement's evidence folder are written or chosen by the auditor, so they prove nothing."""
        self.roles()
        for rel in ("poc/Note.t.sol", "target/test/Mock.sol", "target/tests/Helper.sol", "03-evidence/Probe.sol",
                    "target/src/Vault.t.sol", "01-hunt/Probe.sol", "ledger/Probe.sol"):
            f = self.eng / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("// the guardian pause here is documented and harmless\n")
            with self.subTest(rel=rel):
                self.assertEqual(2, self.hold("A-1", "--privileged-test", f"FAIL (c): {rel}:1")[0])
                self.assertEqual(2, self.hold("A-1", "--privileged-test",
                                              'FAIL (c): "the guardian pause here is documented and harmless"')[0])

    def test_first_party_code_under_a_lib_folder_inside_src_counts(self):
        """A project may keep in-scope code in src/core/lib/; only a dependency lib/ is skipped."""
        self.roles()
        f = self.eng / "target" / "src" / "lib" / "Ticks.sol"
        f.parent.mkdir(parents=True)
        f.write_text("// a\n// b\n")
        self.assertEqual(0, self.hold("A-1", "--privileged-test", "FAIL (c): src/lib/Ticks.sol:2")[0])
        (self.eng / "target" / "foundry.toml").write_text("[profile.default]\n")   # a dependency lib/ sits beside it
        dep = self.eng / "target" / "lib" / "openzeppelin" / "Ownable.sol"
        dep.parent.mkdir(parents=True)
        dep.write_text("// a\n// b\n")
        self.run_cli("add", "--id", "A-4", "--hypothesis", "GUARDIAN pauses again", "--entry", "anyone")
        self.assertEqual(2, self.hold("A-4", "--privileged-test", "FAIL (c): lib/openzeppelin/Ownable.sol:2")[0])

    def test_programme_documents_count_only_where_they_are_verbatim_copies(self):
        """Found in review: chosen by folder name, a FAIL could cite the agent's own triage notes or a README
        it wrote. Only the verbatim programme copies in 00-triage/, and the target repo's README and docs/."""
        self.roles()
        doc = "The guardian may pause any single market at its discretion.\n"
        good = ["00-triage/brief.md", "00-triage/protocol-docs/trust.md", "00-triage/cantina-rules/rules.txt",
                "00-triage/potential-risks/risk.txt", "target/README.md", "target/docs/roles.md"]
        bad = ["00-triage/target-triage.md", "00-triage/scope-exclusions.md", "00-triage/README.md",
               "01-hunt/README.md", "ledger/docs/why.md", "notes/docs/why.md"]
        for i, rel in enumerate(good + bad):
            f = self.eng / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# x\n" + doc)
            rid = f"P-{i}"
            self.run_cli("add", "--id", rid, "--hypothesis", "GUARDIAN pauses one market", "--entry", "anyone")
            with self.subTest(rel=rel):
                self.assertEqual(0 if rel in good else 2, self.hold(rid, "--privileged-test", f"FAIL (c): {rel}:2")[0])
            f.unlink()

    def test_a_line_past_the_end_of_the_file_is_refused(self):
        self.roles()   # target/src/Vault.sol has 3 lines and ends in a newline
        self.assertEqual(2, self.hold("A-1", "--privileged-test", "FAIL (c): src/Vault.sol:4")[0])

    def test_below_bar_is_covered_too(self):
        self.roles()
        self.assertEqual(2, self.hold("A-1", to="BELOW-BAR")[0])
        self.assertEqual(0, self.hold("A-1", "--privileged-test", self.GOOD, to="BELOW-BAR")[0])

    def test_silent_for_rows_naming_no_privileged_action(self):
        self.roles()
        self.assertEqual(0, self.hold("A-2")[0])

    def test_silent_without_a_filled_roles_file(self):
        """Engagements before the file existed, and any engagement before Phase 0 writes it."""
        self.assertEqual(0, self.hold("A-1")[0])

    def test_silent_with_the_unfilled_template(self):
        template = (Path(__file__).resolve().parents[2] / "templates" / "privileged-actors.template.md").read_text()
        self.roles(template)
        self.assertEqual(0, self.hold("A-1")[0])


class TestVerifyWarnsOnMissingHeader(Fixture):
    """REF-23's other half: render composes a hand-written ledger/HEADER.md instead of
    destroying it (PR #67), but an engagement that never wrote one gets no signal that
    the board has rows and no impact bar, materiality basis or scope exclusions. `verify`
    warns; the exit code must not change either way (warn, never refuse)."""

    def _verify_output(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.run_cli("verify")
        return rc, buf.getvalue()

    def test_rows_and_no_header_warns_but_still_exits_zero(self):
        self.add()
        rc, out = self._verify_output()
        self.assertEqual(0, rc)
        self.assertIn(HEADER, out)

    def test_rows_and_a_header_stays_silent_about_it(self):
        (self.eng / HEADER).write_text("## Impact bar\n\nCritical/High only.\n")
        self.add()
        rc, out = self._verify_output()
        self.assertEqual(0, rc)
        self.assertNotIn("HEADER.md", out)

    def test_no_rows_and_no_header_stays_silent(self):
        """A fresh engagement has not written its header yet -- a gate that fires on
        everything gets disabled."""
        rc, out = self._verify_output()
        self.assertEqual(0, rc)
        self.assertNotIn("HEADER.md", out)


class TestVerifyNamesAChangedHeader(Fixture):
    """REF-23's board composes ledger/HEADER.md's text into ledger.md (PR #67). But
    verify's drift check only knew two states -- byte-identical, or 'hand-edited' -- so a
    person who did exactly what #69's own warning told them to (write or edit HEADER.md
    after the last render) was accused of tampering with the board. See #72 and 'Where I
    was wrong' in RUN-REPORT-verify-missing-header.md."""

    def _verify_stderr(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = self.run_cli("verify")
        return rc, buf.getvalue()

    def test_a_header_written_for_the_first_time_after_render(self):
        self.add()
        self.run_cli("render")
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft only.\n")
        rc, err = self._verify_stderr()
        self.assertEqual(1, rc)
        self.assertIn(HEADER, err)
        self.assertIn("render", err)
        self.assertNotIn("hand-edited", err)

    def test_a_header_that_existed_at_render_time_is_then_edited(self):
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft only.\n")
        self.add()
        self.run_cli("render")
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft and lock.\n")
        rc, err = self._verify_stderr()
        self.assertEqual(1, rc)
        self.assertIn(HEADER, err)
        self.assertIn("render", err)
        self.assertNotIn("hand-edited", err)

    def test_a_header_deleted_after_render(self):
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft only.\n")
        self.add()
        self.run_cli("render")
        (self.eng / HEADER).unlink()
        rc, err = self._verify_stderr()
        self.assertEqual(1, rc)
        self.assertIn(HEADER, err)
        self.assertIn("render", err)
        self.assertNotIn("hand-edited", err)

    def test_the_header_edited_inside_the_board_gets_the_same_message(self):
        """The two causes -- HEADER.md changed since render, or the header text hand-edited
        inside ledger.md itself -- leave the board in the identical state and cannot be told
        apart from the file alone. This test documents that they share one message; it does
        not (and cannot) resolve which one actually happened."""
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft only.\n")
        self.add()
        self.run_cli("render")
        p = self.eng / "ledger" / "ledger.md"
        p.chmod(0o644)
        p.write_text(p.read_text().replace(
            "Impact bar: theft only.", "Impact bar: theft and lock."))
        rc, err = self._verify_stderr()
        self.assertEqual(1, rc)
        self.assertIn(HEADER, err)
        self.assertNotIn("hand-edited", err)

    def test_a_row_edited_inside_the_board_still_says_hand_edited(self):
        """The guard this whole class must not weaken: a tampered row must still be called
        out as hand-edited, exactly as TestRenderDrift already checks without a header."""
        self.add()
        self.run_cli("render")
        p = self.eng / "ledger" / "ledger.md"
        p.chmod(0o644)
        p.write_text(p.read_text().replace("UNTESTED", "CONFIRMED"))
        rc, err = self._verify_stderr()
        self.assertEqual(1, rc)
        self.assertIn("hand-edited", err)
        self.assertNotIn(HEADER, err)

    def test_both_header_and_a_row_edited_still_says_hand_edited(self):
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft only.\n")
        self.add()
        self.run_cli("render")
        p = self.eng / "ledger" / "ledger.md"
        p.chmod(0o644)
        text = p.read_text().replace("Impact bar: theft only.", "Impact bar: theft and lock.")
        text = text.replace("UNTESTED", "CONFIRMED")
        p.write_text(text)
        rc, err = self._verify_stderr()
        self.assertEqual(1, rc)
        self.assertIn("hand-edited", err)

    def test_render_text_equals_its_three_parts_joined_with_no_header(self):
        self.add()
        preamble, header, table = cli._render_parts(self.eng)
        self.assertEqual("", header)
        self.assertEqual(preamble + header + table, cli.render_text(self.eng))
        self.run_cli("render")
        self.assertEqual(0, self.run_cli("verify"))

    def test_render_text_equals_its_three_parts_joined_with_a_header(self):
        (self.eng / HEADER).write_text("# Header\n\nImpact bar: theft only.\n")
        self.add()
        preamble, header, table = cli._render_parts(self.eng)
        self.assertNotEqual("", header)
        self.assertEqual(preamble + header + table, cli.render_text(self.eng))
        self.run_cli("render")
        self.assertEqual(0, self.run_cli("verify"))


class TestPhaseWritesWhatTheDoctorChecks(Fixture):
    """REF-27. The doctor has reported a GAP since 2026-09-25 unless PHASES.md accounts for
    every phase as `done` or `skipped -- <reason>`, and nothing ever wrote that file: the
    check fired on 17 of 17 engagements on disk. This command is the writer.

    The round trip is the point. The doctor owns the format, so asserting the exact text this
    command emits would only pin one half against itself; running the doctor's own check over
    its output is what catches the two drifting apart.
    """

    def doctor(self):
        spec = importlib.util.spec_from_file_location(
            "engagement_doctor",
            Path(cli.__file__).resolve().parents[1] / "engagement-doctor.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_two_copies_of_the_phase_list_agree(self):
        """The CLI keeps its own PHASE_IDS rather than importing a hyphenated script on every
        ledger call, so this is what stops the two from naming different phases."""
        doctor = self.doctor()
        self.assertEqual(doctor.PHASES, cli.PHASE_IDS)
        self.assertEqual(doctor.PHASES_FILE, cli.PHASES_FILE)

    def test_every_phase_recorded_passes_the_doctors_check(self):
        self.add()                      # the check is silent until the ledger holds a row
        for phase in cli.PHASE_IDS:
            if phase == "3":
                self.assertEqual(0, self.run_cli("phase", "--skipped", phase,
                                                 "--reason", "no fuzzer on this toolchain"))
            else:
                self.assertEqual(0, self.run_cli("phase", "--done", phase))
        self.assertEqual([], self.doctor().check_phases_recorded(self.eng))

    def test_a_missing_phase_still_fails_the_doctors_check(self):
        """The half that proves the test above asserts something: the same check must still
        report a GAP when one phase was never recorded."""
        self.add()
        for phase in cli.PHASE_IDS[:-1]:
            self.run_cli("phase", "--done", phase)
        findings = self.doctor().check_phases_recorded(self.eng)
        self.assertTrue(any("Phase 5" in detail for _, _, detail in findings), findings)

    def test_skipped_without_a_reason_is_refused(self):
        """A skip with no reason cannot be told from a phase nobody reached, which is the
        distinction the doctor's check exists to make."""
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("phase", "--skipped", "3")
        self.assertIn("--reason", str(caught.exception))
        self.assertFalse((self.eng / cli.PHASES_FILE).exists(),
                         "a refused call must not create the file")

    def test_a_later_line_corrects_an_earlier_one(self):
        """Append-only: a phase recorded wrongly is re-recorded, never edited."""
        self.run_cli("phase", "--skipped", "2", "--reason", "no Slither on this toolchain")
        self.run_cli("phase", "--done", "2")
        parsed = self.doctor().parse_phases((self.eng / cli.PHASES_FILE).read_text())
        self.assertEqual(("done", ""), parsed["2"])


class TestCount(Fixture):
    """`count` (REF-29's finish line): read-only, one `STATUS N` line per status that has
    rows, through the same replay() verify uses. Must write nothing -- the event log is
    the only state, and a read command touching it would be a second write path into the
    thing store.py exists to make append-only."""

    def _count_output(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.run_cli("count")
        return rc, buf.getvalue()

    def test_counts_rows_in_several_statuses(self):
        self.add(rid="R-1")
        self.add(rid="R-2")
        self.add(rid="R-3")
        self.run_cli("promote", "--id", "R-2", "--to", "BLOCKED",
                     "--reason", "requires a mainnet fork we do not have")
        self.run_cli("promote", "--id", "R-3", "--to", "BLOCKED",
                     "--reason", "requires a mainnet fork we do not have")
        rc, out = self._count_output()
        self.assertEqual(0, rc)
        lines = out.strip().splitlines()
        self.assertEqual(["UNTESTED 1", "BLOCKED 2"], lines)

    def test_leaves_the_event_log_byte_identical(self):
        self.add(rid="R-1")
        self.run_cli("promote", "--id", "R-1", "--to", "BLOCKED",
                     "--reason", "requires a mainnet fork we do not have")
        before = events_path(self.eng).read_bytes()
        self._count_output()
        after = events_path(self.eng).read_bytes()
        self.assertEqual(before, after)


class TestExclusionQuotedAtPromote(Fixture):
    """G20 (REF-32) is charged by `promote --to SCOPE-HELD --exclusion`; the predicate's table is in
    tooling/guards/test_ledger_guard.py. This pins the wiring: a declared exclusion hold quotes the
    list in --reason, an undeclared hold is not judged, and a MATCH sidecar exempts nothing."""

    RULE = "Incorrect data supplied by third party oracles is out of scope"

    def promote(self, rid, *extra) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self.run_cli("promote", "--id", rid, "--to", "SCOPE-HELD", "--human", "RJ: oracle rule",
                              *extra)
        return rc, err.getvalue()

    def setUp(self):
        super().setUp()
        (self.eng / "00-triage" / "scope-exclusions.md").write_text(f"# Exclusions\n\n- {self.RULE}.\n")

    def test_a_declared_exclusion_hold_must_quote_the_list(self):
        self.add("R-1")
        rc, err = self.promote("R-1", "--exclusion")
        self.assertEqual((2, True), (rc, "G20" in err), err)
        self.assertEqual(0, self.promote("R-1", "--exclusion", "--reason", f"brief: {self.RULE}")[0])

    def test_an_undeclared_hold_is_not_judged(self):
        self.add("R-2")
        rc, err = self.promote("R-2")
        self.assertEqual((0, False), (rc, "G20" in err), err)

    def test_a_match_sidecar_exempts_nothing(self):
        self.add("R-3")
        rel = self.sidecar("R-3", "result: MATCH\nunmatched: none\nclause: issue\nattacks_entry: no\n")
        rc, err = self.promote("R-3", "--exclusion", "--dedup", rel)
        self.assertIn("G20", err)
        self.assertEqual(2, rc)

    def test_the_flag_means_nothing_off_scope_held(self):
        self.add("R-4")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = self.run_cli("promote", "--id", "R-4", "--to", "BLOCKED", "--exclusion",
                              "--reason", "requires a mainnet fork we do not have")
        self.assertEqual((2, True), (rc, "G20" in err.getvalue()))


class TestKnownReview(Fixture):
    """`known-review` (Richard, 2026-10-26): every row the matcher called KNOWN goes in front of the
    human before Phase 5, on one page, with the row's claim, the entry's quote and the claims list.
    A KNOWN row is ranked last and in practice never tested, so this page is the last look it gets.
    A KNOWN row usually stays UNTESTED with no DEDUP pointer, so its sidecar is found at
    ledger/dedup/<id>.md; a row whose promotion recorded a pointer is read through that."""

    CALLER_QUOTE = "allows a caller to observe an inflated balance mid-transaction"

    def known(self, rid: str, claims: str = "") -> None:
        self.sidecar(rid, "searched:\n  - 00-triage/potential-risks/potential-risks.txt\n"
                          "terms: [vault, shares, settle]\n"
                          f"result: MATCH\nquote: \"{REAL_QUOTE}\"\n{claims}")

    def setUp(self):
        super().setUp()
        self.add("R-1", "vault credits shares before settlement; a caller reads an inflated balance")
        self.known("R-1", f"claims:\n  - caller: \"any caller mid-transaction\"\n"
                          f"    quote: \"{self.CALLER_QUOTE}\"\n")
        self.add("R-2", "a partial match")
        self.sidecar("R-2", "result: PARTIAL\n")
        self.add("R-3", "a new row")
        self.sidecar("R-3", "result: NO-MATCH\n")
        self.add("R-4", "a row with no sidecar")
        self.add("R-5", "matched before the claims list existed")
        self.known("R-5")
        self.add("R-7", "a row whose promotion recorded its sidecar")
        (self.eng / "ledger/dedup/R-7-known.md").write_text(
            (self.eng / "ledger/dedup/R-5.md").read_text())
        self.assertEqual(0, self.run_cli("promote", "--id", "R-7", "--to", "BLOCKED", "--dedup",
                                         "ledger/dedup/R-7-known.md", "--reason",
                                         "requires a mainnet fork we do not have"))

    def page(self, *extra) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.run_cli("known-review", *extra)
        return rc, out.getvalue(), err.getvalue()

    def test_lists_every_match_row_and_nothing_else(self):
        rc, out, _ = self.page()
        self.assertEqual(0, rc)
        self.assertEqual(["R-1", "R-5", "R-7"], re.findall(r"(?m)^## (\S+)", out))
        self.assertIn("credits shares before settlement", out.split("## R-5")[0], "the row's claim")
        self.assertEqual(3, out.count(REAL_QUOTE), "the entry's quote, once per row")
        self.assertIn("caller: any caller mid-transaction", out)
        self.assertIn(self.CALLER_QUOTE, out)
        self.assertIn("no claims: list", out.split("## R-5")[1])

    def test_says_which_rows_the_claims_check_would_refuse(self):
        _, out, _ = self.page()
        r1, r5 = out.split("## R-5")[0], out.split("## R-5")[1].split("## R-7")[0]
        self.assertIn("claims check: passes", r1)
        self.assertIn("claims check: FAILS", r5)

    def test_records_an_answer_per_row(self):
        self.assertEqual(0, self.page("--record", "R-1", "--answer", "agree: KNOWN")[0])
        self.assertIn("R-1: agree: KNOWN", (self.eng / cli.KNOWN_REVIEW_FILE).read_text())
        _, out, _ = self.page()
        self.assertIn("reviewed: agree: KNOWN", out.split("## R-5")[0])
        self.assertIn("not yet reviewed", out.split("## R-5")[1])

    def test_refuses_an_answer_for_a_row_that_is_not_known_or_spans_lines(self):
        for rid, answer in (("R-2", "agree"), ("R-9", "agree"), ("R-1", "agree\nR-5: agree"),
                            ("R-1", "  ")):
            with self.subTest(rid=rid, answer=answer):
                rc, _, err = self.page("--record", rid, "--answer", answer)
                self.assertEqual(2, rc)
                self.assertTrue(err)
        self.assertFalse((self.eng / cli.KNOWN_REVIEW_FILE).exists())

    def test_an_unreadable_match_sidecar_is_listed_not_dropped(self):
        """A load failure must not read as "not KNOWN": the page lists the row and says why."""
        self.add("R-8", "a row whose sidecar no longer parses")
        self.sidecar("R-8", "result: MATCH\nquote: \"unterminated\nclaims: [\n")
        _, out, _ = self.page()
        self.assertEqual(["R-1", "R-5", "R-7", "R-8"], re.findall(r"(?m)^## (\S+)", out))
        self.assertIn("sidecar unreadable", out.split("## R-8")[1])

    def test_printing_the_page_writes_nothing(self):
        before = events_path(self.eng).read_bytes()
        self.page()
        self.assertEqual(before, events_path(self.eng).read_bytes())
        self.assertFalse((self.eng / cli.KNOWN_REVIEW_FILE).exists())


if __name__ == "__main__":
    unittest.main()
