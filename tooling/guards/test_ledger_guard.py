#!/usr/bin/env python3
"""Tests for G1-G3. Includes the engagement 3 regression: the real failure that cost a submission."""
import shutil, subprocess, sys, tempfile, unittest, unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ledger_guard  # noqa: E402  (G11 tests drive evaluate() and main() directly)
from ledger_guard import (  # noqa: E402
    evaluate, parse_rows, parse_row_lines, engagement_ledgers, resolve_artifact,
    TOOLKIT_ROOT, FORMAT_MARKER, is_ledger, row_status, engagement_root,
    header_missing_fields, HEADER_REQUIRED_FIELDS, RUN_WITHOUT_MODEL,
)

PRIOR_ART = (
    "Potential Risks\n"
    "  Cross-hierarchy accreditation of any DID via the new-attribute waiver: checkEligibility skips\n"
    "  the trust-chain membership check whenever the target attribute does not yet exist, so any live\n"
    "  TAO can attach a TAO or TI credential to an arbitrary DID without the target's consent.\n"
    "  setAttributeMetadata pushes a caller-supplied did string into issuers.didStore.\n"
)
EXACT = "the trust-chain membership check whenever the target attribute does not yet exist"
# REF-26: a NEW REFUTED row states the argument the kill rests on, so the G2/G15 rows below
# carry one. What they are testing is the evidence field, not the reason.
KILL_REASON = "REASON: the waiver path reverts before the check, pinned by test_B1_refuted"


class Base(unittest.TestCase):
    def setUp(self):
        self.eng = Path(tempfile.mkdtemp())
        (self.eng / "00-triage" / "potential-risks").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audits").mkdir(parents=True)
        (self.eng / "00-triage" / "prior-audits" / "r.pdf").write_bytes(b"%PDF-1.4")
        (self.eng / "00-triage" / "potential-risks" / "EX-potential-risks.txt").write_text(PRIOR_ART)
        (self.eng / "ledger").mkdir()
        self.ledger = self.eng / "ledger" / "ledger.md"

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def write(self, content):
        self.ledger.write_text(content)

    def check(self, content):
        return evaluate(self.ledger, content)

    def g1ok(self, name):
        """A dedup sidecar that satisfies G1, so G2 tests isolate G2."""
        d = self.eng / "ledger" / "dedup"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.md").write_text(
            "searched:\n  - 00-triage/potential-risks/EX-potential-risks.txt\n"
            "terms:\n  - a\n  - b\n  - c\nresult: NO-MATCH\n")
        return f"DEDUP: ledger/dedup/{name}.md"


class TestG3(Base):
    def test_vanished_row_blocked(self):
        self.write("| **A-1** | x | `UNTESTED` |\n| **A-2** | y | `UNTESTED` |\n")
        errs = self.check("| **A-1** | x | `UNTESTED` |\n")
        self.assertTrue(any("A-2" in e and "G3" in e for e in errs), errs)

    def test_merged_into_allowed(self):
        self.write("| **A-1** | x | `UNTESTED` |\n| **A-2** | y | `UNTESTED` |\n")
        errs = self.check("| **A-1** | x | `UNTESTED` |\n<!-- A-2 MERGED-INTO: A-1 -->\n")
        self.assertEqual([e for e in errs if "G3" in e], [], errs)

    def test_explicit_override_allowed(self):
        self.write("| **A-1** | x | `UNTESTED` |\n| **A-2** | y | `UNTESTED` |\n")
        errs = self.check("| **A-1** | x | `UNTESTED` |\nLEDGER-DELETE-APPROVED: duplicate\n")
        self.assertEqual([e for e in errs if "G3" in e], [], errs)


class TestG1(Base):
    ROW = ("| **T-3** | `setAttributeMetadata` applies no check to the target did; "
           "every control check in `checkEligibility` targets the accreditor | {st} | {extra} |\n")

    def sidecar(self, name="T-3", **kw):
        """Write a per-row dedup sidecar and return the row pointer text."""
        d = self.eng / "ledger" / "dedup"
        d.mkdir(parents=True, exist_ok=True)
        lines = []
        for k, v in kw.items():
            if k == "quote":
                lines.append("quote: |")
                lines += [f"  {ln}" for ln in str(v).splitlines()]
            elif isinstance(v, list):
                lines.append(f"{k}:")
                lines += [f"  - {x}" for x in v]
            else:
                lines.append(f"{k}: {v}")
        (d / f"{name}.md").write_text("\n".join(lines) + "\n")
        return f"DEDUP: ledger/dedup/{name}.md"

    def promote(self, extra=""):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        return self.check(self.ROW.format(st="`TIER-1`", extra=extra))

    def test_no_dedup_block(self):
        self.assertTrue(any("no DEDUP" in e for e in self.promote()), "must require DEDUP")

    def test_nonexistent_searched_file(self):
        e = self.promote(self.sidecar(searched=["00-triage/potential-risks/nope.txt"],
                                      terms=["a", "b", "c"], result="NO-MATCH"))
        self.assertTrue(any("does not exist" in x for x in e), e)

    def test_digest_alone_rejected(self):
        (self.eng / "00-triage" / "digest.md").write_text("summary")
        e = self.promote(self.sidecar(searched=["00-triage/digest.md"],
                                      terms=["a", "b", "c"], result="NO-MATCH"))
        self.assertTrue(any("potential-risks" in x for x in e), e)

    def test_paraphrased_quote_rejected(self):
        e = self.promote(self.sidecar(searched=["00-triage/potential-risks/EX-potential-risks.txt"],
                                      terms=["a", "b", "c"], result="MATCH",
                                      quote="the report broadly describes unconsented entries in general"))
        self.assertTrue(any("EXACT substring" in x for x in e), e)

    def test_exact_quote_passes(self):
        e = self.promote(self.sidecar(searched=["00-triage/potential-risks/EX-potential-risks.txt"],
                                      terms=["a", "b", "c"], result="MATCH", quote=EXACT))
        self.assertEqual([x for x in e if "G1" in x], [], e)

    def test_ENGAGEMENT3_REGRESSION_identifier_crosscheck(self):
        """The real failure: row declared novel; its identifier is all over the prior art."""
        e = self.promote(self.sidecar(searched=["00-triage/potential-risks/EX-potential-risks.txt"],
                                      terms=["consent", "waiver", "accreditation"], result="NO-MATCH"))
        self.assertTrue(any("setAttributeMetadata" in x and "NO-MATCH" in x for x in e),
                        f"identifier cross-check must fire: {e}")

    def test_single_shared_identifier_does_NOT_fire(self):
        """Noise control: one common identifier must not block, or the guard gets disabled."""
        self.write("| **T-9** | uses checkEligibility | `UNTESTED` |\n")
        ptr = self.sidecar("T-9", searched=["00-triage/potential-risks/EX-potential-risks.txt"],
                           terms=["a", "b", "c"], result="NO-MATCH")
        e = self.check(f"| **T-9** | uses checkEligibility | `TIER-1` | {ptr} |\n")
        self.assertEqual([x for x in e if "co-occur" in x], [], f"must stay silent: {e}")

    def test_missing_sidecar_blocks(self):
        e = self.promote("DEDUP: ledger/dedup/nope.md")
        self.assertTrue(any("sidecar does not exist" in x for x in e), e)

    def test_multiline_wrapped_quote_passes(self):
        """The whole point of the sidecar: a verbatim quote spanning wrapped lines.

        pdftotext hard-wraps, so an honest copy-paste of a real passage arrives with
        line breaks in it. Inline-on-one-row this was not expressible at all.
        """
        wrapped = ("Cross-hierarchy accreditation of any DID via the new-attribute waiver:\n"
                   "checkEligibility skips\n"
                   "  the trust-chain membership check whenever the target attribute does not yet exist")
        e = self.promote(self.sidecar(
            searched=["00-triage/potential-risks/EX-potential-risks.txt"],
            terms=["waiver", "consent", "accreditation"], result="MATCH", quote=wrapped))
        self.assertEqual([x for x in e if "G1" in x], [], f"wrapped verbatim quote must pass: {e}")

    def test_missing_extracts_blocks(self):
        for f in (self.eng / "00-triage" / "potential-risks").glob("*.txt"):
            f.unlink()
        self.assertTrue(any("no verbatim extracts" in x for x in self.promote()))


