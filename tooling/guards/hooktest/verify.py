#!/usr/bin/env python3
"""Replay every hook-test case and check the verdict.

Run: ./reset.sh && python3 verify.py

This drives the guards through their REAL stdin contract -- the same JSON a PreToolUse or
Stop hook receives -- so it exercises the shipped scripts, not an importable subset. What
it does NOT prove is that the hooks are REGISTERED with Claude Code; only an actual tool
call in a live session shows that. Do that check by hand at least once per wiring change
(the frontmatter has silently mis-resolved before), then use this for the rest.
"""
import json, os, subprocess, sys
from pathlib import Path

H = Path(__file__).resolve().parent
# The guards sit one level up -- this suite now lives inside the toolkit beside them,
# so resolve them relatively rather than assuming a checkout at ~/audit-toolkit.
PRE = H.parent / "ledger_guard.py"
STOP = H.parent / "ledger_state_guard.py"
TOOLKIT = H.parents[2]

# Fixtures live OUTSIDE the toolkit repo. ledger_guard exempts every path under
# audit-toolkit/, so fixtures inside it would make every case ALLOW and the suite would
# report ALL PASS having never run a guard. reset.sh builds them here; keep the two in step.
CASES_DIR = Path(os.environ.get(
    "HOOKTEST_CASES", Path(os.environ.get("TMPDIR", "/tmp")) / "audit-toolkit-hooktest/cases"))

BLOCK, ALLOW = "BLOCK", "ALLOW"

# The Stop guard scans ~/engagements for recently-touched engagements REGARDLESS of cwd -- that is
# what makes it independent of where a session is rooted, and it is correct. It also means an
# unsandboxed test run reaches into LIVE engagements: measured 2026-08-28, running this suite
# rewrote .guard/ledger-state.json for three live engagements, silently GRANDFATHERING
# whatever violations those ledgers held at that moment. A violation absorbed by a test run is one
# the real session is never told about. So every subprocess gets the fixtures as its engagements
# root, and the canary refuses to run if that is not in force.
SANDBOX_ENV = {**os.environ, "AUDIT_ENGAGEMENTS_ROOT": str(CASES_DIR)}


def canary() -> None:
    """A green suite that never ran a guard is a lie.

    ledger_guard exempts every path under the toolkit repo, so fixtures built inside it
    would make all 22 cases ALLOW and the suite would report ALL PASS having tested
    nothing. That is not hypothetical -- it happened on 2026-08-28, the first run after
    this suite was moved in from ~/engagements/. Refuse to run rather than green-wash.
    """
    if not CASES_DIR.exists():
        sys.exit(f"canary: no fixtures at {CASES_DIR} -- run ./reset.sh first")
    if CASES_DIR.resolve().is_relative_to(TOOLKIT):
        sys.exit(f"canary: fixtures are inside the toolkit repo ({CASES_DIR}).\n"
                 f"Everything under {TOOLKIT} is exempt from the guards, so every case\n"
                 f"would ALLOW and pass without a guard running. Build them elsewhere.")
    for f in (PRE, STOP):
        if not f.exists():
            sys.exit(f"canary: guard not found at {f}")
    real = Path(os.environ.get("HOME", "~")) / "engagements"
    if SANDBOX_ENV.get("AUDIT_ENGAGEMENTS_ROOT") != str(CASES_DIR):
        sys.exit("canary: the engagements root is not sandboxed to the fixtures.")
    if CASES_DIR.resolve() == real.resolve():
        sys.exit(f"canary: fixtures are the REAL engagements root ({real}). Refusing: the Stop "
                 f"guard would baseline live ledgers and hide their violations.")


def edit(case, old, new):
    return ("pre", {"file_path": str(CASES_DIR / case / "ledger/ledger.md"),
                    "old_string": old, "new_string": new})


def write(case, rel, content="// harness stub\n"):
    return ("pre", {"file_path": str(CASES_DIR / case / rel), "content": content})


U = "| `UNTESTED` |"
UD = "| `UNTESTED` DEDUP:"
T1 = "| `TIER-1` |"

