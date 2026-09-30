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
import contextlib, importlib.util, io, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cli  # noqa: E402
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
                                   "the statement has one leg, and it states the worst impact.") -> None:
        """Append an `unmatched:` answer to the fixture's sidecar. G12 checks that the
        three questions were ASKED; `none` is a legal conclusion."""
        p = self.eng / "ledger" / "dedup" / "R-6.md"
        p.write_text(p.read_text().rstrip() + f"\nunmatched: |\n  {text}\n")


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

    def test_partial_is_untouched_by_g12(self):
        """PARTIAL already requires `unmatched:` through G1. G12 must not double-report."""
        p = self.eng / "ledger" / "dedup" / "R-6.md"
        p.write_text(p.read_text().replace("result: MATCH", "result: PARTIAL")
                     + "\nunmatched: the impact leg is not covered by the listed issue at all\n")
        self.assertEqual(0, self.run_cli("promote", "--id", "R-6", "--to", "SCOPE-HELD",
                                         "--human", "RJ: partial"))


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


if __name__ == "__main__":
    unittest.main()