class TestTier1(Base):
    """The pre-spend waypoint: dedup is owed BEFORE the harness hours, not after."""

    # deliberately free of prior-art identifiers, so these tests isolate the waypoint
    ROW = "| **T-3** | unrelated rounding drift in the fee accrual path | {st} | {extra} |\n"

    def test_untested_to_confirmed_is_blocked(self):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        e = self.check(self.ROW.format(st="`CONFIRMED`", extra=""))
        self.assertTrue(any("skips TIER-1" in x for x in e), e)

    def test_untested_to_refuted_is_blocked(self):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        e = self.check(self.ROW.format(st="`REFUTED`", extra=""))
        self.assertTrue(any("skips TIER-1" in x for x in e), e)

    def test_g1_fires_on_entering_tier1(self):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        e = self.check(self.ROW.format(st="`TIER-1`", extra=""))
        self.assertTrue(any("no DEDUP" in x for x in e), e)

    def test_tier1_dedup_is_not_recharged_on_the_way_to_confirmed(self):
        """G1 is paid once at TIER-1. G10 still asks CONFIRMED for its PoC.

        Renamed 2026-08-20: this used to assert the onward promotion was *free*, which was
        true only while nothing was required of CONFIRMED. G10 closed that; what must stay
        true is narrower -- the DEDUP obligation is not charged twice.
        """
        ptr = self.g1ok("T-3")
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        self.assertEqual(self.check(self.ROW.format(st="`TIER-1`", extra=ptr)), [])

        self.write(self.ROW.format(st="`TIER-1`", extra=ptr))
        errs = self.check(self.ROW.format(st="`CONFIRMED`", extra=ptr))
        self.assertFalse([e for e in errs if e.startswith("G1 [")], "dedup must not be re-charged")
        self.assertTrue([e for e in errs if e.startswith("G10")], "CONFIRMED must cite a PoC")

        poc = self.eng / "poc"; poc.mkdir(exist_ok=True)
        (poc / "T3.t.sol").write_text("contract T { function test_T3() public {} }")
        self.assertEqual(
            self.check(self.ROW.format(st="`CONFIRMED`",
                                       extra=ptr + " EVIDENCE: poc/T3.t.sol::test_T3")), [])

    def test_blocked_needs_no_tier1(self):
        """No spend happened, so no dedup is owed."""
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        for st in ("`BLOCKED`", "`BLOCKED-OUT-OF-HARNESS`"):
            self.assertEqual(self.check(self.ROW.format(st=st, extra="")), [], st)


class TestG1b(Base):
    def poc_write(self, name="poc/x.t.sol"):
        from ledger_guard import evaluate as ev
        return ev(self.eng / name, "contract T {}")

    def test_harness_before_any_dedup_blocked(self):
        self.write("| **A-1** | thing | `UNTESTED` |\n")
        self.assertTrue(any("no row is at TIER-1" in x for x in self.poc_write()))

    def test_harness_allowed_once_a_row_is_tier1(self):
        self.write(f"| **A-1** | thing | `TIER-1` | {self.g1ok('A-1')} |\n")
        self.assertEqual(self.poc_write(), [])

    def test_non_poc_file_unaffected(self):
        self.write("| **A-1** | thing | `UNTESTED` |\n")
        from ledger_guard import evaluate as ev
        self.assertEqual(ev(self.eng / "notes/scratch.md", "hello"), [])


class TestG2(Base):
    def refute(self, extra=""):
        self.write(f"| **B-1** | thing | `TIER-1` | {extra} |\n")
        return self.check(f"| **B-1** | thing | `REFUTED` | {extra} |\n")

    def test_prose_kill_blocked(self):
        self.assertTrue(any("never by prose" in e for e in self.refute("clearly safe because the guard holds")))

    def test_nonexistent_evidence_blocked(self):
        e = self.refute(self.g1ok("B-1") + " EVIDENCE: poc/ghost.t.sol")
        self.assertTrue(any("does not resolve" in x for x in e), e)

    def test_real_evidence_passes(self):
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "x.t.sol").write_text(
            "contract T { function test_B1_refuted() public {} }")
        e = self.refute(self.g1ok("B-1") + " EVIDENCE: poc/x.t.sol::test_B1_refuted · "
                        + KILL_REASON)
        self.assertEqual(e, [], e)

    def test_a_new_kill_must_state_its_reason(self):
        """REF-26, at the hand-edit layer, and the same reach as G15 above: this guard judges
        TRANSITIONS, so a row ARRIVING at REFUTED is asked for the argument behind it."""
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "x.t.sol").write_text(
            "contract T { function test_B1_refuted() public {} }")
        e = self.refute(self.g1ok("B-1") + " EVIDENCE: poc/x.t.sol::test_B1_refuted")
        self.assertTrue(any("REFUTED [B-1] needs a --reason" in x for x in e), e)

    def test_a_row_already_refuted_with_no_reason_is_never_re_judged(self):
        """REF-26's half of G15's risk: 237 REFUTED rows on disk carry no reason, and editing
        a ledger that holds one must not refuse the edit -- on an existing file or a new one."""
        row = "| **B-1** | thing | `REFUTED` | EVIDENCE: poc/x.t.sol |\n"
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "x.t.sol").write_text("contract T {}")
        self.write(row)
        self.assertEqual([x for x in self.check(row + "| **B-2** | new | `UNTESTED` | |\n")
                          if "needs a --reason" in x], [])
        fresh = self.eng / "ledger" / "copy.md"
        self.assertEqual([x for x in evaluate(fresh, FORMAT_MARKER + "\n" + row)
                          if "needs a --reason" in x], [])

    def test_a_new_forge_citation_must_name_the_test_function(self):
        """REF-1, at the hand-edit layer. This guard judges TRANSITIONS, so it asks the same
        question of a new promotion as `promote` does -- and stays silent on a row that was
        already REFUTED, which the sibling test below pins."""
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "x.t.sol").write_text(
            "contract T { function test_B1_refuted() public {} }")
        e = self.refute(self.g1ok("B-1") + " EVIDENCE: poc/x.t.sol")
        self.assertTrue(any("G15" in x and "::" in x for x in e), e)

    def test_a_row_already_refuted_is_never_re_judged(self):
        """The main risk: 186 rows on disk are REFUTED citing a bare file. Editing a ledger
        that holds one must not refuse the edit."""
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "x.t.sol").write_text("contract T {}")
        row = "| **B-1** | thing | `REFUTED` | EVIDENCE: poc/x.t.sol |\n"
        self.write(row)
        self.assertEqual([x for x in self.check(row + "| **B-2** | new | `UNTESTED` | |\n")
                          if "G15" in x], [])

    def test_a_row_already_refuted_is_never_re_judged_on_a_NEW_file(self):
        """`old` comes from the file on disk, so a ledger written to a path that does not
        exist yet has no "before" and every row in it reads as a fresh transition. Copying,
        splitting or restoring a board must not re-judge rows closed before the rule."""
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "x.t.sol").write_text("contract T {}")
        fresh = self.eng / "ledger" / "copy.md"
        content = (FORMAT_MARKER +
                   "\n| **B-1** | thing | `REFUTED` | EVIDENCE: poc/x.t.sol |\n")
        self.assertEqual([x for x in evaluate(fresh, content) if "G15" in x], [])

    def test_scope_held_needs_human(self):
        self.write("| **C-1** | thing | `UNTESTED` |\n")
        e = self.check("| **C-1** | thing | `SCOPE-HELD` | |\n")
        self.assertTrue(any("HUMAN" in x for x in e), e)


class TestNeverBlocks(Base):
    def test_row_creation_never_gated(self):
        """Recall is the north star: creating UNTESTED rows must ALWAYS be free."""
        self.write("")
        errs = self.check("| **N-1** | a | `UNTESTED` |\n| **N-2** | b | `UNTESTED` |\n")
        self.assertEqual(errs, [], f"row creation must never block: {errs}")

    def test_untested_to_untested_silent(self):
        self.write("| **N-1** | a | `UNTESTED` |\n")
        self.assertEqual(self.check("| **N-1** | a rewritten | `UNTESTED` |\n"), [])

    def test_non_ledger_file_silent(self):
        p = self.eng / "notes.md"
        self.assertEqual(evaluate(p, "anything at all"), [])


class TestG13FiledVsDrafted(unittest.TestCase):
    """O-9. `SUBMITTED` meant 'a draft exists' to some readers and 'we filed it' to others, and
    that ambiguity made two documents overstate our engagement 2 filing history four-fold."""

    def g13(self, row):
        return ledger_guard.check_g13("H1", row)

    def test_submitted_as_a_status_cell_is_refused(self):
        errs = self.g13("| H1 | some hypothesis | SUBMITTED | evidence |")
        self.assertEqual(1, len(errs))
        self.assertIn("not a status", errs[0])

    def test_a_submitted_variant_is_also_refused(self):
        self.assertTrue(self.g13("| H1 | x | SUBMITTED-REJECTED | y |"))

    def test_the_word_in_PROSE_is_left_alone(self):
        """G0d's rule: read the cell, never the line. A row may say it was submitted to the
        sponsor without that being its status, and firing there would make this noisy."""
        self.assertEqual([], self.g13(
            "| H1 | the sponsor was submitted a courtesy note | CONFIRMED | poc/H1.t.sol |"))

    def test_filed_without_a_url_is_refused(self):
        errs = self.g13("| H1 | x | CONFIRMED | FILED: yes, last week |")
        self.assertEqual(1, len(errs))
        self.assertIn("no platform URL", errs[0])

    def test_filed_with_a_url_passes(self):
        self.assertEqual([], self.g13(
            "| H1 | x | CONFIRMED | FILED: https://github.com/org/repo/issues/2 |"))

    def test_drafted_needs_no_url(self):
        """A draft is a local artifact; only a FILING is proved by a platform link."""
        self.assertEqual([], self.g13(
            "| H1 | x | CONFIRMED | DRAFTED: submissions/H1-body.md |"))

    def test_filing_is_an_attribute_not_a_status(self):
        """FILED must never enter STATUSES: the taxonomy is epistemic, and putting an ACTION in
        it is the exact defect SUBMITTED had — one field carrying two axes."""
        self.assertNotIn("FILED", ledger_guard.STATUSES)
        self.assertNotIn("DRAFTED", ledger_guard.STATUSES)
        self.assertNotIn("SUBMITTED", ledger_guard.STATUSES)

    def test_a_clean_row_is_silent(self):
        self.assertEqual([], self.g13("| H1 | x | UNTESTED | — |"))


