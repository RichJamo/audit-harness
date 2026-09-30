#!/usr/bin/env python3
"""Ledger STATE guard. Runs as a Claude Code Stop hook.

WHY THIS EXISTS -- the write path, not the rule, was the hole.

ledger_guard.py is a PreToolUse hook matching `Write|Edit`, so it only ever sees a
transition proposed through those two tools. Anything else writes to a ledger completely
unguarded: `sed -i`, a heredoc, `tee`, `python -c`, or a subagent that picked Bash.
Measured live (hooktest case 18, 2026-08-20): `sed -i` performed the exact
`UNTESTED` -> `CONFIRMED` promotion that the PreToolUse guard blocks, with no block and
no message. This is not a hypothetical evasion -- Claude Code's own auto-mode instructs
the model to prefer `sed`/heredocs over the Write and Edit tools, so the DEFAULT tool
choice on a real run bypasses the guard.

Extending the matcher to Bash cannot close this. Deciding whether an arbitrary shell
command writes to a ledger is undecidable in general (the path can sit in a variable,
behind a script, or on the far side of a pipe), so a Bash matcher catches the obvious
shapes and misses the rest -- still silently. Tightening it to catch more means firing on
more, and a noisy gate gets disabled, which is the one failure the register is most
explicit about.

So this guard changes WHAT is checked rather than WHICH TOOL. Every register rule except
G3 restates cleanly as an invariant over the ledger's CURRENT STATE, which is write-path
agnostic -- it does not matter what produced the file. G3 needs history, supplied by a
row-set snapshot under .guard/.

DETECTIVE, NOT PREVENTIVE. When this fires the bad write has already landed. That is
exactly why it SUPPLEMENTS the PreToolUse guard instead of replacing it: G1 exists to make
the dedup happen BEFORE the harness hours, and only an intent-time gate can do that. This
one guarantees the violation cannot pass unnoticed, whatever wrote it.

Contract: exit 0 = silent. exit 2 = block the turn from ending, reasons on stderr.
"""
from __future__ import annotations
import hashlib, json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger_guard import (  # noqa: E402
    ROW_RE, SPEND_STATUSES, engagement_root, is_ledger, parse_rows, row_status,
    check_g1, check_g2, check_format, engagement_ledgers, field,
    check_g12, check_g14,
)

# A ledger is considered active if it changed in this window. Only used when the session
# cwd is a CONTAINER of engagements rather than one engagement, to stop the guard waking
# up every closed engagement on disk.
ACTIVE_WINDOW_S = 24 * 60 * 60
# Where engagements live. The guard used to check ONLY the engagement containing the session's
# cwd, which meant it was silently inert for any session rooted elsewhere -- and the session that
# built this guard edited seven engagement ledgers from the toolkit repo, so it would have caught
# none of them. Relying on "always cd into the engagement first" is discipline, and discipline is
# the thing this whole register exists to replace. Single-user system: the root is known, so scan
# it. Override with AUDIT_ENGAGEMENTS_ROOT.
ENGAGEMENTS_ROOT = Path(os.environ.get("AUDIT_ENGAGEMENTS_ROOT",
                                       str(Path.home() / "engagements")))
# Blocking forever is a worse failure than the violation: if the model cannot fix the
# ledger it would loop until the budget is gone. After this many blocks in one session the
# guard yields, and writes the unresolved violations to .guard/UNRESOLVED.md so the failure
# is durable and loud instead of merely repeated.
MAX_BLOCKS_PER_SESSION = 3
SNAPSHOT = "ledger-state.json"


# ---------------------------------------------------------------- discovery
def _recently_active(container: Path) -> list[Path]:
    """Engagements under `container` whose ledger changed inside the active window.

    The mtime filter is what keeps a dormant back-catalogue quiet: there are twenty
    directories under ~/engagements and only a handful are ever live at once.
    """
    out, now = [], time.time()
    if not container.is_dir():
        return out
    for child in sorted(container.iterdir()):
        if not (child.is_dir() and (child / "00-triage").is_dir()):
            continue
        try:
            if any(now - f.stat().st_mtime < ACTIVE_WINDOW_S for f in ledgers(child)):
                out.append(child)
        except OSError:
            continue
    return out


