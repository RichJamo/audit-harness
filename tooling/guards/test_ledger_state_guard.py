#!/usr/bin/env python3
"""Tests for the ledger STATE guard (Stop hook).

The headline case is test_sed_style_write_is_caught: the guard must catch a violation
written by a tool the PreToolUse matcher never sees. That is the whole reason it exists.
"""
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ledger_state_guard import (  # noqa: E402
    MAX_BLOCKS_PER_SESSION, evaluate_engagement, load_snapshot, save_snapshot,
    state_violations,
)
import ledger_state_guard as LSG  # noqa: E402

GUARD = Path(__file__).parent / "ledger_state_guard.py"
CLEAN = ("| id | hypothesis | status |\n|---|---|---|\n"
         "| H-01 | fee accrual rounds down | `UNTESTED` |\n"
         "| H-02 | queue starvation via dust | `UNTESTED` |\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.eng = Path(tempfile.mkdtemp())
        (self.eng / "00-triage").mkdir()
        (self.eng / "ledger").mkdir()
        self.ledger = self.eng / "ledger" / "ledger.md"
        self.ledger.write_text(CLEAN)

    def tearDown(self):
        shutil.rmtree(self.eng, ignore_errors=True)

    def run_guard(self, session="s1"):
        """One Stop-hook pass over this engagement, persisting the snapshot as main does."""
        msgs, snap, block = evaluate_engagement(self.eng, session)
        save_snapshot(self.eng, snap)
        return msgs, block

    def sed(self, old, new):
        """Mutate the ledger the way Bash would -- bypassing Write/Edit entirely."""
        self.ledger.write_text(self.ledger.read_text().replace(old, new, 1))


class TestBaseline(Base):
    def test_first_run_is_silent_and_records_a_baseline(self):
        msgs, block = self.run_guard()
        self.assertEqual(msgs, [])
        self.assertFalse(block)
        self.assertIn("ledger/ledger.md", load_snapshot(self.eng)["rows"])

    def test_clean_ledger_stays_silent(self):
        self.run_guard()
        self.assertEqual(self.run_guard()[0], [])

    def test_preexisting_violations_are_grandfathered(self):
        """Opening by dumping every legacy violation is how a gate gets switched off."""
        self.ledger.write_text(CLEAN.replace("| H-01 | fee accrual rounds down | `UNTESTED` |",
                                             "| H-01 | fee accrual rounds down | `REFUTED` |"))
        self.assertEqual(self.run_guard()[0], [], "first run must baseline, not report")
        self.assertEqual(self.run_guard()[0], [], "and must stay quiet about it after")


class TestDetection(Base):
    def test_sed_style_write_is_caught(self):
        """THE point of this guard: a prose-kill written by Bash, which PreToolUse misses."""
        self.run_guard()
        self.sed("| H-01 | fee accrual rounds down | `UNTESTED` |",
                 "| H-01 | fee accrual rounds down | `REFUTED` - conserved by inspection |")
        msgs, block = self.run_guard()
        self.assertTrue(block)
        self.assertTrue(any("G2" in m and "H-01" in m for m in msgs), msgs)

    def test_scope_held_without_a_human_is_caught(self):
        self.run_guard()
        self.sed("| H-02 | queue starvation via dust | `UNTESTED` |",
                 "| H-02 | queue starvation via dust | `SCOPE-HELD` admin-gated |")
        msgs, block = self.run_guard()
        self.assertTrue(block)
        self.assertTrue(any("HUMAN" in m for m in msgs), msgs)

    def test_scope_held_with_a_human_passes(self):
        self.run_guard()
        self.sed("| H-02 | queue starvation via dust | `UNTESTED` |",
                 "| H-02 | queue starvation via dust | `SCOPE-HELD` HUMAN: RJ 2026-08-20 |")
        self.assertEqual(self.run_guard()[0], [])

    def test_a_path_function_citation_is_accepted(self):
        """REF-1. The Stop hook is check_g2's third caller and runs on every engagement,
        so it must resolve the path part of `path::function` -- otherwise the citation
        format `promote` now requires would block every session that used it."""
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "H02.t.sol").write_text(
            "contract T { function test_H02_refuted() public {} }")
        self.run_guard()
        self.sed("| H-02 | queue starvation via dust | `UNTESTED` |",
                 "| H-02 | queue starvation via dust | `REFUTED` "
                 "EVIDENCE: poc/H02.t.sol::test_H02_refuted |")
        msgs, _ = self.run_guard()
        self.assertEqual([m for m in msgs if "G2" in m], [], msgs)

    def test_vanished_row_is_caught_across_runs(self):
        self.run_guard()
        self.sed("| H-02 | queue starvation via dust | `UNTESTED` |\n", "")
        msgs, block = self.run_guard()
        self.assertTrue(block)
        self.assertTrue(any("G3" in m and "H-02" in m for m in msgs), msgs)

    def test_merged_into_hatch_is_honoured(self):
        self.run_guard()
        self.sed("| H-02 | queue starvation via dust | `UNTESTED` |",
                 "H-02 folded in. MERGED-INTO: H-01")
        self.assertEqual(self.run_guard()[0], [])

    def test_harness_without_any_tier1_is_caught(self):
        self.run_guard()
        (self.eng / "poc").mkdir()
        (self.eng / "poc" / "Exploit.t.sol").write_text("contract E {}")
        msgs, block = self.run_guard()
        self.assertTrue(block)
        self.assertTrue(any("G1b" in m for m in msgs), msgs)

    def test_a_violation_is_reported_once_not_every_turn(self):
        """Re-reporting a known violation forever is noise; the snapshot absorbs it."""
        self.run_guard()
        self.sed("| H-01 | fee accrual rounds down | `UNTESTED` |",
                 "| H-01 | fee accrual rounds down | `REFUTED` - by inspection |")
        self.assertTrue(self.run_guard()[1], "first sighting blocks")
        self.assertEqual(self.run_guard()[0], [], "second sighting is already known")