class TestHookWiring(unittest.TestCase):
    """The guards are only real if the hook can find them.

    Regression: the frontmatter used ${CLAUDE_SKILL_DIR}, which Claude Code substitutes into
    SKILL.md *content* but NOT into a hook command. It expanded to empty, so the script was
    never executed and every Write/Edit died on a file-not-found instead. The guard logic was
    fine the whole time; the wiring was not. Blocked-by-crash looks like enforcement and is not.
    """

    BENIGN = '{"tool_name":"Write","tool_input":{"file_path":"/tmp/not-a-ledger.txt","content":"x"}}'

    def hook_command(self):
        import yaml
        raw = (Path(__file__).parents[2] / "skill" / "SKILL.md").read_text().split("---\n")[1]
        fm = yaml.safe_load(raw)
        return fm["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    def run_hook(self, payload, env=None):
        """Run the literal frontmatter command.

        HOME defaults to the checkout's PARENT because the command resolves the guard as
        `$HOME/audit-toolkit/...`. That is a deliberate deployment assumption -- the register
        explains why $CLAUDE_PROJECT_DIR was rejected (it resolves to wherever the session
        started, usually ~/engagements/<target>). Pinning HOME here tests the command's own
        logic instead of whichever machine happens to run it: these two tests passed locally
        only because the repo really does live at ~/audit-toolkit, and CI caught that on its
        first run. Tests that override HOME (the fail-closed case) still do.
        """
        import os, subprocess, tempfile
        # The frontmatter hard-codes $HOME/audit-toolkit/. Rather than require that THIS
        # checkout is literally named "audit-toolkit" -- which made these three tests fail in
        # every worktree, and CLAUDE.md now directs all feature work into worktrees -- build a
        # temporary HOME holding an `audit-toolkit` symlink to wherever this checkout lives.
        # The hard-coded path is still what gets exercised; only the harness stops caring what
        # the directory is called.
        home = Path(tempfile.mkdtemp())
        link = home / "audit-toolkit"
        if not link.exists():
            link.symlink_to(TOOLKIT_ROOT)
        return subprocess.run(["sh", "-c", self.hook_command()], input=payload, text=True,
                              capture_output=True,
                              env={**os.environ, "HOME": str(home), **(env or {})})

    def test_the_command_resolves_relative_to_HOME(self):
        """Pins the assumption the two tests below rely on, so a breach names itself."""
        self.assertIn("$HOME/audit-toolkit/", self.hook_command())
        # Deliberately NOT asserting TOOLKIT_ROOT.name == "audit-toolkit". That coupled the
        # suite to one directory name and produced three failures in every worktree, which is
        # indistinguishable from real breakage. run_hook() supplies the path instead.
        self.assertTrue((TOOLKIT_ROOT / "tooling/guards/ledger_guard.py").is_file(),
                        "the guard must exist wherever this checkout lives")

    def test_resolves_and_stays_silent_on_an_unrelated_write(self):
        r = self.run_hook(self.BENIGN)
        self.assertEqual(r.returncode, 0, f"hook did not resolve: {r.stderr}")
        self.assertEqual(r.stderr, "", "a non-ledger write must be silent")

    def test_blocks_the_illegal_promotion_through_the_real_command(self):
        import json, tempfile
        eng = Path(tempfile.mkdtemp())
        (eng / "ledger").mkdir()
        (eng / "00-triage").mkdir()   # anchors engagement_root; without it no guard runs
        led = eng / "ledger" / "ledger.md"
        row = "| **HT-1** | fee accrual rounds down | `%s` |"
        led.write_text(row % "UNTESTED")
        r = self.run_hook(json.dumps({"tool_name": "Edit", "tool_input": {
            "file_path": str(led), "old_string": row % "UNTESTED",
            "new_string": row % "CONFIRMED"}}))
        shutil.rmtree(eng, ignore_errors=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("skips TIER-1", r.stderr)

    def test_missing_script_fails_closed_and_says_so(self):
        r = self.run_hook(self.BENIGN, env={"HOME": "/nonexistent"})
        self.assertEqual(r.returncode, 2, "a missing guard must never fail open")
        self.assertIn("MISCONFIGURED", r.stderr)


class TestRowParsing(unittest.TestCase):
    """ROW_RE must match the id styles real ledgers actually use.

    The hyphen was mandatory until 2026-08-20, so `H1` -- the style this repo's own
    templates/ledger.template.md emits -- parsed as zero rows. Zero rows means the
    guard enforces nothing AND says nothing, which is the silent-failure shape the
    whole register exists to remove.
    """

    def ids(self, *lines):
        return set(parse_rows("\n".join(lines)))

    def test_hyphenless_id_from_the_repo_template(self):
        self.assertEqual(self.ids("| H1 | a | `UNTESTED` |"), {"H1"})

    def test_multidigit_hyphenless(self):
        self.assertEqual(self.ids("| H12 | a | `UNTESTED` |"), {"H12"})

    def test_hyphenated_styles_still_parse(self):
        self.assertEqual(
            self.ids("| H-01 | a | `UNTESTED` |",
                     "| AB-1 | b | `UNTESTED` |",
                     "| **HT-80** | c | `UNTESTED` |"),
            {"H-01", "AB-1", "HT-80"})

    def test_letter_suffixed_id_parses(self):
        """engagement 6 uses H-01b for a split hypothesis; it was invisible before."""
        self.assertEqual(self.ids("| H-01b | a | `UNTESTED` |"), {"H-01b"})

    def test_header_cells_are_not_rows(self):
        """Requiring >=1 digit is what stops header/label cells parsing as ids."""
        self.assertEqual(
            self.ids("| id | hypothesis | status |",
                     "| ID | File | notes |",
                     "| contract | subsystem | status |",
                     "| File | ID | label |",
                     "|----|----|----|"),
            set())

    def test_id_must_be_in_the_first_cell(self):
        """Unanchored search matched ids buried mid-row (a spurious H8-04 on engagement 8)."""
        self.assertEqual(self.ids("| some prose | see H8-04 for detail | `UNTESTED` |"), set())

    def test_date_first_cell_is_not_a_row(self):
        self.assertEqual(self.ids("| 2026-08-19 | patch landed | n/a |"), set())


class TestG0(unittest.TestCase):
    """An unrooted ledger must fail closed, not pass silently (hooktest case 17)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "ledger").mkdir()
        self.ledger = self.tmp / "ledger" / "ledger.md"
        self.ledger.write_text(FORMAT_MARKER + "\n")   # exists: these model edits, not creation
        self.rows = FORMAT_MARKER + "\n| H-01 | fee accrual rounds down | `CONFIRMED` |"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unrooted_ledger_with_rows_is_blocked(self):
        errs = evaluate(self.ledger, self.rows)
        self.assertTrue(errs, "an unrooted ledger must never pass silently")
        self.assertIn("no engagement root", errs[0])

    def test_creating_the_root_brings_it_under_guard(self):
        (self.tmp / "00-triage").mkdir()
        errs = evaluate(self.ledger, self.rows)
        self.assertFalse(any("no engagement root" in e for e in errs))

    def test_unrooted_file_with_no_rows_stays_silent(self):
        """Firing on any .md with 'ledger' in its name would be pure noise."""
        self.assertEqual(evaluate(self.ledger, "# notes\nno table here\n"), [])

    def test_toolkit_repo_files_are_exempt(self):
        """docs/, templates/ and examples/ hold ledger-shaped docs, not engagements."""
        for rel in ("docs/hypothesis-ledger.md",
                    "templates/ledger.template.md",
                    "examples/worked-example/ledger.md"):
            f = TOOLKIT_ROOT / rel
            self.assertEqual(evaluate(f, self.rows), [], f"{rel} must not be gated")


class TestG0bFormat(unittest.TestCase):
    """A ledger that is not a table is invisible to every guard -- say so (G0b).

    Both shapes below are real: engagement 9 writes hypotheses as `### R-1` headings,
    engagement 7 as `- **L-C1 ...**` bullets. Each parsed zero rows and was
    silently exempt from every rule.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "00-triage").mkdir()
        (self.tmp / "ledger").mkdir()
        self.ledger = self.tmp / "ledger" / "ledger.md"
        self.ledger.write_text(FORMAT_MARKER + "\n")   # exists: these model edits, not creation

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_heading_format_is_flagged(self):
        errs = evaluate(self.ledger, "## REFUTED\n### R-1 - front-run\n### R-2 - grace period\n")
        self.assertTrue(any(e.startswith("G0b") for e in errs), errs)

    def test_bullet_format_is_flagged(self):
        errs = evaluate(self.ledger,
                        "## LEDGER\n- **L-C1 [conservation]** two events\n"
                        "- **L-D1 [domain sep]** replay\n")
        self.assertTrue(any(e.startswith("G0b") for e in errs), errs)

    def test_table_format_is_silent(self):
        errs = evaluate(self.ledger, "| H-01 | a | `UNTESTED` |\n| H-02 | b | `UNTESTED` |\n")
        self.assertFalse(any(e.startswith("G0b") for e in errs), errs)

    def test_a_new_ledger_with_no_hypotheses_is_silent(self):
        """Row CREATION is never gated -- a header block alone must not trip this."""
        errs = evaluate(self.ledger,
                        "# Hypothesis Ledger\nStatus taxonomy: UNTESTED -> CONFIRMED | REFUTED\n"
                        "- **Scope commit:** abc123\n")
        self.assertEqual(errs, [])

    def test_one_offtable_id_is_below_threshold(self):
        """A single id in prose is not evidence of a wrong-format ledger."""
        errs = evaluate(self.ledger, "## Notes\n### R-1 - one stray heading\n")
        self.assertEqual(errs, [])

    def test_toolkit_docs_are_exempt(self):
        errs = evaluate(TOOLKIT_ROOT / "docs/hypothesis-ledger.md",
                        "### R-1 - x\n### R-2 - y\n")
        self.assertEqual(errs, [])


class TestG0cNewLedger(unittest.TestCase):
    """A NEW ledger must declare its format. G0b detects shapes we have seen; this
    catches the one we have not, because a declaration cannot be out-run by a novel format."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "00-triage").mkdir()
        (self.tmp / "ledger").mkdir()
        self.ledger = self.tmp / "ledger" / "ledger.md"
        self.body = "| H-01 | fee accrual rounds down | `UNTESTED` |\n"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_ledger_without_the_marker_is_blocked(self):
        errs = evaluate(self.ledger, self.body)
        self.assertTrue(any(e.startswith("G0c") for e in errs), errs)

    def test_new_ledger_with_the_marker_passes(self):
        self.assertEqual(evaluate(self.ledger, FORMAT_MARKER + "\n" + self.body), [])

    def test_existing_ledger_without_the_marker_is_grandfathered(self):
        """Requiring it everywhere would block five engagements on disk for no gain."""
        self.ledger.write_text(self.body)
        errs = evaluate(self.ledger, self.body + "| H-02 | queue starvation | `UNTESTED` |\n")
        self.assertFalse(any(e.startswith("G0c") for e in errs), errs)

    def test_the_shipped_template_satisfies_it(self):
        """Whatever the guard demands, the template must already provide."""
        tpl = (TOOLKIT_ROOT / "templates/ledger.template.md").read_text()
        self.assertIn(FORMAT_MARKER, tpl)
        self.assertEqual(evaluate(self.ledger, tpl), [])

    def test_row_creation_is_still_never_gated(self):
        """G0c gates FILE creation only -- adding rows to a declared ledger stays free."""
        self.ledger.write_text(FORMAT_MARKER + "\n")
        many = FORMAT_MARKER + "\n" + "".join(
            f"| H-{i:02d} | hypothesis {i} | `UNTESTED` |\n" for i in range(1, 20))
        self.assertEqual(evaluate(self.ledger, many), [])


class TestStatusRequiredForRows(unittest.TestCase):
    """A line is a ledger row only with an id AND a status -- and why that matters.

    Ledgers carry other tables (hunter roster, status summary, dedup matrix) whose first
    cell also looks like an id. Counting those as rows gave engagement 8 a healthy row
    count that SUPPRESSED the wrong-format detector, while its real hypotheses sat in
    `## C1` headings no guard could read.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "00-triage").mkdir()
        (self.tmp / "ledger").mkdir()
        self.ledger = self.tmp / "ledger" / "ledger.md"
        self.ledger.write_text(FORMAT_MARKER + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    ROSTER = ("| hunter | frame | rows |\n"
              "| H1 | territory: rewards.rs arithmetic | 9 |\n"
              "| H2 | territory: epoch lifecycle | 20 |\n")

    def test_roster_rows_are_not_ledger_rows(self):
        self.assertEqual(parse_rows(self.ROSTER), {})
        self.assertEqual(set(parse_row_lines(self.ROSTER)), {"H1", "H2"})

    def test_a_row_needs_both_an_id_and_a_status(self):
        self.assertEqual(set(parse_rows("| H-01 | a | `UNTESTED` |")), {"H-01"})
        self.assertEqual(parse_rows("| H-01 | a | no status here |"), {})

    def test_statusless_table_is_flagged(self):
        errs = evaluate(self.ledger, FORMAT_MARKER + "\n" + self.ROSTER)
        self.assertTrue(any("NONE carries" in e for e in errs), errs)

    def test_ENGAGEMENT8_REGRESSION_one_real_row_does_not_suppress_the_detector(self):
        """1 table row + 14 heading hypotheses must still be caught."""
        content = (FORMAT_MARKER + "\n" + self.ROSTER
                   + "| H8-04 | multi-epoch race | `UNTESTED` |\n"
                   + "".join(f"## C{i} - hypothesis {i}\n" for i in range(1, 9)))
        errs = evaluate(self.ledger, content)
        self.assertTrue(any("headings or bullets" in e for e in errs), errs)

    def test_a_healthy_ledger_with_an_appendix_stays_silent(self):
        """engagement 7 keeps 8 bullet ids in a verbatim appendix under 15 real rows."""
        content = (FORMAT_MARKER + "\n"
                   + "".join(f"| R-{i:02d} | hypothesis {i} | `UNTESTED` |\n" for i in range(1, 16))
                   + "# Prior write-up\n"
                   + "".join(f"- **L-C{i} [class]** note {i}\n" for i in range(1, 9)))
        self.assertEqual(evaluate(self.ledger, content), [])


class TestLedgerDiscovery(unittest.TestCase):
    """G1b must find the ledger whatever layout the engagement uses.

    It used to glob `<eng>/ledger/*.md` only. engagement 6 and engagement 8 keep the ledger
    flat at `<eng>/ledger.md`, so it found none, concluded no row had ever reached TIER-1, and
    blocked every poc/ file permanently -- the noisy-gate failure, and a disagreement with
    is_ledger(), which accepts both layouts.
    """

    def setUp(self):
        self.eng = Path(tempfile.mkdtemp())
        (self.eng / "00-triage").mkdir()
        (self.eng / "poc").mkdir()

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    ROW = "| H-01 | fee accrual | `{}` |\n"

    def test_flat_layout_ledger_is_found(self):
        (self.eng / "ledger.md").write_text(self.ROW.format("CONFIRMED"))
        self.assertEqual([p.name for p in engagement_ledgers(self.eng)], ["ledger.md"])

    def test_nested_layout_ledger_is_found(self):
        (self.eng / "ledger").mkdir()
        (self.eng / "ledger" / "hypothesis-ledger.md").write_text(self.ROW.format("CONFIRMED"))
        self.assertEqual([p.name for p in engagement_ledgers(self.eng)],
                         ["hypothesis-ledger.md"])

    def test_ENGAGEMENT6_REGRESSION_g1b_quiet_on_a_flat_layout_with_spend(self):
        (self.eng / "ledger.md").write_text(self.ROW.format("CONFIRMED"))
        self.assertEqual(evaluate(self.eng / "poc" / "New.t.sol", "contract X {}"), [])

    def test_g1b_still_fires_when_nothing_is_deduped(self):
        (self.eng / "ledger.md").write_text(self.ROW.format("UNTESTED"))
        errs = evaluate(self.eng / "poc" / "New.t.sol", "contract X {}")
        self.assertTrue(any("G1b" in e for e in errs), errs)

    def test_build_trees_are_not_walked(self):
        """A real checkout has out/, cache/, lib/ -- walking them is waste, not discovery."""
        (self.eng / "lib").mkdir()
        (self.eng / "lib" / "ledger.md").write_text(self.ROW.format("CONFIRMED"))
        self.assertEqual(engagement_ledgers(self.eng), [])


class TestEvidenceResolver(unittest.TestCase):
    """Cited evidence must resolve the way real ledgers actually write it.

    Measured 2026-08-20 across every row at CONFIRMED or REFUTED on disk: 1 of 16 resolved
    under a literal-path-only rule, 4 by basename. Three of engagement 6's five CONFIRMED
    rows name `PoC_H01_FeeBypass.t.sol` with no path while the file sits in `test/`.
    """

    def setUp(self):
        self.eng = Path(tempfile.mkdtemp())
        (self.eng / "00-triage").mkdir()
        (self.eng / "test").mkdir()
        (self.eng / "poc").mkdir()
        (self.eng / "test" / "PoC_H01_FeeBypass.t.sol").write_text(
            "contract T { function test_H01_refuted() public {} }")

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def test_ENGAGEMENT6_REGRESSION_bare_basename_resolves(self):
        self.assertIsNotNone(resolve_artifact("PoC_H01_FeeBypass.t.sol", self.eng))

    def test_repo_relative_path_resolves(self):
        self.assertIsNotNone(resolve_artifact("test/PoC_H01_FeeBypass.t.sol", self.eng))

    def test_a_name_that_does_not_exist_still_fails(self):
        self.assertIsNone(resolve_artifact("PoC_Nope.t.sol", self.eng))

    def test_build_trees_are_not_searched(self):
        """A stale copy under out/ or lib/ must not satisfy the citation."""
        (self.eng / "out").mkdir()
        (self.eng / "out" / "Ghost.t.sol").write_text("x")
        self.assertIsNone(resolve_artifact("Ghost.t.sol", self.eng))

    def test_a_path_function_citation_resolves_to_the_path(self):
        """REF-1. `path::function` is the citation format from 2026-09-29 on. Every reader
        of an evidence value must resolve the path part, so a correct citation can never be
        refused for its form."""
        for tok in ("PoC_H01_FeeBypass.t.sol::test_H01_refuted",
                    "test/PoC_H01_FeeBypass.t.sol::test_H01_refuted"):
            with self.subTest(tok=tok):
                self.assertIsNotNone(resolve_artifact(tok, self.eng))

    def test_a_path_function_citation_on_a_missing_file_still_fails(self):
        self.assertIsNone(resolve_artifact("PoC_Nope.t.sol::test_nope", self.eng))

    def test_g2_accepts_a_bare_basename_end_to_end(self):
        (self.eng / "ledger").mkdir()
        led = self.eng / "ledger" / "ledger.md"
        led.write_text(FORMAT_MARKER + "\n| H-01 | fee bypass | `TIER-1` |\n")
        errs = evaluate(led, FORMAT_MARKER + "\n| H-01 | fee bypass | `REFUTED` "
                        "EVIDENCE: PoC_H01_FeeBypass.t.sol::test_H01_refuted · "
                        + KILL_REASON + " |\n")
        self.assertEqual(errs, [], errs)


class TestG10(Base):
    """A CONFIRMED row must cite a PoC that exists -- the missing half of G2.

    G2 protects kills, G10 protects claims. Its evidence is REF-8: an invite-only review
    platform's submission form marks Proof of Concept "(optional)", so "no PoC => no submission"
    -- which has never broken, because HackenProof returns an error -- has nothing enforcing it
    there.
    """

    ROW = "| G-1 | fee accrual rounds down | {st} {extra}|"

    def test_confirmed_with_no_evidence_is_blocked(self):
        self.write(self.ROW.format(st="`TIER-1`", extra=""))
        errs = self.check(self.ROW.format(st="`CONFIRMED`", extra=""))
        self.assertTrue(any(e.startswith("G10") for e in errs), errs)

    def test_confirmed_citing_a_missing_file_is_blocked(self):
        self.write(self.ROW.format(st="`TIER-1`", extra=""))
        errs = self.check(self.ROW.format(st="`CONFIRMED`", extra="EVIDENCE: poc/Nope.t.sol "))
        self.assertTrue(any("does not resolve" in e for e in errs), errs)

    def test_a_back_reference_is_not_a_citation(self):
        """Two engagement 6 rows say 'same file'; that names nothing the guard can check."""
        self.write(self.ROW.format(st="`TIER-1`", extra=""))
        errs = self.check(self.ROW.format(st="`CONFIRMED`", extra="EVIDENCE: same file "))
        self.assertTrue(any(e.startswith("G10") for e in errs), errs)

    def test_confirmed_with_a_real_poc_passes(self):
        poc = self.eng / "poc"; poc.mkdir(exist_ok=True)
        (poc / "G1.t.sol").write_text("contract T { function test_G1() public {} }")
        self.write(self.ROW.format(st="`TIER-1`", extra=""))
        self.assertEqual(
            self.check(self.ROW.format(st="`CONFIRMED`",
                                       extra="EVIDENCE: poc/G1.t.sol::test_G1 ")), [])

    def test_untested_row_creation_is_still_free(self):
        """The rule protects the WIDE SWEEP: generating UNTESTED rows must never block."""
        self.write("| Z-9 | unrelated | `UNTESTED` |")
        self.assertEqual(
            self.check("| Z-9 | unrelated | `UNTESTED` |\n| G-2 | new hypothesis | `UNTESTED` |"), [])

    def test_a_row_asserted_straight_into_confirmed_is_gated(self):
        """Not a violation of "never gate row creation" -- that rule protects hypothesis
        generation. A row written directly at CONFIRMED is a CLAIM, not a hypothesis, and
        gating it is the point. Matches the pre-existing behaviour for REFUTED."""
        self.write("| Z-9 | unrelated | `UNTESTED` |")
        errs = self.check("| Z-9 | unrelated | `UNTESTED` |\n| G-2 | new | `CONFIRMED` |")
        self.assertTrue(any(e.startswith("G10") for e in errs), errs)


class TestSidecarIsNotALedger(Base):
    """G1 demands `ledger/dedup/<row>.md`; G0c used to refuse to let it be written.

    Found live on an engagement cut from this release, at the first real TIER-1 promotion any
    engagement has attempted. `is_ledger()` accepted every .md under a `ledger/` directory, so the
    sidecar G1 asks for was classified as a new ledger with no format marker and blocked.
    The two guards deadlocked: no row could ever reach TIER-1.

    The suite missed it because the fixtures write sidecars straight to disk, which never
    fires a PreToolUse hook. So this test asserts the CLASSIFIER, not the fixture.
    """

    def test_dedup_sidecar_is_not_classified_as_a_ledger(self):
        self.assertFalse(is_ledger(Path("ledger/dedup/INV-04.md")))
        self.assertFalse(is_ledger(Path("/abs/eng/ledger/dedup/H-002.md")))

    def test_a_real_ledger_still_is_one(self):
        """The fix must not punch a hole in G0b/G0c for actual ledgers."""
        self.assertTrue(is_ledger(Path("ledger/hypothesis-ledger.md")))
        self.assertTrue(is_ledger(Path("ledger.md")))
        self.assertTrue(is_ledger(Path("eng/ledger/merged-tier1.md")))

    def test_writing_a_sidecar_is_not_blocked_by_g0c(self):
        """The end-to-end shape of the deadlock: creating the file G1 named must pass."""
        sc = self.eng / "ledger" / "dedup" / "INV-04.md"
        sc.parent.mkdir(parents=True, exist_ok=True)
        errs = evaluate(sc, "searched:\n  - 00-triage/potential-risks/x.txt\n"
                            "terms: [a, b, c]\nresult: NO-MATCH\n")
        self.assertEqual([e for e in errs if e.startswith("G0c")], [], errs)


class TestHeaderIsNotALedger(Base):
    """REF-23's fix composes a human-owned `ledger/HEADER.md` into the render. Same shape
    as the dedup-sidecar deadlock above: `is_ledger()` accepted every .md under `ledger/`,
    so writing that header -- free prose, no table, no format marker -- would have been
    classified as a new ledger with no format declaration and refused by G0c. That would
    block the exact file the REF-23 fix exists to let a human maintain."""

    def test_header_is_not_classified_as_a_ledger(self):
        self.assertFalse(is_ledger(Path("ledger/HEADER.md")))
        self.assertFalse(is_ledger(Path("/abs/eng/ledger/HEADER.md")))

    def test_a_real_ledger_still_is_one(self):
        """The fix must not punch a hole in G0b/G0c for actual ledgers."""
        self.assertTrue(is_ledger(Path("ledger/hypothesis-ledger.md")))
        self.assertTrue(is_ledger(Path("ledger.md")))

    def test_writing_the_header_is_not_blocked_by_g0c(self):
        """The end-to-end shape: creating ledger/HEADER.md with plain prose must pass."""
        hdr = self.eng / "ledger" / "HEADER.md"
        hdr.parent.mkdir(parents=True, exist_ok=True)
        errs = evaluate(hdr, "# Hypothesis Ledger -- Example Protocol\n\n"
                             "- **Impact bar:** theft / permanent lock\n")
        self.assertEqual([e for e in errs if e.startswith("G0c")], [], errs)






class FieldParseWithReason(unittest.TestCase):
    """Regression, 2026-09-10 (engagement 14): a row carrying BOTH a DEDUP and a REASON had the rest of
    the cell swallowed into the sidecar path, so G1 reported a real sidecar as absent.

    REASON is the field BELOW-BAR requires, so this fired on every row that was BELOW-BAR and was
    later promoted with a dedup — i.e. exactly the correction path. `cli.py render` also joins
    inline fields with U+00B7, which was being captured as part of the value.
    """

    ROW = ("| H7 | hyp |  |  | `REFUTED` | EVIDENCE: poc/X.t.sol · "
           "DEDUP: ledger/dedup/e.md · REASON: a long reason with EVIDENCE-ish words |  |")

    def test_dedup_stops_at_reason(self):
        self.assertEqual(ledger_guard.field(self.ROW, "DEDUP"), "ledger/dedup/e.md")

    def test_evidence_does_not_keep_the_separator(self):
        self.assertEqual(ledger_guard.field(self.ROW, "EVIDENCE"), "poc/X.t.sol")

    def test_reason_is_extractable(self):
        self.assertEqual(ledger_guard.field(self.ROW, "REASON"),
                         "a long reason with EVIDENCE-ish words")

    def test_reason_only_row_still_parses(self):
        row = "| H8 | hyp |  |  | `BELOW-BAR` | REASON: bar not cleared, $0 reachable |  |"
        self.assertIsNone(ledger_guard.field(row, "DEDUP"))
        self.assertEqual(ledger_guard.field(row, "REASON"), "bar not cleared, $0 reachable")

    def test_g1_accepts_a_real_sidecar_when_a_reason_follows_it(self):
        """The end-to-end shape: G1 must resolve the sidecar, not complain it is missing."""
        with tempfile.TemporaryDirectory() as d:
            eng = Path(d)
            (eng / "ledger" / "dedup").mkdir(parents=True)
            (eng / "00-triage" / "prior-audits").mkdir(parents=True)
            (eng / "00-triage" / "potential-risks").mkdir(parents=True)
            (eng / "00-triage" / "prior-audits" / "a.txt").write_text("x")
            (eng / "00-triage" / "potential-risks" / "p.txt").write_text("x")
            (eng / "ledger" / "dedup" / "e.md").write_text(
                "searched:\n  - 00-triage/potential-risks/p.txt\n"
                "terms:\n  - one\n  - two\n  - three\nresult: NO-MATCH\n")
            errs = ledger_guard.check_g1("H7", ledger_guard.field(self.ROW, "DEDUP"), self.ROW, eng)
            self.assertEqual(errs, [], f"G1 rejected a valid sidecar: {errs}")

if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPartialVerdict(Base):
    """G1 accepts a third dedup verdict: PARTIAL = root cause matched, impact/consumer did not.

    Added after one engagement, cut from this release. Dozens of rows matched the platform's
    exclusion list and a few were a different animal -- the ROOT CAUSE was published but the
    consumer or the impact was not, so the argument for submitting is a GRADING argument, not a
    DISTINCTNESS one. A single blanket HUMAN: ruling was applied to all of them and silently
    overrode the sidecars that had themselves recorded "this is a Phase-4 call and it belongs to
    the human". Nothing errored.
    """

    ROW = ("| **P-1** | `ragequitLock` hands the aggregate to the emergency checkpoint "
           "| {st} | {extra} |\n")

    def sidecar(self, name="P-1", **kw):
        d = self.eng / "ledger" / "dedup"
        d.mkdir(parents=True, exist_ok=True)
        lines = []
        for k, v in kw.items():
            if k in ("quote", "unmatched"):
                lines.append(f"{k}: |")
                lines += [f"  {ln}" for ln in str(v).splitlines()]
            elif isinstance(v, list):
                lines.append(f"{k}:")
                lines += [f"  - {x}" for x in v]
            else:
                lines.append(f"{k}: {v}")
        (d / f"{name}.md").write_text("\n".join(lines) + "\n")
        return f"DEDUP: ledger/dedup/{name}.md"

    def promote(self, extra=""):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        return self.check(self.ROW.format(st="`TIER-1`", extra=extra))

    def _base(self, **over):
        kw = dict(searched=["00-triage/potential-risks/EX-potential-risks.txt"],
                  terms=["a", "b", "c"], result="PARTIAL",
                  quote=EXACT,
                  unmatched="searched for the two consumers of the deflated denominator and "
                            "found neither in the corpus")
        kw.update(over)
        return kw

    def test_partial_is_a_legal_verdict(self):
        """The whole point: a valid PARTIAL must PASS, not merely produce a nicer error."""
        e = self.promote(self.sidecar(**self._base()))
        self.assertEqual(e, [], f"a well-formed PARTIAL must pass G1, got: {e}")

    def test_partial_without_unmatched_is_blocked(self):
        """Without `unmatched:` PARTIAL degrades into 'probably a duplicate, not sure' --
        which is the confidence grade this verdict exists to not be."""
        kw = self._base(); kw.pop("unmatched")
        e = self.promote(self.sidecar(**kw))
        self.assertTrue(any("requires unmatched" in x for x in e), e)

    def test_partial_with_token_unmatched_is_blocked(self):
        e = self.promote(self.sidecar(**self._base(unmatched="n/a")))
        self.assertTrue(any("requires unmatched" in x for x in e), e)

    def test_partial_still_needs_a_verbatim_quote(self):
        """PARTIAL asserts the root cause DID match, so it owes the same proof MATCH owes."""
        e = self.promote(self.sidecar(**self._base(
            quote="the report broadly describes this mechanism somewhere in general terms")))
        self.assertTrue(any("EXACT substring" in x for x in e), e)

    def test_partial_skips_the_identifier_cross_check(self):
        """On a PARTIAL the identifiers co-occur BY DEFINITION -- that is what PARTIAL asserts.
        Firing the cross-check here would fire on every PARTIAL and get the guard disabled."""
        row = ("| **P-2** | `checkEligibility` and `setAttributeMetadata` both drift "
               "| {st} | {extra} |\n")
        self.write(row.format(st="`UNTESTED`", extra=""))
        e = self.check(row.format(st="`TIER-1`", extra=self.sidecar("P-2", **self._base())))
        self.assertFalse(any("co-occur" in x for x in e),
                         f"cross-check must not fire on PARTIAL: {e}")

    def test_unknown_verdict_still_rejected(self):
        e = self.promote(self.sidecar(**self._base(result="PROBABLY")))
        self.assertTrue(any("must be MATCH, PARTIAL or NO-MATCH" in x for x in e), e)


class TestStatusComesFromTheCell(Base):
    """row_status() must read the STATUS CELL, not the whole line.

    On an engagement cut from this release, a row whose status cell read `REFUTED` carried an
    honest cross-reference in its prose -- "... is still UNTESTED". UNTESTED is first in
    STATUSES, so the row reported UNTESTED. evaluate() then saw old_st == new_st, hit
    `continue`, and returned PASS on a real UNTESTED -> TIER-1 -> REFUTED promotion: no G1,
    no G2. ledger_state_guard imports row_status, so the Stop hook was blind to the same row.
    """

    def test_prose_token_does_not_hijack_the_status(self):
        row = ("| **X-1** | a note saying T1-16 is still UNTESTED | done | `REFUTED` "
               "| EVIDENCE: poc/x.txt |\n")
        self.assertEqual(row_status(row), "REFUTED",
                         "status must come from the cell, not from prose")

    def test_the_transition_is_no_longer_invisible(self):
        """The decisive regression: the promotion must be SEEN, and therefore gated."""
        before = "| **X-1** | plain claim | done | `UNTESTED` | |\n"
        after = ("| **X-1** | a note saying T1-16 is still UNTESTED | done | `CONFIRMED` "
                 "| EVIDENCE: poc/nope.txt |\n")
        self.write(before)
        errs = self.check(after)
        self.assertTrue(errs, "a promotion hidden behind a prose status token must be caught")
        self.assertTrue(any("skips TIER-1" in e for e in errs), errs)

    def test_ambiguous_row_is_reported_even_with_no_transition(self):
        row = ("| **X-1** | a note saying T1-16 is still UNTESTED | done | `REFUTED` "
               "| EVIDENCE: poc/x.txt |\n")
        (self.eng / "poc").mkdir(exist_ok=True)
        (self.eng / "poc" / "x.txt").write_text("PASS")
        self.write(row)
        self.assertTrue(any("G0d" in e for e in self.check(row)),
                        "an ambiguous row must be flagged even when nothing changed")

    def test_a_row_may_repeat_its_own_status_in_prose(self):
        """Narrow on purpose. Firing on a row restating its OWN status would be noise, and a
        noisy gate gets disabled -- the failure the register is most explicit about."""
        row = ("| **X-1** | kept UNTESTED because the precondition is unproven | done "
               "| `UNTESTED` | |\n")
        self.write(row)
        self.assertFalse(any("G0d" in e for e in self.check(row)), self.check(row))

    def test_non_table_text_keeps_the_whole_line_fallback(self):
        self.assertEqual(row_status("### R-6 -- something `CONFIRMED`"), "CONFIRMED")


class TestCrossCheckAnswered(Base):
    """G1's identifier cross-check must be answerable by EVIDENCE, not by writing less.

    On an engagement cut from this release, four fully-evidenced rows sat at UNTESTED
    because the check re-derives identifiers from the row every time and had no way to record
    that the flagged sections had been read. The only way to silence it was to delete function
    names from the row -- degrading the ledger for a green light.
    """

    # Both identifiers appear in PRIOR_ART, so the cross-check fires on this row.
    ROW = ("| **X-9** | `checkEligibility` skips the trust-chain check and "
           "`setAttributeMetadata` pushes a caller-supplied did | {st} | {extra} |\n")

    def sidecar(self, name="X-9", **kw):
        d = self.eng / "ledger" / "dedup"
        d.mkdir(parents=True, exist_ok=True)
        lines = []
        for k, v in kw.items():
            if k == "cross_check_answered":
                lines.append("cross_check_answered:")
                for e in v:
                    lines.append(f"  - identifier: {e[0]}")
                    lines.append(f"    section: {e[1]}")
            elif isinstance(v, list):
                lines.append(f"{k}:")
                lines += [f"  - {x}" for x in v]
            else:
                lines.append(f"{k}: {v}")
        (d / f"{name}.md").write_text("\n".join(lines) + "\n")
        return f"DEDUP: ledger/dedup/{name}.md"

    def promote(self, extra=""):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        return self.check(self.ROW.format(st="`TIER-1`", extra=extra))

    def _kw(self, **over):
        kw = dict(searched=["00-triage/potential-risks/EX-potential-risks.txt"],
                  terms=["a", "b", "c"], result="NO-MATCH")
        kw.update(over)
        return kw

    def test_unanswered_cross_check_still_blocks(self):
        """The engagement 3 catch must keep working when nothing is claimed."""
        e = self.promote(self.sidecar(**self._kw()))
        self.assertTrue(any("co-occur" in x for x in e), e)

    def test_answering_every_flagged_identifier_passes(self):
        e = self.promote(self.sidecar(**self._kw(cross_check_answered=[
            ("checkEligibility", "EX-potential-risks.txt:3"),
            ("setAttributeMetadata", "EX-potential-risks.txt:6")])))
        self.assertEqual(e, [], f"a fully answered cross-check must pass, got: {e}")

    def test_partial_answer_names_what_is_still_missing(self):
        e = self.promote(self.sidecar(**self._kw(cross_check_answered=[
            ("checkEligibility", "EX-potential-risks.txt:3")])))
        self.assertTrue(any("Still unanswered" in x and "setAttributeMetadata" in x for x in e), e)

    def test_a_section_that_names_no_real_file_is_rejected(self):
        """Otherwise the field is the same hand-wave the DEDUP quote rule exists to stop."""
        e = self.promote(self.sidecar(**self._kw(cross_check_answered=[
            ("checkEligibility", "i-read-it-honest:1"),
            ("setAttributeMetadata", "EX-potential-risks.txt:6")])))
        self.assertTrue(any("does not resolve" in x for x in e), e)

    def test_answering_irrelevant_identifiers_does_not_help(self):
        """Coverage is of the FLAGGED set, so a list of unrelated names buys nothing."""
        e = self.promote(self.sidecar(**self._kw(cross_check_answered=[
            ("somethingElse", "EX-potential-risks.txt:1"),
            ("anotherThing", "EX-potential-risks.txt:2")])))
        self.assertTrue(any("Still unanswered" in x for x in e), e)


class TestG11ChannelGuard(unittest.TestCase):
    """G11: once an engagement has an event log, its markdown is a render and may not
    be hand-edited. This is what makes the SKILL.md wiring binding rather than advisory."""

    def setUp(self):
        self.eng = Path(tempfile.mkdtemp(prefix="g11-test-"))
        (self.eng / "00-triage").mkdir(parents=True)
        (self.eng / "ledger").mkdir(parents=True)
        self.led = self.eng / "ledger" / "ledger.md"
        self.body = ("<!-- ledger-format: table-v1 -->\n"
                     "| id | hyp | entry | inv | status |\n|---|---|---|---|---|\n"
                     "| H1 | idea | mint() | cap | UNTESTED |\n")
        self.led.write_text(self.body)

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def migrate(self):
        (self.eng / "ledger" / "events.jsonl").write_text(
            '{"id":"H1","event":"created","status":"UNTESTED","seq":1,"hash":"x","prev":null}\n')

    def test_unmigrated_engagements_are_untouched(self):
        """Silent on the common path. A gate that fires where it does not apply gets
        disabled -- CLAUDE.md constraint 3."""
        errs = ledger_guard.evaluate(self.led, self.body)
        self.assertFalse([e for e in errs if e.startswith("G11")])

    def test_editing_a_cli_managed_ledger_is_blocked(self):
        self.migrate()
        errs = ledger_guard.evaluate(self.led, self.body.replace("UNTESTED", "CONFIRMED"))
        self.assertTrue(errs and errs[0].startswith("G11"), errs)

    def test_even_a_harmless_looking_edit_is_blocked(self):
        """The CHANNEL is wrong, not the content. An edit that changes no status still
        forks the render from the log."""
        self.migrate()
        errs = ledger_guard.evaluate(self.led, self.body + "\n<!-- a note -->\n")
        self.assertTrue(errs and errs[0].startswith("G11"), errs)

    def test_a_pre_migration_ledger_in_the_same_engagement_is_also_blocked(self):
        """engagement 9's dual state: events.jsonl alongside hypothesis-ledger.md. Editing
        the old file is still forking, and the message names the fix (import, then delete)."""
        self.migrate()
        old = self.eng / "ledger" / "hypothesis-ledger.md"
        old.write_text(self.body)
        errs = ledger_guard.evaluate(old, self.body.replace("UNTESTED", "REFUTED"))
        self.assertTrue(errs and errs[0].startswith("G11"), errs)
        self.assertIn("two sources of truth", errs[0])

    def test_the_message_names_the_replacement_command(self):
        """A block is information, not an obstacle -- it must say what to do instead."""
        self.migrate()
        errs = ledger_guard.evaluate(self.led, self.body.replace("UNTESTED", "CONFIRMED"))
        self.assertIn("promote", errs[0])
        self.assertIn("render", errs[0])

    def test_the_cli_render_is_not_blocked_by_g11(self):
        """VERIFIED, NOT ASSUMED. The hook's main() only ever sees Write/Edit payloads
        (file_path + content/new_string). The CLI writes ledger.md from Python inside a
        Bash call, which produces no such payload, so its own renders never reach the
        guard and need no exemption."""
        self.migrate()
        import io, json as _json, contextlib
        # A Bash tool call carries no file_path: main() returns 0 before evaluate() runs.
        payload = _json.dumps({"tool_name": "Bash",
                               "tool_input": {"command": "python3 cli.py render"}})
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            with unittest.mock.patch("sys.stdin", io.StringIO(payload)):
                rc = ledger_guard.main()
        self.assertEqual(0, rc)


class TestG14FindingBodies(Base):
    """G14 (REF-3): a NO-MATCH must be cleared against finding BODIES, not section extracts.

    The failure it catches, measured on disk: engagement 16 rows H7, H8 and H15 declare NO-MATCH on
    `executeBatch` territory having searched only the Notes and Trust Model extracts, while H6's
    own sidecar quotes ChainSecurity finding 7.1, "Reentrancy in Proposal Execution", out of the
    full report text sitting unsearched in the same tree. `potential-risks/` holds SECTIONS --
    extract_prior_art.py stops at the heading "Findings" by design -- so a finding whose title
    names another subsystem cannot match there however carefully it is grepped.
    """

    ROW = "| **X-4** | `settleBatch` double-credits on retry | {st} | {extra} |\n"
    # Three findings, ~1.4KB each: prose per finding, which is what makes it a body.
    REPORT = "".join(
        f"F-2026-100{i} Medium\n\nDescription\n" + ("the reception ack strands deposits. " * 45)
        + "\n\n" for i in range(1, 4))
    # The same three findings as a title list: 12x more ids per byte. This is engagement 14's INDEX.txt,
    # and accepting it as a body would clear the exact dedup the guard exists to stop.
    INDEX = "F-2026-1001 Bridge Deposits\nF-2026-1002 Fee Rounding\nF-2026-1003 Pause Flow\n"

    def sidecar(self, searched, result="NO-MATCH", name="X-4"):
        d = self.eng / "ledger" / "dedup"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.md").write_text(
            "searched:\n" + "".join(f"  - {s}\n" for s in searched)
            + "terms:\n  - a\n  - b\n  - c\n" + f"result: {result}\n"
            + ("quote: the reception ack strands deposits. the reception ack strands deposits.\n"
               if result in ("MATCH", "PARTIAL") else "")
            + ("unmatched: the listed issue covers the single-hop case and never the retry path "
               "that this row asserts\n" if result == "PARTIAL" else ""))
        return f"DEDUP: ledger/dedup/{name}.md"

    def body(self, rel="00-triage/prior-audits-text/hacken.txt", text=None):
        p = self.eng / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text if text is not None else self.REPORT)
        return rel

    def promote(self, extra):
        self.write(self.ROW.format(st="`UNTESTED`", extra=""))
        return [e for e in self.check(self.ROW.format(st="`TIER-1`", extra=extra))
                if e.startswith("G14")]

    SECTION = "00-triage/potential-risks/EX-potential-risks.txt"

    def test_no_match_against_sections_alone_is_blocked(self):
        self.body()
        e = self.promote(self.sidecar([self.SECTION]))
        self.assertTrue(any("FINDING bodies" in x for x in e), e)
        self.assertTrue(any("prior-audits-text/hacken.txt" in x for x in e), e)

    def test_searching_the_body_passes(self):
        rel = self.body()
        self.assertEqual(self.promote(self.sidecar([self.SECTION, rel])), [])

    def test_silent_when_the_corpus_holds_no_bodies(self):
        """Nothing was skipped, so firing would demand a corpus rather than a reading of one."""
        self.assertEqual(self.promote(self.sidecar([self.SECTION])), [])

    def test_match_and_partial_are_not_checked(self):
        """A MATCH or PARTIAL has already engaged the prior art; the risk is a FALSE CLEAR.
        Measured: on all verdicts the fire rate is 7/174 rather than 3/174, and all four extra
        are PARTIALs whose `unmatched:` proves the bodies were read and only `searched:` lagged."""
        for verdict in ("MATCH", "PARTIAL"):
            with self.subTest(verdict=verdict):
                self.body()
                self.assertEqual(self.promote(self.sidecar([self.SECTION], result=verdict)), [])

    def test_a_title_index_is_not_a_body(self):
        """The engagement 14 regression. INDEX.txt names 12 WatchPug issues in 1.8KB; WP-M3.txt spends
        13.5KB on one. Bytes-per-finding is the whole discriminator between them."""
        self.body("00-triage/potential-risks/INDEX.txt", self.INDEX)
        self.assertEqual(self.promote(self.sidecar([self.SECTION])), [])
        # The control: the SAME three ids at body density do fire, so the test is measuring
        # bytes-per-finding and not merely the absence of a fire.
        self.body("00-triage/potential-risks/INDEX.txt", self.REPORT)
        self.assertTrue(self.promote(self.sidecar([self.SECTION])))

    def test_a_single_finding_extract_is_a_body(self):
        """engagement 14's hand-made WP-M3.txt shape: one id, thousands of bytes of description."""
        rel = self.body("00-triage/potential-risks/WP-M3.txt",
                        "[WP‐M3] claimMMRewards unrestricted external call\n\n"
                        + ("the box position is drained to an arbitrary address. " * 60))
        e = self.promote(self.sidecar([self.SECTION]))
        self.assertTrue(any("WP-M3.txt" in x for x in e), e)
        self.assertEqual(self.promote(self.sidecar([self.SECTION, rel])), [])

    def test_only_the_prior_art_corpus_is_asked_about(self):
        """protocol-docs/ can cite a finding id in passing; demanding it be searched for dedup
        is a category error, and a gate that fires wrongly gets disabled."""
        self.body("00-triage/protocol-docs/primer.txt")
        self.assertEqual(self.promote(self.sidecar([self.SECTION])), [])
        # The control: identical bytes under a corpus directory do fire.
        self.body("00-triage/prior-audits/primer.txt")
        self.assertTrue(self.promote(self.sidecar([self.SECTION])))

    def test_no_sidecar_is_g1s_case_not_g14s(self):
        self.body()
        self.assertEqual(self.promote(""), [])

    def test_the_body_cache_is_invalidated_by_an_equal_LENGTH_edit(self):
        """The cache keys on (path, mtime, size), and size alone would not catch this.

        Without the mtime leg a corpus file edited in place keeps its first verdict for the
        life of the process -- which in the Stop guard is the whole session. Pinned with two
        payloads of IDENTICAL length so only the timestamp can distinguish them.
        """
        # Under potential-risks/, so CONTENT decides. A file under prior-audits-text/ is a
        # body by path whatever it holds, and could never flip.
        rel = "00-triage/potential-risks/WP-M3.txt"
        body = self.REPORT
        filler = "x" * len(body)            # same length, no finding ids, not a body
        self.body(rel, body)
        self.assertTrue(self.promote(self.sidecar([self.SECTION])), "control: a body fires")
        p = self.eng / rel
        p.write_text(filler)
        self.assertEqual(len(p.read_text()), len(body), "the payloads must be the same size")
        self.assertEqual(self.promote(self.sidecar([self.SECTION])), [],
                         "a stale cached verdict survived an equal-length edit")