CASES = [
    ("01-g1-waypoint",          edit("01-g1-waypoint", U, "| `CONFIRMED` |"),      BLOCK, "skips TIER-1"),
    ("02-g1-no-corpus",         edit("02-g1-no-corpus", U, T1),                    BLOCK, "no prior-audit sources"),
    ("03-g1-no-dedup",          edit("03-g1-no-dedup", U, T1),                     BLOCK, "no DEDUP: pointer"),
    ("04-g1-nomatch-idents",    edit("04-g1-nomatch-idents", UD, "| `TIER-1` DEDUP:"), BLOCK, "identifiers from this row"),
    ("05-g1-paraphrase",        edit("05-g1-paraphrase", UD, "| `TIER-1` DEDUP:"), BLOCK, "not an EXACT substring"),
    ("06-g1-pass",              edit("06-g1-pass", UD, "| `TIER-1` DEDUP:"),       ALLOW, ""),
    ("07-g1b-no-tier1",         write("07-g1b-no-tier1", "poc/FeeAccrual.t.sol"),  BLOCK, "no row is at TIER-1"),
    ("08-g1b-pass",             write("08-g1b-pass", "poc/FeeAccrual.t.sol"),      ALLOW, ""),
    ("09-g2-refuted-prose",     edit("09-g2-refuted-prose", T1, "| `REFUTED` - safe by inspection |"), BLOCK, "never by prose"),
    ("10-g2-evidence-missing",  edit("10-g2-evidence-missing", T1, "| `REFUTED` EVIDENCE: poc/Nope.t.sol |"), BLOCK, "does not resolve"),
    ("11-g2-refuted-pass",      edit("11-g2-refuted-pass", T1, "| `REFUTED` EVIDENCE: poc/FeeRounding.t.sol::test_residueNotClaimable |"), ALLOW, ""),
    ("23-g2-refuted-noreason",  edit("23-g2-refuted-noreason", T1, "| `REFUTED` EVIDENCE: poc/FeeRounding.t.sol::test_residueNotClaimable |"), BLOCK, "needs a --reason"),
    ("12-g2-scopeheld-nohuman", edit("12-g2-scopeheld-nohuman", U, "| `SCOPE-HELD` admin-gated |"), BLOCK, "no HUMAN: record"),
    ("13-g2-scopeheld-pass",    edit("13-g2-scopeheld-pass", U, "| `SCOPE-HELD` HUMAN: RJ 2026-08-20 |"), ALLOW, ""),
    ("14-g3-delete",            edit("14-g3-delete", "| **HT-41** | withdrawal queue starvation via dust | `UNTESTED` |\n", ""), BLOCK, "rows vanished"),
    ("15-g3-merged",            edit("15-g3-merged", "| **HT-51** | fee truncation on full exit (same mechanism) | `UNTESTED` |", "HT-51 folded in. MERGED-INTO: HT-50"), ALLOW, ""),
    ("16-noise-control",        ("pre", {"file_path": str(CASES_DIR / "16-noise-control/notes.md"),
                                         "old_string": "guard.", "new_string": "guard. UNTESTED REFUTED CONFIRMED."}), ALLOW, ""),
    ("17-no-00-triage",         edit("17-no-00-triage", U, "| `CONFIRMED` |"),     BLOCK, "no engagement root"),
    ("22-g0b-nontable",         edit("22-g0b-nontable", "Refuted by inspection.", "Refuted by inspection. Still refuted."), BLOCK, "readable table row(s)"),
]


def run_pre(tool_input):
    r = subprocess.run([sys.executable, str(PRE)],
                       input=json.dumps({"tool_input": tool_input}),
                       capture_output=True, text=True, env=SANDBOX_ENV)
    return r.returncode, r.stderr


def run_stop(case, session="verify"):
    eng = CASES_DIR / case
    r = subprocess.run([sys.executable, str(STOP)],
                       input=json.dumps({"session_id": session, "cwd": str(eng),
                                         "stop_hook_active": False}),
                       capture_output=True, text=True, env=SANDBOX_ENV)
    return r.returncode, r.stderr


def main():
    canary()
    fails = 0
    print("=== PreToolUse guard (Write|Edit) ===")
    for name, (_, ti), expect, needle in CASES:
        code, err = run_pre(ti)
        got = BLOCK if code == 2 else ALLOW
        ok = got == expect and (not needle or needle in err)
        fails += not ok
        print(f"  [{'ok ' if ok else 'FAIL'}] {name:26s} {got}")
        if not ok:
            print(f"         expected {expect} containing {needle!r}; stderr: {err.strip()[:200]}")

    print("\n=== Stop guard (state; catches any write path) ===")
    # 18: the bypass the PreToolUse matcher cannot see.
    led = CASES_DIR / "18-bash-bypass/ledger/ledger.md"
    led.write_text(led.read_text().replace("`CONFIRMED`", "`UNTESTED`"))  # idempotent
    for g in (CASES_DIR / "18-bash-bypass/.guard",):
        if g.exists():
            for f in g.iterdir():
                f.unlink()
            g.rmdir()
    code, _ = run_stop("18-bash-bypass")
    ok = code == 0
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] 19-stop-baseline          {'ALLOW' if ok else 'BLOCK'} (first run records a baseline)")

    led.write_text(led.read_text().replace("`UNTESTED`", "`CONFIRMED`"))   # the sed bypass
    code, err = run_stop("18-bash-bypass")
    ok = code == 2 and "G1" in err
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] 20-stop-catches-bash-write {'BLOCK' if code == 2 else 'ALLOW'}")

    code, _ = run_stop("18-bash-bypass")
    ok = code == 0
    fails += not ok
    print(f"  [{'ok ' if ok else 'FAIL'}] 21-stop-reports-once       {'ALLOW' if ok else 'BLOCK'} (known violation is not re-reported)")

    print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