def engagement_roots(cwd: Path) -> list[Path]:
    """Every engagement this turn might have touched -- NOT just the one holding cwd.

    Three sources, unioned:
      1. the engagement containing cwd, if there is one (the session ran inside it);
      2. engagements directly under cwd, if cwd is a container of them;
      3. **engagements under ENGAGEMENTS_ROOT whose ledger changed recently** -- this is the
         one that makes the guard independent of where the session happens to be rooted.

    (3) is why you no longer have to remember to `cd` anywhere. Editing a ledger is what puts
    an engagement in scope, not the shell's working directory.
    """
    found: list[Path] = []
    root = engagement_root(cwd / "_") if cwd.is_dir() else None
    if root:
        found.append(root)
    found += _recently_active(cwd)
    found += _recently_active(ENGAGEMENTS_ROOT)
    seen, out = set(), []
    for p in found:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            out.append(p)
    return out


def ledgers(eng: Path) -> list[Path]:
    return engagement_ledgers(eng)          # one discovery function, shared with the PreToolUse guard


# ---------------------------------------------------------------- violations
def vkey(eng: Path, rel: str, rid: str, msg: str) -> str:
    """A violation identity stable across runs.

    Absolute paths and row counts drift between runs, so they are normalised out before
    hashing; otherwise a grandfathered violation would look new on the next turn.
    """
    norm = re.sub(r"[0-9]+", "N", msg.replace(str(eng), ""))
    return f"{rel}::{rid}::{hashlib.md5(norm.encode()).hexdigest()[:8]}"


def state_violations(eng: Path) -> list[tuple[str, str]]:
    """Invariants over the ledger as it stands. Returns [(key, message)]."""
    found: list[tuple[str, str]] = []
    tier1_seen = False

    for lp in ledgers(eng):
        rel = str(lp.relative_to(eng))
        content = lp.read_text(errors="ignore")
        # Format, checked on the ARTIFACT. G0c only sees ledgers created through Write/Edit,
        # so a ledger written by `cat > ledger.md <<EOF` never meets it -- the same Bash hole
        # that motivated this guard, one level up. Checking here closes it for any write path.
        for m in check_format(lp, content):
            found.append((vkey(eng, rel, "", m), f"{rel}: {m}"))
        for rid, line in parse_rows(content).items():
            st = row_status(line)
            if st is None:
                continue
            if st == "TIER-1" or st in SPEND_STATUSES:
                tier1_seen = True
                # G1 restated as state: a row that has been spent on must CARRY its dedup,
                # not merely have passed a gate at some point nobody can now inspect.
                for m in check_g1(rid, field(line, "DEDUP"), line, eng):
                    found.append((vkey(eng, rel, rid, m), f"{rel}: {m}"))
                # G14 rides with G1: it is the same dedup obligation, and a hand-edited
                # table is exactly the channel this layer exists to cover.
                for m in check_g14(rid, field(line, "DEDUP"), eng):
                    found.append((vkey(eng, rel, rid, m), f"{rel}: {m}"))
            if st in ("REFUTED", "CONFIRMED", "SCOPE-HELD"):
                if st == "SCOPE-HELD":
                    # G12 backstop. The CLI is the chokepoint for migrated engagements;
                    # this covers the ones still hand-editing a table.
                    #
                    # `found`, not a bare list: this line said `msgs.append(m)` and `msgs` is
                    # bound in main(), not here, so state_violations() raised NameError on any
                    # engagement with a SCOPE-HELD row whose sidecar says MATCH with an empty
                    # `unmatched:` -- dozens of such rows on one engagement. main() catches only
                    # OSError, so the Stop guard died with a traceback and G1/G2/G12/G14 all
                    # went unenforced for that engagement. Silent since G12 shipped, because a
                    # crashed Stop hook looks exactly like a clean one.
                    for m in check_g12(rid, field(line, "DEDUP"), eng):
                        found.append((vkey(eng, rel, rid, m), f"{rel}: {m}"))
                for m in check_g2(rid, field(line, "DEDUP"), field(line, "EVIDENCE"),
                                  field(line, "HUMAN"), line, st, eng):
                    found.append((vkey(eng, rel, rid, m), f"{rel}: {m}"))

    poc = eng / "poc"
    if poc.is_dir() and any(p.is_file() for p in poc.rglob("*")) and not tier1_seen:
        m = ("G1b harness files exist under poc/ but no row has reached TIER-1, so nothing "
             "has been deduped against prior art. Promote the row being tested first.")
        found.append((vkey(eng, "", "", m), m))
    return found