class TestBelowBarRecognised(Base):
    """Regression: BELOW-BAR was added to the CLI (2026-09-02) but not to the guard's
    STATUSES list, so parse_rows dropped BELOW-BAR rows and G3 reported them as vanished.
    A row set to a valid terminal status must NEVER read as gone. Caught live on the
    engagement 19, 2026-09-08."""

    def test_below_bar_row_is_not_seen_as_vanished(self):
        self.run_guard()  # baseline with H-01 UNTESTED
        # Move H-01 to BELOW-BAR the way the CLI render would.
        self.sed("| H-01 | fee accrual rounds down | `UNTESTED` |",
                 "| H-01 | fee accrual rounds down | `BELOW-BAR` |")
        msgs, block = self.run_guard()
        joined = " ".join(msgs)
        self.assertNotIn("H-01", joined,
                         "a BELOW-BAR row must not be reported as vanished (G3)")
        self.assertFalse(block)


class TestLoopSafety(Base):
    def test_blocking_is_bounded_and_the_failure_is_written_down(self):
        """A guard that loops until the budget is gone is worse than the violation."""
        self.run_guard()
        self.sed("| H-01 | fee accrual rounds down | `UNTESTED` |",
                 "| H-01 | fee accrual rounds down | `REFUTED` - by inspection |")
        blocks = 0
        for _ in range(MAX_BLOCKS_PER_SESSION + 2):
            # re-arm each turn: the model "did not fix it", which is the loop we fear
            snap = load_snapshot(self.eng)
            snap["known_violations"] = []
            save_snapshot(self.eng, snap)
            if self.run_guard()[1]:
                blocks += 1
        self.assertEqual(blocks, MAX_BLOCKS_PER_SESSION)
        unresolved = self.eng / ".guard" / "UNRESOLVED.md"
        self.assertTrue(unresolved.exists(), "an abandoned violation must become durable")
        self.assertIn("H-01", unresolved.read_text())


