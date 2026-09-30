"""`audit ledger` -- the only door into ledger state.

The guard predicates run here as PRECONDITIONS OF THE MUTATION, not as an interception
of a document edit. Validation and mutation are the same operation, so there is no gap
between them for a write path to slip through.

  python3 tooling/ledger/cli.py add     --id R-6 --hypothesis "..."
  python3 tooling/ledger/cli.py import  <ledger.md>
  python3 tooling/ledger/cli.py promote --id R-6 --to TIER-1 --dedup ledger/dedup/R-6.md
  python3 tooling/ledger/cli.py phase   --done 2
  python3 tooling/ledger/cli.py render
  python3 tooling/ledger/cli.py verify

Phase 1 implements the `-> TIER-1` transition only; that is where G1 fires and where
spend is committed. Other transitions are phase 2 (see the design note).
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "guards"))
from store import (  # noqa: E402
    CREATE, append, read_events, replay, revisits, status_path, events_path, RENDER, HEADER,
)
from ledger_guard import (  # noqa: E402
    ROW_RE, FORMAT_MARKER, STATUSES, check_g1, check_g2, check_g12, check_g14,
    check_below_bar, check_blocked, check_evidence_function, check_refuted_reason,
    engagement_root, load_sidecar,
    header_missing_fields,
)

# Row creation is DELIBERATELY UNGATED (CLAUDE.md constraint 1): phases 1-2 generate
# wide and suppress nothing. Only transitions are gated.
CREATE_STATUS = "UNTESTED"
WAYPOINT = "TIER-1"
# Reaching CONFIRMED or REFUTED implies harness work, and the dedup obligation is owed
# BEFORE that spend, so those need the waypoint.
SPEND = ("CONFIRMED", "REFUTED")
# CORRECTED 2026-09-01 (REF-2). This block used to say SCOPE-HELD "needs no waypoint --
# no spend happened", counting only harness hours as spend. One engagement, cut from this
# release, refutes that: most of its rows left the hunt through SCOPE-HELD, and every
# finding the contest actually paid for was inside them. The spend is OPPORTUNITY, not
# compute -- a held row is a hunt permanently abandoned -- and it was invisible to this
# model. SCOPE-HELD still
# needs no TIER-1 waypoint (no harness hours are owed), but it is not free, and G12
# below is what prices it.
# BELOW-BAR (added 2026-09-02): a row that is REAL but cannot clear THIS program's reward
# bar -- e.g. a valid Low on a Critical-only contest (engagement 4 H16/H17/H18). Before this, such
# rows sat UNTESTED, which reads as "not yet looked at" when the truth is "looked at, decided
# not to chase because it cannot pay here". Terminal, no waypoint (no PoC spend is owed), but
# it requires a cited reason naming the bar it fails -- otherwise it is a silent-drop channel,
# which is exactly what the immovable rules forbid. Contest-relative, never "not a bug": the
# row is LABELLED, so a courtesy disclosure or a re-file on another platform stays open.
TERMINAL = SPEND + ("SCOPE-HELD", "BELOW-BAR", "BLOCKED", "BLOCKED-OUT-OF-HARNESS")

PHASES_FILE = "PHASES.md"
# The skill's phases, -1 through 5. tooling/engagement-doctor.py holds the other copy
# (its PHASES) and the regex it parses these lines with (PHASE_LINE_RE). The round-trip
# test runs the doctor's own check over this command's output and asserts the two lists
# agree, rather than importing a hyphenated script into every ledger call.
PHASE_IDS = ["-1", "0", "1", "2", "3", "4", "5"]


def _eng(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).resolve()
        if not (p / "00-triage").is_dir():
            sys.exit(f"not an engagement (no 00-triage/): {p}")
        return p
    # engagement_root() walks PARENTS only, which is right for the hook (it is handed a
    # file path inside the engagement) and wrong here: the cwd may BE the engagement.
    cwd = Path.cwd().resolve()
    if (cwd / "00-triage").is_dir():
        return cwd
    p = engagement_root(cwd)
    if not p:
        sys.exit("no engagement root found from cwd. Pass --engagement <dir>.")
    return p


def cmd_add(a) -> int:
    eng = _eng(a.engagement)
    if a.id in replay(eng):
        sys.exit(f"row {a.id} already exists. Rows are never recreated.")
    append(eng, {"id": a.id, "event": CREATE, "status": CREATE_STATUS,
                 "hypothesis": a.hypothesis, "entry": a.entry,
                 "invariant": a.invariant, "by": a.by})
    print(f"{a.id} created UNTESTED")
    redraw(eng)
    return 0


# REF-21: a table-shaped line is one starting with `|` and carrying four or more cells. The
# two shapes that are NOT rows are a table's separator and the header line above it.
# Anything else of that shape is a row someone meant to import.
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


def _is_separator(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return line.lstrip().startswith("|") and bool(cells) and all(
        _SEPARATOR_CELL_RE.match(c) for c in cells if c)


def _scan_tables(text: str) -> dict:
    """Sort every markdown table in an import source by its header, and every data line in it.

    REF-21: five refutation-critic files emitted ids like `RC-L03-1`, ROW_RE allows one
    hyphen, and `import` printed "imported 0 rows" five times. 24 rows were lost and nothing
    said so -- the operator could not tell "found nothing" from "read nothing".

    A table whose header's first cell is `id`, or a table with no header, is a LEDGER table:
    every data line must parse, or the import is refused. A table with any other header (a
    hunter's coverage map, a call-site inventory) is SKIPPED, and reported as skipped -- unless
    one of its lines parses as a ledger row, which makes it AMBIGUOUS and refuses the import,
    so real rows under a wrong header can never vanish. Returns rows, rejected, skipped and
    ambiguous, each a list of (line number, detail).
    """
    lines = text.splitlines()
    out: dict = {"rows": [], "rejected": [], "skipped": [], "ambiguous": []}
    n = 0
    while n < len(lines):
        if not lines[n].lstrip().startswith("|"):
            n += 1
            continue
        start = n
        while n < len(lines) and lines[n].lstrip().startswith("|"):
            n += 1
        block = list(range(start, n))                 # 0-based line indices of one table
        has_header = len(block) >= 2 and _is_separator(lines[block[1]])
        data = block[2:] if has_header else block
        first = (lines[start].strip().strip("|").split("|")[0].strip("*_` ").lower()
                 if has_header else "id")
        if first != "id":
            hits = [i for i in data if ROW_RE.search(lines[i])]
            if hits:
                out["ambiguous"].append((hits[0] + 1, first))
            else:
                out["skipped"].append((start + 1, f"{first} ({len(data)} line(s))"))
            continue
        for i in data:
            line = lines[i]
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if _is_separator(line):
                continue
            if ROW_RE.search(line):
                out["rows"].append((i + 1, line))
            elif len(cells) >= 4:
                out["rejected"].append((i + 1, cells[0].strip("*_` ")))
    return out


def cmd_import(a) -> int:
    """Bulk path, built on day one on purpose: if adding a row costs a CLI call each,
    the sweep gets batched or routed around, which is how every gate dies."""
    eng = _eng(a.engagement)
    src = Path(a.file)
    text = src.read_text()
    scan = _scan_tables(text)
    if scan["rejected"]:
        n, first = scan["rejected"][0]
        print(f"REFUSED: {src} -- {len(scan['rejected'])} table row(s) do not parse as ledger "
              f"rows. Nothing was imported.", file=sys.stderr)
        print(f"  first rejected id: {first!r} (line {n})", file=sys.stderr)
        print(f"  ids must match {ROW_RE.pattern} -- a letter, up to five more letters or "
              f"digits, ONE optional hyphen, 1-3 digits and an optional trailing "
              f"lowercase letter: H1, H-01, AB-1, T2H1-16, H-01b.",
              file=sys.stderr)
        print("  Rename the ids in the source file and import again; the row pattern does "
              "not change.", file=sys.stderr)
        print("  If those lines are not rows at all, give their table a header whose first "
              "column is not `id` (e.g. `| # | ... |`) and it will be skipped.", file=sys.stderr)
        return 2
    if scan["ambiguous"]:
        n, first = scan["ambiguous"][0]
        print(f"REFUSED: {src} -- line {n} parses as a ledger row, but it sits in a table whose "
              f"first column is {first!r}, not `id`. Nothing was imported.", file=sys.stderr)
        print("  Rename that header to `id` if these are rows, or move the table out if they "
              "are not.", file=sys.stderr)
        return 2
    if not scan["rows"]:
        print(f"REFUSED: {src} -- no ledger table found: no table whose header starts with "
              f"`id` holds a row. Nothing was imported.", file=sys.stderr)
        for n, what in scan["skipped"]:
            print(f"  skipped table at line {n}: first column {what}", file=sys.stderr)
        return 2
    existing = replay(eng)
    added = 0
    for _, line in scan["rows"]:
        rid = ROW_RE.search(line).group(1)
        if rid in existing:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        append(eng, {"id": rid, "event": CREATE, "status": CREATE_STATUS,
                     "hypothesis": cells[1] if len(cells) > 1 else "",
                     "entry": cells[2] if len(cells) > 2 else "",
                     "invariant": cells[3] if len(cells) > 3 else "",
                     "by": a.by, "imported_from": str(src)})
        existing[rid] = {}
        added += 1
    print(f"imported {added} rows")
    for n, what in scan["skipped"]:
        print(f"  skipped a table at line {n} whose first column is not `id`: {what} -- "
              f"not ledger rows")
    redraw(eng)
    return 0


def cmd_promote(a) -> int:
    eng = _eng(a.engagement)
    rows = replay(eng)
    row = rows.get(a.id)
    if not row:
        sys.exit(f"no such row: {a.id}. Create it first -- rows are never invented by a transition.")
    if a.to not in (WAYPOINT,) + TERMINAL:
        sys.exit(f"unknown status {a.to!r}. One of: {', '.join((WAYPOINT,) + TERMINAL)}")

    text = " ".join(str(v) for v in row["fields"].values())
    dedup = a.dedup or row["fields"].get("dedup")
    errs: list[str] = []

    # THE WAYPOINT. UNTESTED -> CONFIRMED/REFUTED is refused: reaching either implies
    # harness work, and dedup is owed before the spend, not after.
    if a.to in SPEND and row["status"] == CREATE_STATUS:
        errs.append(
            f"G1 [{a.id}] {CREATE_STATUS} -> {a.to} skips {WAYPOINT}. Reaching {a.to} implies "
            f"harness work, and the dedup obligation is owed BEFORE that spend, not after. "
            f"Promote to {WAYPOINT} with a DEDUP: sidecar first.")

    # STATE LOCKING: a discharged precondition is never re-charged. G1 already worked this
    # way by convention (dedup paid at TIER-1 is not re-charged downstream); here it is
    # enforced from the log rather than remembered.
    if a.to == WAYPOINT:
        if "G1" in row["satisfied"]:
            print(f"{a.id}: G1 already discharged (locked) -- not re-charging")
        else:
            errs += check_g1(a.id, dedup, text, eng)
            # G14 (REF-3): a NO-MATCH cleared against section extracts alone. Charged with G1
            # and never separately -- it is part of the same dedup obligation, so State
            # Locking discharges both together.
            errs += check_g14(a.id, dedup, eng)
        # REF-23: not locked, deliberately -- unlike G1/G14 this is not a per-row spend
        # obligation, it is an engagement-wide fact that can regress (someone deletes or
        # edits the header after an earlier row already reached TIER-1), so it is worth
        # re-checking on every promotion rather than discharged once. Shares
        # header_missing_fields with the doctor's engagement-level report (REF-23), so the
        # two can never disagree about what "complete" means.
        header_path = eng / HEADER
        if not header_path.is_file():
            errs.append(f"REF-23 [{a.id}] {HEADER} does not exist. Write it before the first "
                       f"TIER-1 promotion (docs/hypothesis-ledger.md \"The ledger header\").")
        else:
            missing = header_missing_fields(header_path.read_text(errors="ignore"))
            if missing:
                errs.append(f"REF-23 [{a.id}] {HEADER} is missing {', '.join(missing)}.")

    # G2 protects kills, G10 protects claims: same predicate, opposite failure. A REFUTED
    # row with no evidence is an argument-kill; a CONFIRMED row with no evidence is an
    # unbacked finding. SCOPE-HELD must cite a human -- scope is never the model's call.
    if a.to in TERMINAL:
        errs += check_g2(a.id, dedup, a.evidence, a.human, text, a.to, eng)
        # REF-1: and a Forge citation names the test FUNCTION. New promotions only --
        # rows closed before the rule keep passing every check.
        errs += check_evidence_function(a.id, a.evidence, a.to, eng)

    # G12: a Known-Issue match retires the CLAIM, not the row.
    if a.to == "SCOPE-HELD":
        errs += check_g12(a.id, dedup, eng)

    # BELOW-BAR must cite the program bar it fails -- otherwise it is a silent drop.
    if a.to == "BELOW-BAR":
        errs += check_below_bar(a.id, a.reason, dedup, eng)

    # BLOCKED must record why it could not be PoC'd -- same reasoning as BELOW-BAR (REF-22).
    # BLOCKED-OUT-OF-HARNESS takes the same requirement: it was the one exit from the board
    # that recorded no reason at all.
    if a.to in ("BLOCKED", "BLOCKED-OUT-OF-HARNESS"):
        errs += check_blocked(a.id, a.reason, eng, a.to)

    # A kill must state the argument it rests on, not only the file that ran (REF-26).
    # New promotions only, like G15 above.
    if a.to == "REFUTED":
        errs += check_refuted_reason(a.id, a.reason)

    if errs:
        print(f"REFUSED: {a.id} -> {a.to}", file=sys.stderr)
        for e in errs:
            print(f"  {e}", file=sys.stderr)
        # A block is information, not an obstacle: the row is missing evidence the
        # methodology requires. Supply it rather than routing around it.
        return 2

    satisfied = ["G1"] if a.to == WAYPOINT else []
    append(eng, {"id": a.id, "event": "promote", "to": a.to, "dedup": dedup,
                 "evidence": a.evidence, "human": a.human, "reason": a.reason,
                 "satisfied": satisfied, "by": a.by})
    print(f"{a.id} -> {a.to}")
    redraw(eng)
    return 0


def _render_parts(eng: Path) -> tuple[str, str, str]:
    """Split the board into (preamble, header, table). `render_text` joins them, so this
    refactor keeps its output byte-identical to before it. `cmd_verify` uses the split to
    tell a `HEADER.md` change from a hand-edited row apart (#72): it re-renders each part
    fresh and checks which one the on-disk board still starts/ends with.
    """
    rows = replay(eng)
    preamble = "\n".join([
        # The format marker must be line 1: G0c checks for it, and a rendered ledger that
        # omitted it would make the CLI produce a file its own guard family warns about.
        # Caught on the engagement 9 migration, not by a fixture.
        FORMAT_MARKER,
        "<!-- GENERATED by tooling/ledger -- do not edit. Your edits will be overwritten.",
        "     Change state with: python3 tooling/ledger/cli.py promote --id <ID> ... -->",
        "",
    ]) + "\n"

    # REF-23: render used to emit marker + banner + table and NOTHING else, so it silently
    # deleted any header a human had written -- the impact bar, materiality basis, scope
    # exclusions, RUN/CUTOFF provenance bench/ needs to compare one run to another. Compose
    # it in rather than replace it. HEADER.md is a human-owned file the CLI never writes
    # (see is_ledger()'s exclusion in ledger_guard.py -- REF-23's sibling defect: a guard
    # that thought this WAS a ledger table would block hand-editing it).
    header_file = eng / HEADER
    header = header_file.read_text().rstrip("\n") + "\n\n" if header_file.is_file() else ""

    table_lines = [
        "| id | hypothesis | entry point + access | invariant | status | evidence |",
        "|---|---|---|---|---|---|",
    ]
    for rid, row in sorted(rows.items()):
        f = row["fields"]
        # Emit EVERY key the guards parse, not just evidence/dedup. The log stored `human`
        # and `reason` correctly, but the render dropped them -- so a promotion the CLI had
        # just accepted (`--human`, satisfying G2) failed G2 the moment it was rendered, and
        # the only "fix" would have been to hand-edit the render, which G11 forbids. The CLI's
        # output must be able to satisfy the CLI's own guards. Found on engagement 16 2026-09-04.
        parts = []
        if f.get("evidence"):
            parts.append(f"EVIDENCE: {f['evidence']}")
        if f.get("dedup"):
            parts.append(f"DEDUP: {f['dedup']}")
        if f.get("human"):
            parts.append(f"HUMAN: {f['human']}")
        if f.get("reason"):
            parts.append(f"REASON: {f['reason']}")
        ev = " · ".join(parts)
        table_lines.append(f"| {rid} | {f.get('hypothesis','')} | {f.get('entry','')} | "
                           f"{f.get('invariant','')} | `{row['status']}` | {ev} |")
    table = "\n".join(table_lines) + "\n"

    return preamble, header, table


def render_text(eng: Path) -> str:
    preamble, header, table = _render_parts(eng)
    return preamble + header + table


def redraw(eng: Path) -> Path:
    """Write the board so it can never disagree with the log. Every command that appends
    an event calls this -- `render` is now just this, run on demand. A board that only
    updates when someone remembers to run `render` by hand went three days out of date on
    a live contest, missing four hypotheses and every status change since."""
    p = eng / RENDER
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.chmod(0o644)
    p.write_text(render_text(eng))
    p.chmod(0o444)  # read-only: the render is a printout, not the state
    return p


def cmd_render(a) -> int:
    eng = _eng(a.engagement)
    p = redraw(eng)
    print(f"rendered {len(replay(eng))} rows -> {p}")
    return 0


def cmd_verify(a) -> int:
    """Replay and assert the log's own invariants. Run in CI."""
    eng = _eng(a.engagement)
    problems = []
    prev_hash = None
    for e in read_events(eng):
        if e.get("prev") != prev_hash:
            problems.append(f"seq {e.get('seq')}: hash chain broken -- the log was rewritten.")
        prev_hash = e.get("hash")

    rows = replay(eng)
    for rid, row in sorted(rows.items()):
        # State Locking: the satisfied set must be non-decreasing.
        seen: set[str] = set()
        for e in row["history"]:
            for g in e.get("satisfied", []):
                seen.add(g)
        if not seen.issuperset(set(row["satisfied"])):
            problems.append(f"{rid}: satisfied-precondition set decreased (State Locking violated).")
        n = revisits(row)
        if n:
            # Not an error -- the measurement we came for. See design note section 2.
            print(f"  oscillation: {rid} re-entered a prior status {n}x "
                  f"({' -> '.join(status_path(row))})")

    # The one surviving hook check. It does NOT parse the markdown -- it compares the
    # file to a fresh render -- so it cannot be out-run by format drift, which is the
    # 697-line parser guard's whole failure mode.
    rendered = eng / RENDER
    if rendered.exists():
        on_disk = rendered.read_text()
        preamble, header, table = _render_parts(eng)
        if on_disk != preamble + header + table:
            # A HEADER.md written, edited or removed after the last render, and the
            # header text edited directly inside ledger.md, land the board in the exact
            # same state: same preamble, same table, only the header portion differs from
            # a fresh one. There is no way to tell the two apart from the file alone, so
            # they share one message that blames neither -- and points at HEADER.md as
            # the place to fix it, since that's the source render reads from (#72).
            if (on_disk.startswith(preamble) and on_disk.endswith(table)
                    and len(on_disk) >= len(preamble) + len(table)):
                problems.append(
                    f"{RENDER}'s header part does not match {HEADER} -- either {HEADER} "
                    f"was written, edited or removed after the board was last drawn, or "
                    f"the header was edited inside {RENDER}. {HEADER} is the source: put "
                    f"any header text you want to keep there, then run `render` (it "
                    f"overwrites {RENDER}).")
            else:
                problems.append(
                    f"{RENDER} differs from a fresh render -- it was hand-edited. "
                    f"It is GENERATED; change state with `promote`, then re-render.")

    # REF-23: HEADER.md carries the impact bar, materiality basis, scope exclusions and
    # RUN/CUTOFF provenance -- the human scope gate in Phase 4 reads it, and a board with
    # rows but no header cannot be adjudicated. This is a warning, not a failure: the exit
    # code stays whatever it already was, because a missing header is a missing document,
    # not a broken log.
    if rows and not (eng / HEADER).is_file():
        print(f"  warn: {HEADER} is missing -- {len(rows)} rows with no recorded impact "
              f"bar, scope exclusions or RUN provenance. Write it by hand; render composes it in.")

    total_osc = sum(1 for r in rows.values() if revisits(r))
    print(f"{len(rows)} rows, {len(read_events(eng))} events, {total_osc} oscillating")
    for p in problems:
        print(f"  FAIL {p}", file=sys.stderr)
    return 1 if problems else 0


def cmd_phase(a) -> int:
    """Record one phase as `done` or `skipped -- <reason>` (REF-27).

    The doctor has required PHASES.md since 2026-09-25 and nothing ever wrote it, so the
    check fired on 17 of 17 engagements: a requirement with no writer is a check that fires
    forever and then gets ignored, which removes the signal it exists to give.

    Append-only, one line per call, written as each phase ends rather than reconstructed at
    close-out. `parse_phases` takes the LAST line for a phase, so re-recording one corrects
    it without editing anything.
    """
    eng = _eng(a.engagement)
    if a.done and a.skipped:
        sys.exit("pass --done or --skipped, not both.")
    phase = a.done or a.skipped
    if not phase:
        sys.exit(f"pass --done <phase> or --skipped <phase>. Phases: {', '.join(PHASE_IDS)}")
    reason = (a.reason or "").strip()
    # A skip with no reason is indistinguishable from a phase nobody reached, which is the
    # state REF-28 built the check to tell apart. Same shape as the --reason rules on the
    # statuses that take a row off the board.
    if a.skipped and not reason:
        sys.exit(f"Phase {phase} skipped needs --reason naming what was not done and why "
                 f"(e.g. 'no fuzzer on this toolchain'). Without it the record cannot be "
                 f"told from a phase nobody reached.")
    # PHASES.md is line-addressed: the doctor's PHASE_LINE_RE is multiline-anchored, so a
    # newline inside the reason would write further lines this call never claimed, and
    # `--skipped 3 --reason $'x\nPhase 4: done'` would record Phase 4 as done. One record per
    # call is the property; refuse rather than mangle the operator's text.
    if any(c in reason for c in "\r\n"):
        sys.exit("--reason must be a single line: PHASES.md holds one record per line, so a "
                 "newline in it writes phase records this call did not claim.")
    line = f"Phase {phase}: done" if a.done else f"Phase {phase}: skipped -- {reason}"

    p = eng / PHASES_FILE
    if not p.is_file():
        p.write_text(f"# Phases -- {eng.name}\n\nOne line per phase as it ends, written by "
                     f"`tooling/ledger/cli.py phase`.\nA later line for the same phase wins.\n\n")
    with p.open("a") as fh:
        fh.write(line + "\n")
    print(f"{line}  -> {p}")
    return 0


def cmd_count(a) -> int:
    """Read-only: `STATUS N` per status that has rows, in STATUSES order (REF-29's finish
    line -- a script needs a stable place to read "0 UNTESTED" from). Through the same
    replay() verify uses; writes nothing."""
    eng = _eng(a.engagement)
    tally: dict[str, int] = {}
    for row in replay(eng).values():
        tally[row["status"]] = tally.get(row["status"], 0) + 1
    for status in STATUSES:
        if tally.get(status):
            print(f"{status} {tally[status]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="audit ledger")
    ap.add_argument("--engagement")
    ap.add_argument("--by", default="unrecorded",
                    help="model id or human. 'not recorded' is legal; a guessed value is not.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add"); a.add_argument("--id", required=True)
    a.add_argument("--hypothesis", required=True)
    a.add_argument("--entry", default=""); a.add_argument("--invariant", default="")
    a.set_defaults(fn=cmd_add)

    i = sub.add_parser("import"); i.add_argument("file"); i.set_defaults(fn=cmd_import)

    p = sub.add_parser("promote"); p.add_argument("--id", required=True)
    p.add_argument("--to", required=True); p.add_argument("--dedup")
    p.add_argument("--evidence", help="PoC citation that must resolve. A Forge test names the "
                                      "test function too: poc/test/H7.t.sol::test_H7_refuted. "
                                      "Other evidence is a path: .rs / .ts / _test.go / .txt / "
                                      ".log")
    p.add_argument("--human", help="required for SCOPE-HELD -- who ruled, and on what rule")
    p.add_argument("--reason", help="required for BELOW-BAR (the program bar this row fails to "
                                    "clear), BLOCKED / BLOCKED-OUT-OF-HARNESS (why the row "
                                    "could not be PoC'd) and REFUTED (the argument the kill "
                                    "rests on -- what the evidence showed)")
    p.set_defaults(fn=cmd_promote)

    ph = sub.add_parser("phase")
    ph.add_argument("--done", choices=PHASE_IDS, help="this phase ran")
    ph.add_argument("--skipped", choices=PHASE_IDS, help="this phase did not run")
    ph.add_argument("--reason", help="required for --skipped: what was not done, and why")
    ph.set_defaults(fn=cmd_phase)

    sub.add_parser("render").set_defaults(fn=cmd_render)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("count").set_defaults(fn=cmd_count)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