def vanished_rows(eng: Path, snap: dict) -> list[tuple[str, str]]:
    """G3 restated over the snapshot: a row present last turn must still be present."""
    out = []
    prev = snap.get("rows", {})
    for lp in ledgers(eng):
        rel = str(lp.relative_to(eng))
        if rel not in prev:
            continue
        content = lp.read_text(errors="ignore")
        now = set(parse_rows(content))
        if "LEDGER-DELETE-APPROVED:" in content:
            continue
        for rid in sorted(set(prev[rel]) - now):
            m = re.search(rf"{re.escape(rid)}\b.{{0,120}}?MERGED-INTO:\s*([A-Z][A-Z0-9]*-?[0-9]+)",
                          content)
            if m and m.group(1) in now:
                continue
            msg = (f"G3 {rel}: row {rid} was present last turn and is gone now. Rows never "
                   f"vanish -- use BLOCKED / BLOCKED-OUT-OF-HARNESS, or record "
                   f"'MERGED-INTO: <id>' or 'LEDGER-DELETE-APPROVED: <reason>'.")
            out.append((vkey(eng, rel, rid, "G3-vanished"), msg))
    return out


# ---------------------------------------------------------------- snapshot
def load_snapshot(eng: Path) -> dict:
    f = eng / ".guard" / SNAPSHOT
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}


def save_snapshot(eng: Path, snap: dict) -> None:
    d = eng / ".guard"
    d.mkdir(exist_ok=True)
    (d / SNAPSHOT).write_text(json.dumps(snap, indent=2, sort_keys=True))


def current_rows(eng: Path) -> dict[str, list[str]]:
    return {str(lp.relative_to(eng)): sorted(parse_rows(lp.read_text(errors="ignore")))
            for lp in ledgers(eng)}


# ---------------------------------------------------------------- driver
def evaluate_engagement(eng: Path, session: str) -> tuple[list[str], dict, bool]:
    """Returns (messages_to_report, snapshot_to_save, should_block)."""
    snap = load_snapshot(eng)
    known = set(snap.get("known_violations", []))
    first_run = not snap

    violations = state_violations(eng) + vanished_rows(eng, snap)
    fresh = [(k, m) for k, m in violations if k not in known]

    new_snap = {
        "version": 1,
        "rows": current_rows(eng),
        "known_violations": sorted({k for k, _ in violations}),
        "block_session": snap.get("block_session"),
        "block_count": snap.get("block_count", 0),
    }

    # First run in an engagement records a BASELINE and reports nothing. Without this the
    # guard would open by dumping every pre-existing violation in a mature ledger, which is
    # how a gate earns a reputation for noise and gets switched off. Enforcement starts
    # from the state it inherited.
    if first_run or not fresh:
        new_snap["block_session"], new_snap["block_count"] = None, 0
        return [], new_snap, False

    if new_snap["block_session"] != session:
        new_snap["block_session"], new_snap["block_count"] = session, 0
    new_snap["block_count"] += 1

    if new_snap["block_count"] > MAX_BLOCKS_PER_SESSION:
        d = eng / ".guard"
        d.mkdir(exist_ok=True)
        (d / "UNRESOLVED.md").write_text(
            "# Unresolved ledger violations\n\n"
            f"The ledger state guard blocked {MAX_BLOCKS_PER_SESSION} times in one session "
            "and then yielded, so these were NOT fixed. They are recorded here because a "
            "guard that loops forever is worse than the violation it is chasing, and a "
            "violation that merely scrolls past is invisible.\n\n"
            + "".join(f"- {m}\n" for _, m in fresh))
        new_snap["known_violations"] = sorted({k for k, _ in violations})
        return [], new_snap, False

    return [m for _, m in fresh], new_snap, True


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return 0
    session = str(payload.get("session_id", ""))
    cwd = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    override = os.environ.get("AUDIT_ENGAGEMENT_ROOT")   # tests + explicit targeting
    roots = [Path(override)] if override else engagement_roots(cwd)

    msgs: list[str] = []
    for eng in roots:
        try:
            m, snap, block = evaluate_engagement(eng, session)
            save_snapshot(eng, snap)
            if block:
                msgs += m
        except OSError:
            continue          # an unreadable engagement is not a reason to trap the turn

    if not msgs:
        return 0
    print("Ledger state is invalid (docs/guard-register.md). This fires on the ledger's "
          "state, so it catches writes made by any tool -- sed, a script, a subagent -- "
          "not just Write/Edit:", file=sys.stderr)
    for m in msgs:
        print(f"  - {m}", file=sys.stderr)
    print("Fix the rows above, or record the explicit escape hatch each rule names.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