class TestHookInterface(Base):
    def hook(self, session="s1"):
        return subprocess.run(
            [sys.executable, str(GUARD)],
            input=json.dumps({"session_id": session, "cwd": str(self.eng),
                              "stop_hook_active": False}),
            capture_output=True, text=True,
            env={**__import__("os").environ, "AUDIT_ENGAGEMENT_ROOT": str(self.eng)})

    def test_exit_0_and_silent_on_a_clean_ledger(self):
        self.hook()
        r = self.hook()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.strip(), "")

    def test_exit_2_through_the_real_stdin_interface(self):
        self.hook()
        self.sed("| H-01 | fee accrual rounds down | `UNTESTED` |",
                 "| H-01 | fee accrual rounds down | `REFUTED` - by inspection |")
        r = self.hook()
        self.assertEqual(r.returncode, 2)
        self.assertIn("G2", r.stderr)

    def test_garbage_stdin_stays_silent(self):
        r = subprocess.run([sys.executable, str(GUARD)], input="not json",
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


class TestEngagementDiscovery(unittest.TestCase):
    """The guard must find a touched engagement wherever the session is rooted.

    It used to check ONLY the engagement containing cwd. The session that built this guard
    edited seven engagement ledgers from the toolkit repo and would have been caught by none
    of them. "Always cd into the engagement first" is discipline, and discipline is the thing
    the register exists to replace.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())          # stands in for ~/engagements
        self.elsewhere = Path(tempfile.mkdtemp())      # stands in for ~/audit-toolkit
        self.eng = self.root / "target-x"
        (self.eng / "00-triage").mkdir(parents=True)
        (self.eng / "ledger").mkdir()
        (self.eng / "ledger" / "ledger.md").write_text("| H-01 | a | `UNTESTED` |\n")
        self._saved = LSG.ENGAGEMENTS_ROOT
        LSG.ENGAGEMENTS_ROOT = self.root

    def tearDown(self):
        LSG.ENGAGEMENTS_ROOT = self._saved
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.elsewhere, ignore_errors=True)

    def test_found_from_an_unrelated_cwd(self):
        """THE fix: a session rooted anywhere still sees a recently-touched engagement."""
        self.assertEqual([p.name for p in LSG.engagement_roots(self.elsewhere)], ["target-x"])

    def test_found_from_inside_the_engagement(self):
        self.assertIn("target-x", [p.name for p in LSG.engagement_roots(self.eng)])

    def test_not_listed_twice_when_cwd_is_the_engagement(self):
        self.assertEqual(len(LSG.engagement_roots(self.eng)), 1)

    def test_a_dormant_engagement_is_ignored(self):
        """Twenty directories live under ~/engagements; only live ones should be woken."""
        old = time.time() - (LSG.ACTIVE_WINDOW_S + 3600)
        os.utime(self.eng / "ledger" / "ledger.md", (old, old))
        self.assertEqual(LSG.engagement_roots(self.elsewhere), [])

    def test_a_directory_without_00_triage_is_not_an_engagement(self):
        (self.root / "just-a-folder").mkdir()
        (self.root / "just-a-folder" / "ledger.md").write_text("| H-01 | a | `UNTESTED` |\n")
        self.assertEqual([p.name for p in LSG.engagement_roots(self.elsewhere)], ["target-x"])


class TestHooktestSandbox(unittest.TestCase):
    """The hook-wiring suite must not reach the REAL ~/engagements.

    `engagement_roots()` scans ENGAGEMENTS_ROOT regardless of cwd -- correct for a live session,
    and the reason an unsandboxed test run rewrote .guard/ledger-state.json for three live
    engagements on 2026-08-28, silently grandfathering the violations they held at that moment.
    A violation absorbed by a test run is one the real session is never told about.
    """

    SUITE = Path(__file__).resolve().parent / "hooktest" / "verify.py"

    def test_the_suite_pins_the_engagements_root_to_its_fixtures(self):
        src = self.SUITE.read_text()
        self.assertIn('SANDBOX_ENV = {**os.environ, "AUDIT_ENGAGEMENTS_ROOT": str(CASES_DIR)}', src)

    def test_every_guard_subprocess_runs_inside_the_sandbox(self):
        src = self.SUITE.read_text()
        calls = src.split("subprocess.run(")[1:]
        self.assertTrue(calls, "verify.py spawns no guard subprocess -- has it been rewritten?")
        for call in calls:
            self.assertIn("env=SANDBOX_ENV", call[:400],
                          "a guard subprocess without the sandbox env can reach ~/engagements")


class TestG12BackstopDoesNotCrashTheHook(Base):
    """The G12 branch referenced a name bound in main(), so state_violations() raised.

    Found by review, 2026-09-10. `for m in check_g12(...): msgs.append(m)` sat inside
    state_violations(), which binds `found`, not `msgs`. Any engagement holding a SCOPE-HELD
    row whose dedup sidecar says `result: MATCH` with an empty `unmatched:` raised NameError
    -- dozens of such rows on one engagement. main() catches only OSError, so the Stop hook died
    with a traceback and G1, G2, G12 and G14 all went unenforced for that engagement.

    It was silent for the same reason every rule in this repo needs machinery: a crashed Stop
    hook and a clean one look identical from the outside.
    """

    def scope_held_matching_a_known_issue(self):
        (self.eng / "00-triage" / "prior-audits").mkdir(parents=True, exist_ok=True)
        (self.eng / "00-triage" / "prior-audits" / "r.pdf").write_bytes(b"%PDF-1.4")
        pr = self.eng / "00-triage" / "potential-risks"
        pr.mkdir(parents=True, exist_ok=True)
        (pr / "known.txt").write_text(
            "Known Issues\n  the vault mints shares before pulling assets on the first deposit\n")
        d = self.eng / "ledger" / "dedup"
        d.mkdir(parents=True, exist_ok=True)
        (d / "H-01.md").write_text(
            "searched:\n  - 00-triage/potential-risks/known.txt\n"
            "terms:\n  - a\n  - b\n  - c\nresult: MATCH\n"
            "quote: the vault mints shares before pulling assets on the first deposit\n")
        self.run_guard()                                  # baseline first, as main() does
        self.sed("| H-01 | fee accrual rounds down | `UNTESTED` |",
                 "| H-01 | fee accrual rounds down | `SCOPE-HELD` | DEDUP: ledger/dedup/H-01.md "
                 "| HUMAN: RJ ruled it a duplicate 2026-09-10 |")

    def test_the_hook_survives_a_g12_hit(self):
        self.scope_held_matching_a_known_issue()
        msgs, _ = self.run_guard()                        # NameError before the fix
        self.assertTrue(any("G12" in m for m in msgs), msgs)

    def test_state_violations_returns_rather_than_raising(self):
        """Called directly, because evaluate_engagement is where a future try/except could
        hide the crash again and turn this into a green test over a dead code path."""
        self.scope_held_matching_a_known_issue()
        self.assertTrue(any("G12" in m for _, m in state_violations(self.eng)))


class TestFreshEngagementScaffold(unittest.TestCase):
    """A fresh engagement's placeholder row must not trip G3 on its first render.

    tooling/new-engagement.sh scaffolds ledger/ledger.md from templates/ledger.template.md,
    whose `H1` example row parses as a real UNTESTED ledger row -- confirmed by
    test_ledger_guard.py::TestRowParsing::test_hyphenless_id_from_the_repo_template -- but
    it was never created through the ledger CLI, so ledger/events.jsonl has no H1 event.
    If a Stop-hook baseline is ever taken while that row is still on disk (routine: it is
    there from the moment the engagement is scaffolded), the first CLI-triggered redraw --
    now happening on the very first `add`, per the board-redraw fix -- does not know about
    H1 and silently drops it. The next Stop-hook check then sees H1 gone and fires G3
    ("row H1 was present last turn and is gone now") on an engagement that never had a
    real H1 hypothesis at all.
    """

    NEW_ENGAGEMENT_SH = Path(__file__).resolve().parent.parent / "new-engagement.sh"

    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="board-redraw-fresh-"))
        subprocess.run([str(self.NEW_ENGAGEMENT_SH), "fresh", str(self.parent)],
                       check=True, capture_output=True, text=True)
        self.eng = self.parent / "fresh"
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ledger"))
        global cli
        import cli  # noqa: E402  (tooling/ledger/cli.py, imported lazily for this test only)

    def tearDown(self):
        shutil.rmtree(self.parent, ignore_errors=True)

    def run_guard(self, session="s1"):
        msgs, snap, block = evaluate_engagement(self.eng, session)
        save_snapshot(self.eng, snap)
        return msgs, block

    def test_the_placeholder_row_does_not_trip_g3_on_first_add(self):
        self.run_guard()   # baseline: whatever new-engagement.sh scaffolded
        cli.main(["--engagement", str(self.eng), "add", "--id", "H2",
                 "--hypothesis", "a real hypothesis, added through the CLI"])
        msgs, block = self.run_guard()
        self.assertFalse(block, msgs)
        self.assertFalse(any("G3" in m for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