class TestScaffoldIsParsedRootedAndGuarded(unittest.TestCase):
    """The end-to-end check `.github/workflows/tests.yml`'s `scaffold` job runs, mirrored
    here so a regression is caught by the local suite instead of only by CI.

    Found live 2026-09-18: the board-redraw fix (REF-23's sibling defect, "a fresh
    engagement's placeholder row trips a guard on its first render") removed
    `tooling/new-engagement.sh`'s example row, correctly -- but the CI workflow's own
    scaffold check had assumed the scaffold always ships with one, and started failing on
    every push while every local `unittest` suite stayed green, because this check lived
    only in the workflow YAML. Keep the two copies in sync by hand if either ever changes.
    """

    NEW_ENGAGEMENT_SH = TOOLKIT_ROOT / "tooling" / "new-engagement.sh"

    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="scaffold-ci-check-"))
        subprocess.run([str(self.NEW_ENGAGEMENT_SH), "ci-target", str(self.parent)],
                       check=True, capture_output=True, text=True)
        self.led = self.parent / "ci-target" / "ledger" / "ledger.md"

    def tearDown(self):
        shutil.rmtree(self.parent, ignore_errors=True)

    def test_scaffold_ships_empty_rooted_and_clean(self):
        scaffold = self.led.read_text()
        self.assertFalse(parse_rows(scaffold), "scaffold should ship with no rows")
        self.assertIsNotNone(engagement_root(self.led),
                             "scaffolded ledger has no engagement root")
        self.assertEqual(evaluate(self.led, scaffold), [], "empty scaffold is not clean")

    def test_a_hand_written_row_is_guarded(self):
        """A human fills in the empty table, saves it, then a later illegal jump straight
        to CONFIRMED must be refused -- proving the scaffold is guardable, not just clean."""
        scaffold = self.led.read_text()
        content = scaffold.rstrip("\n") + "\n| H1 | fee rounds down |  |  | UNTESTED |  |  |\n"
        self.assertTrue(parse_rows(content), "a hand-written row does not parse")
        self.assertEqual(evaluate(self.led, content), [], "a freshly hand-written row is not clean")
        self.led.write_text(content)

        illegal = content.replace("| H1 | fee rounds down |  |  | UNTESTED |",
                                  "| H1 | fee rounds down |  |  | CONFIRMED |")
        errs = evaluate(self.led, illegal)
        self.assertTrue(any("skips TIER-1" in e for e in errs), f"guard did not fire: {errs}")

    def ledger_cli(self):
        sys.path.insert(0, str(TOOLKIT_ROOT / "tooling" / "ledger"))
        import cli  # noqa: PLC0415 -- tooling/ledger/cli.py, imported lazily for these tests
        return cli

    def test_the_scaffold_writes_a_header_file_with_no_values_in_it(self):
        """REF-18, first half. The skeleton ships with bare labels on purpose: a placeholder
        would satisfy `header_missing_fields` vacuously, and the REF-23 precondition on the
        first TIER-1 promotion would stop biting on every engagement scaffolded after this.

        RUN is the one that nearly did. REF-17 stamps `skill=<commit>` into that line, and a
        label check alone then read it as filled while the model and effort were still
        blank -- so all four must still report missing here, RUN included."""
        header = self.parent / "ci-target" / "ledger" / "HEADER.md"
        self.assertTrue(header.is_file(), "the scaffold did not write ledger/HEADER.md")
        expected = [RUN_WITHOUT_MODEL if f == "RUN" else f for f in HEADER_REQUIRED_FIELDS]
        self.assertEqual(expected, header_missing_fields(header.read_text()),
                         "the scaffolded skeleton already reads as filled in")

    def test_a_run_line_carrying_only_the_stamp_does_not_satisfy_the_header_gate(self):
        """The whole point of the field: a recall delta measured across a silent model or
        effort change is not a measurement of the process change it claims to measure
        (docs/hypothesis-ledger.md). `model=not recorded` is a legal answer; empty is not."""
        stamped = "IMPACT BAR  theft\nMATERIALITY strict\nCUTOFF      N/A\nRUN         skill=abc1234"
        self.assertEqual([RUN_WITHOUT_MODEL], header_missing_fields(stamped))
        self.assertEqual([], header_missing_fields(stamped + " · model=not recorded"))

    def test_the_scaffold_stamps_the_skill_commit_it_ran_from(self):
        """REF-17. The phase files under `skill/phases/` move independently, so a ledger that
        does not name the commit it followed cannot be compared with one that followed
        another. Stamped by the scaffold from its own checkout, never typed by the model."""
        head = subprocess.run(["git", "-C", str(TOOLKIT_ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        run_line = [ln for ln in (self.parent / "ci-target" / "ledger" / "HEADER.md")
                    .read_text().splitlines() if ln.startswith("RUN")]
        self.assertEqual(1, len(run_line), run_line)
        self.assertIn(f"skill={head}", run_line[0])

    def test_a_filled_header_survives_the_first_cli_write(self):
        """REF-18, second half and the defect itself. The header used to be copied into
        `ledger/ledger.md`, and since #67 every CLI write redraws that file from the event
        log -- so the first `add` deleted it. Five engagements lost theirs that way. It now
        lives in `ledger/HEADER.md`, which `render` composes back in above the table."""
        eng = self.parent / "ci-target"
        header = eng / "ledger" / "HEADER.md"
        header.write_text(header.read_text().replace(
            "\nIMPACT BAR\n", "\nIMPACT BAR  theft / permanent lock of principal\n"))
        self.ledger_cli().main(["--engagement", str(eng), "add", "--id", "H7",
                                "--hypothesis", "fee accrual rounds down"])
        board = self.led.read_text()
        self.assertIn("IMPACT BAR  theft / permanent lock of principal", board)
        self.assertIn("| H7 |", board)
