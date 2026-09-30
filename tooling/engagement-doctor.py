#!/usr/bin/env python3
"""Check an engagement's layout against what the guards actually require.

Why this exists. The guards enforce the layout at the moment it matters -- G0 when a ledger is
written, G1 when a row is promoted. That is correct, but it means you learn about a problem
mid-hunt instead of at setup. One engagement kept its prior art in `00-triage/prior-art/` while
G1 looks for `00-triage/prior-audits/`, and nothing said so until a promotion was attempted.

So: run this once when you start or resume an engagement. It reports every layout fact the guards
care about, names the guard that cares, and `--fix` creates the missing directories.

It also reports one thing NO guard refuses on: whether the target's own documentation was ever
extracted (REF-20). Those rows are marked `GAP` rather than `BAD`, because the doctor is the only
thing checking them -- calling them blocking would be a claim about the guards that is not true.

    tooling/engagement-doctor.py ~/engagements/<name>
    tooling/engagement-doctor.py --all            # every engagement under ~/engagements
    tooling/engagement-doctor.py <dir> --fix      # create missing dirs (never moves data)

`--fix` only ever CREATES empty directories. It never moves, renames or deletes anything: a
misplaced corpus is a judgement call about which files are really prior art, and that is yours.
"""
from __future__ import annotations
import argparse
import json, subprocess, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "guards"))
from ledger_guard import (  # noqa: E402
    FORMAT_MARKER, engagement_ledgers, parse_rows, parse_row_lines, finding_body_files,
    load_sidecar, as_list, header_missing_fields, row_status,
)

# GAP sits between WARN and BAD: it fails the run (exit 2) but is NOT guard-enforced. Keeping it
# distinct is the point -- BAD means a guard will refuse the next TIER-1 promotion, and a row that
# only the doctor checks must not borrow that authority.
OK, WARN, GAP, BAD = "ok", "warn", "GAP", "BAD"
# INFO is an OK-shaped row that is ALWAYS printed. It exists for facts you want most when the
# engagement is messy -- the filing count above all, since an `ok` row is suppressed whenever
# anything else fires, which is precisely when someone would otherwise estimate it from prose.
INFO = "info"
FAILING = (GAP, BAD)
ENGAGEMENTS_ROOT = Path(os.environ.get("AUDIT_ENGAGEMENTS_ROOT", str(Path.home() / "engagements")))

# (relative path, created by --fix?, which guard cares, why)
REQUIRED_DIRS = [   # only what a guard genuinely refuses on

    ("00-triage", True, "G0",
     "every guard keys off this; without it NO guard runs at all, silently"),
    ("00-triage/prior-audits", True, "G1",
     "the corpus itself -- must be non-empty, or 00-triage/NO-PRIOR-ART.md must assert there is none"),
    ("00-triage/potential-risks", True, "G1",
     "verbatim extracts, >=1 .txt -- this is what the identifier cross-check greps"),

    ("poc", True, "G1b", "harnesses; G1b blocks files here until some row is TIER-1"),
]


# ---------------------------------------------------------------- REF-20: the target's own docs
#
# One engagement, cut from this release under a confidentiality agreement, read the prior audits
# and the platform's published Known Issues list exhaustively and never opened the target repo's
# own `docs/` tree. It did not cost recall -- the findings came from code reading -- it cost
# IMPACT CALIBRATION: half the submission severities moved late, and every question that moved
# them (who calls this, how many instances exist, is the system even live) is answered directly in
# the docs. The public site had no section on the audited system at all, so the in-repo tree was
# the only description that existed, and it is the one we skipped.
#
# Checked here rather than as a guard, deliberately. The cost lands at Phase 4/5 severity, not at
# PoC spend, so there is no transition to gate; and nothing on disk today would pass, so a guard
# would block every engagement at once -- the noisy-gate failure the register keeps warning about.
DOC_DIR_NAMES = {"docs", "doc", "documentation", "specs", "spec"}
DOC_TEXT_EXT = {".md", ".mdx", ".txt", ".rst", ".adoc"}
DOC_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".drawio"}
# Never walked: build output and dependencies hold thousands of files and no target documentation.
# `00-triage` is excluded because it holds OUR extracts -- counting them as target docs would let
# the check satisfy itself.
DEPENDENCY_DIRS = {"node_modules", "lib", "libs", "foundry-lib", "out", "output", "cache",
                   "artifacts", "target", "build", "dist", "coverage", "venv", "__pycache__",
                   "broadcast", "typechain", "typechain-types"}
# OUR working directories, not the target's. Pruning them is what stops the check reading our own
# notes as the target's documentation -- engagement 1's PoC attachment bundles each carry a manifest
# and were being counted as separate checkouts.
ENGAGEMENT_DIRS = {"00-triage", "01-scope", "02-static", "05-submission", "ledger", "hunt", "poc",
                   "poc-snapshot", "submissions", "review", "findings", "kill", "hunters",
                   "harness", "diagrams", "rows", "prior-audit", "prior-audits"}
DOC_PRUNE = DEPENDENCY_DIRS | ENGAGEMENT_DIRS
# A directory holding one of these is a code checkout. Anchoring on the checkout is what keeps the
# check honest: the first version counted `02-static/README.md` and `hunt/stage-a/README.md` --
# files WE wrote -- as target documentation, and a dependency's README as well.
MANIFESTS = {"foundry.toml", "package.json", "hardhat.config.js", "hardhat.config.ts",
             "Cargo.toml", "go.mod", "Anchor.toml", "truffle-config.js", "remappings.txt"}
CHECKOUT_MAX_DEPTH = 3
PROTOCOL_DOCS = "00-triage/protocol-docs"
NO_DOCS_MARKER = "00-triage/NO-PROTOCOL-DOCS.md"
# Mirrors ledger_state_guard.ACTIVE_WINDOW_S. Only applied in --all mode: a closed engagement
# cannot promote a row, and reporting its docs gap every session is how a hook gets muted.
ACTIVE_WINDOW_S = 24 * 60 * 60


def checkout_roots(eng: Path) -> list[Path]:
    """The target's own code checkouts inside the engagement, outermost first.

    Outermost wins: a monorepo package with its own `package.json` is part of one target, not a
    second one, and descending into it re-admits every dependency README we just pruned.
    """
    roots = []
    for dirpath, dirnames, filenames in os.walk(eng):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in DOC_PRUNE and not d.startswith("."))
        if len(here.relative_to(eng).parts) >= CHECKOUT_MAX_DEPTH:
            dirnames[:] = []
        if any(m in filenames for m in MANIFESTS):
            roots.append(here)
            dirnames[:] = []
    return roots


def target_docs(eng: Path) -> tuple[list[Path], list[Path]]:
    """Documentation shipped by the TARGET's own checkouts: (text files, image/PDF files).

    Two sources, both named by `skill/phases/phase-1-hunt.md` step 3: any `docs/`-shaped directory inside a
    checkout, and the README at the checkout root. Returned separately because an image-only docs
    tree cannot be extracted by any script -- engagement 4 ships twelve PNG diagrams and no text at all.
    """
    texts, images = [], []
    for root in checkout_roots(eng):
        for fn in os.listdir(root):
            if fn.lower().startswith("readme") and Path(fn).suffix.lower() in DOC_TEXT_EXT:
                texts.append(root / fn)
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if d not in DOC_PRUNE and not d.startswith("."))
            if not any(part.lower() in DOC_DIR_NAMES for part in here.relative_to(root).parts):
                continue
            for fn in filenames:
                ext = Path(fn).suffix.lower()
                if ext in DOC_TEXT_EXT:
                    texts.append(here / fn)
                elif ext in DOC_IMAGE_EXT:
                    images.append(here / fn)
    return sorted(set(texts)), sorted(set(images))


def _sample(paths: list[Path], eng: Path, n: int = 2) -> str:
    shown = ", ".join(str(p.relative_to(eng)) for p in paths[:n])
    return shown + (f", +{len(paths) - n} more" if len(paths) > n else "")


def check_protocol_docs(eng: Path) -> list[tuple[str, str, str]]:
    """REF-20. Did anyone extract the target's own documentation?"""
    if (eng / NO_DOCS_MARKER).exists():
        return [(OK, f"{NO_DOCS_MARKER} asserts the target ships no usable docs", "")]

    if not checkout_roots(eng):
        return [(WARN, "no target checkout inside the engagement — docs check could not run",
                 "[REF-20] nothing here holds a foundry.toml/package.json/Cargo.toml, so this check "
                 "is inert for this engagement. Saying so beats staying silent, which would read "
                 "as a pass.")]

    texts, images = target_docs(eng)
    if not texts and not images:
        return []                       # nothing to read; saying so every run would be pure noise

    extracts = sorted((eng / PROTOCOL_DOCS).glob("*")) if (eng / PROTOCOL_DOCS).is_dir() else []
    extracts = [f for f in extracts if f.suffix.lower() in DOC_TEXT_EXT]
    if extracts:
        detail = (f"[REF-20] {len(images)} image/PDF doc file(s) carry no text and are not covered "
                  f"by an extract: {_sample(images, eng)}") if images else ""
        return [(WARN if images else OK,
                 f"{PROTOCOL_DOCS}/: {len(extracts)} extract(s) for {len(texts)} target doc file(s)",
                 detail)]

    if not texts:                        # image-only: no script can extract these
        return [(WARN, f"target ships {len(images)} image/PDF doc file(s) and no text",
                 f"[REF-20] nothing to extract mechanically, so someone has to LOOK at them: "
                 f"{_sample(images, eng)}. Record what they say in {PROTOCOL_DOCS}/.")]

    extra = f" (plus {len(images)} image/PDF)" if images else ""
    return [(GAP, f"target's own docs were never extracted — {len(texts)} file(s){extra}",
             f"[REF-20] e.g. {_sample(texts, eng)}. Nothing else checks this, and skipping it has "
             f"cost impact calibration on half the submissions of a real engagement. Extract to "
             f"{PROTOCOL_DOCS}/, or add {NO_DOCS_MARKER}.")]


def check_ledger_is_cli_managed(eng: Path) -> list[tuple[str, str, str]]:
    """Does this engagement's ledger state live in the event log yet?

    The bootstrap half of G11. Once `ledger/events.jsonl` exists, G11 refuses any direct
    edit to a ledger markdown file -- that half is binding. But an engagement that never
    creates the log is invisible to it: there is nothing to compare against, so the agent
    can ignore `tooling/ledger` entirely and nothing errors.

    GAP, not BAD: no guard refuses on this, and saying otherwise would be the same
    register-vs-code disagreement that left G4-G9 with rows and no implementation.
    """
    events = eng / "ledger" / "events.jsonl"
    ledgers = engagement_ledgers(eng)
    if events.exists():
        n = sum(1 for line in events.read_text().splitlines() if line.strip())
        stale = [l for l in ledgers if l.name != "ledger.md"]
        if stale:
            return [(WARN, f"ledger is CLI-managed ({n} events) but {len(stale)} pre-migration "
                           f"file(s) remain",
                     f"[G11] {_sample(stale, eng)} still on disk. Two ledger files is two sources "
                     f"of truth -- import what is missing, then delete the old file. G11 blocks "
                     f"edits to it meanwhile.")]
        return [(OK, f"ledger is CLI-managed ({n} events)", "")]
    if not ledgers:
        return []                        # nothing scaffolded yet; new-engagement.sh covers it
    return [(GAP, "ledger state is not in an event log — the CLI is not being used",
             f"[G11] `skill/SKILL.md` says every row and status change goes through "
             f"tooling/ledger, and until ledger/events.jsonl exists NOTHING enforces that: "
             f"G11 has nothing to compare against, so a hand-edited table looks normal. "
             f"Migrate with `cli.py import {_sample(ledgers, eng)}`, then `render`. "
             f"`import` refuses the whole file if any table row in it fails the row pattern "
             f"(REF-21), so a ledger that also holds a coverage map or summary table has to "
             f"be split first -- 5 of the 27 ledger files on disk are in that shape.")]


def check_filings(eng: Path) -> list[tuple[str, str, str]]:
    """Report how many rows were FILED and how many only DRAFTED (O-9).

    The guard half (G13) refuses `SUBMITTED` and a `FILED:` with no URL. This is the half that
    would actually have prevented the error: it makes the filing count MECHANICAL. engagement 2's
    four-fold overstatement did not come from a malformed status cell -- it came from a human
    reading prose bullets and summarising "4 SUBMITTED" into `bench/engagements.md`. A count
    nobody can compute gets estimated, and an estimate about our own past is what CLAUDE.md
    rule 3 says to stop doing.

    Reports OK, not WARN: having zero filings is the normal state for most of an engagement,
    and a check that complained about it would fire constantly.
    """
    filed, drafted = [], []
    for led in engagement_ledgers(eng):
        try:
            content = led.read_text(errors="replace")
        except OSError:
            continue
        for rid, line in parse_row_lines(content).items():
            if re.search(r"\bFILED:", line, re.I):
                filed.append(rid)
            elif re.search(r"\bDRAFTED:", line, re.I):
                drafted.append(rid)
    if not filed and not drafted:
        return []
    detail = (f"FILED: {', '.join(filed) or 'none'} · DRAFTED: {', '.join(drafted) or 'none'}. "
              f"[O-9] Filing counts come from here, never from prose — reading a summary is how "
              f"engagement 2's filing history was overstated four-fold.")
    return [(INFO, f"{len(filed)} filed, {len(drafted)} drafted", detail)]


def check_statusless_rows(eng: Path) -> list[tuple[str, str, str]]:
    """WARN on row-shaped lines that carry no status token — they are invisible to EVERY guard.

    Found 2026-09-08 while scoring engagement 2. `parse_rows` deliberately requires a status token,
    because side tables (a hunter roster, a dedup matrix) otherwise parse as ledger rows. The
    cost of that rule was never checked in the other direction: a REAL hypothesis table with
    no status column parses as nothing, and every guard keyed on `parse_rows` skips it in
    silence.

    engagement 2's `LEDGER.md` has 36 row-shaped lines and 29 a guard can see. The seven invisible
    ones are H18-H24 — **including H21**, the five-hypothesis bundle that swallowed the live
    residue of the refuted H28, which was the contest's valid M-2. So the single most costly
    row in that engagement sat outside every guard in this repo, and nothing said so.

    G0b cannot catch this: it fires only when a file parses ZERO rows, and this file parses 29.

    THIS CHECK REPORTS; IT DOES NOT FIX. The guards still cannot see these rows, and loosening
    `parse_rows` is the wrong fix: the status requirement exists because side tables (a hunter
    roster, a dedup matrix) otherwise parse as ledger rows, and engagement 8's roster once
    parsed as 8 phantom rows -- which SUPPRESSED G0b, since that fires only at zero parsed rows.
    Loosening trades one silent failure for another.

    The right fixes are (a) give the row a status cell, `UNTESTED` being the honest default, or
    (b) move the table under the ledger CLI, where every row has a status by construction. A
    CLI-managed engagement never trips this check. Commit b3868c5 is the third, narrowest fix and
    a worked example: adding the legitimate `BELOW-BAR` status to the recognised list made 11
    rows visible across three engagements without touching the parser -- and dropped this check
    from 8 affected engagements to 5, all of them hand-written.
    """
    hits = []
    for led in engagement_ledgers(eng):
        try:
            content = led.read_text(errors="replace")
        except OSError:
            continue
        blind = sorted(set(parse_row_lines(content)) - set(parse_rows(content)))
        if blind:
            hits.append((led.name, blind))
    if not hits:
        return []
    detail = "; ".join(f"{name}: {', '.join(ids[:8])}"
                       + (f" (+{len(ids) - 8} more)" if len(ids) > 8 else "")
                       for name, ids in hits)
    n = sum(len(ids) for _, ids in hits)
    return [(WARN, f"{n} row-shaped line(s) carry no status — invisible to every guard",
             f"[G0b family] {detail}. A guard keyed on parse_rows cannot see these, and G0b "
             f"only fires when a file parses ZERO rows, so a partly-statusless ledger looks "
             f"healthy. Add a status cell (UNTESTED is the honest default) or move the table "
             f"under the ledger CLI.")]


def check_bundled_rows(eng: Path) -> list[tuple[str, str, str]]:
    """WARN on rows that appear to assert several independent hypotheses at once.

    Why this is worth a check. engagement 2's H21 packed five unrelated mechanisms into one row
    -- including the live residue of the correctly-refuted H28, which was the contest's
    valid M-2 -- and the whole bundle died on a single prose scope note. The cost is
    double, and the second half was a surprise: a human cannot triage a bundle, AND the
    semantic matcher cannot see the valid fragment inside it. The gate-passing grader
    rejected H21 unprompted as a "multi-issue bundle" (bench/w6-conversion-result.md).

    WARN and never BAD, on measurement. Across the 224 rows on disk this predicate fires on
    7.1% -- 21% on engagement 2, 0% on engagement 12, engagement 15 and engagement 6 -- so it is quiet where the
    problem is absent, which is the property a gate needs (CLAUDE.md: "a gate that fires
    often gets disabled"). But reading the 8 engagement 2 hits by hand, only about half are real
    bundles; H25 and H27 are single mechanisms narrated across clauses. **Roughly 50%
    precision is not good enough to refuse anything**, and the honest fix is structural:
    one (contract, function, bug_class) triple per row, which conduct.py already forces on
    hunter rows and which belongs in the ledger schema. That is HR-C, not this.
    """
    hits = []
    for led in engagement_ledgers(eng):
        try:
            # parse_row_lines, NOT parse_rows: the row this check exists for (engagement 2's H21)
            # sits in a table with no status column and is invisible to parse_rows. Using
            # the stricter parser here would silently exempt exactly the case that motivated
            # the check. See check_statusless_rows below.
            rows = parse_row_lines(led.read_text(errors="replace"))
        except OSError:
            continue
        for rid, line in rows.items():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            hyp = cells[1]
            if len(hyp) >= 25 and hyp.count(";") >= 2:
                hits.append(f"{led.name}:{rid}")
    if not hits:
        return []
    return [(WARN, f"{len(hits)} row(s) may bundle several hypotheses",
             f"[REF-2 family] {', '.join(hits[:6])}"
             + (f" (+{len(hits) - 6} more)" if len(hits) > 6 else "")
             + ". A row asserting several mechanisms is retired as a unit, so one scope "
               "note kills all of them, and a matcher cannot see the valid fragment "
               "inside. Split each into its own row. Advisory only -- this predicate is "
               "about 50% precise, so read them rather than trusting it.")]


def check_finding_bodies(eng: Path) -> list[tuple[str, str, str]]:
    """WARN when the corpus holds prior-audit finding BODIES that no dedup has ever searched.

    Same predicate as G14, reported earlier. G14 refuses one row at the moment it is promoted;
    this says the same thing at session start, before any spend, and for the engagement as a
    whole -- which is when it is cheap to fix, because fixing it means grepping a file.

    Measured across the 24 engagements on disk: fires on ONE (engagement 16), where all 7 sidecars
    searched only the Notes and Trust Model extracts while 12 full reports sat unread in
    prior-audits-text/. WARN and not BAD: no guard refuses on the engagement-level fact, and a
    doctor row must not borrow authority the guards do not have.
    """
    dd = eng / "ledger" / "dedup"
    side = sorted(dd.glob("*.md")) if dd.is_dir() else []
    if not side:
        return []
    bodies = finding_body_files(eng)
    if not bodies:
        return []
    wanted = set()
    for b in bodies:
        try:
            wanted.add(b.resolve())
        except OSError:
            continue
    # Read the sidecar the way G14 does -- load_sidecar + as_list, never a line regex.
    # An earlier version matched `- <text>` lines, which disagreed with G14 in BOTH
    # directions: a flow-style `searched: [a, b]` produced a WARN claiming "G14 will refuse
    # the next promotion" when G14 in fact passes, and a body path quoted inside a
    # `notes: |` block silenced the WARN while G14 fired. A doctor row that contradicts the
    # guard it names is worse than no row.
    for sc in side:
        data, err = load_sidecar(str(sc.relative_to(eng)), eng)
        if err == "__NOYAML__":
            return []                      # cannot read any sidecar; say nothing rather than guess
        if err or not data:
            continue
        for sp in as_list(data.get("searched")):
            c = Path(sp)
            cand = c if c.is_absolute() else (eng / c)
            try:
                if cand.resolve() in wanted:
                    return []
            except OSError:
                continue
    names = [str(b.relative_to(eng)) for b in bodies]
    return [(WARN, f"{len(side)} dedup sidecar(s), none searched a finding BODY",
             f"[G14/REF-3] potential-risks/ holds SECTION extracts; extract_prior_art.py stops "
             f"at \"Findings\" by design, so a finding whose title names another subsystem "
             f"cannot match there. Unsearched: {', '.join(names[:3])}"
             + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")
             + ". G14 will refuse the next NO-MATCH promotion on this engagement.")]


def recently_active(eng: Path) -> bool:
    """Did this engagement's ledger change inside the active window? Same rule, same reason, as
    `ledger_state_guard._recently_active`."""
    now = time.time()
    try:
        return any(now - f.stat().st_mtime < ACTIVE_WINDOW_S for f in engagement_ledgers(eng))
    except OSError:
        return False

# The row generators, and the state that makes each one APPLICABLE. A generator earns a
# prompt only when the engagement already holds the thing it reads -- otherwise the doctor
# would nag every engagement about a tool that has nothing to work on.
#
# Hunter files live in BOTH `hunters/` and `01-hunt/` on disk (engagement 8 uses the
# first, engagement 14's 48 files and engagement 17 use the second), so both are checked. Taking
# opposite-tail.py's docstring at its word would have made this check silent on the two
# engagements with the most hunter files.
GENERATORS = (
    ("refutation-critic", "tooling/refutation-critic.py <engagement>"),
    ("opposite-tail", "tooling/opposite-tail.py <hunter files>"),
    ("fix-adjacency", "tooling/fix-adjacency.py --prior 00-triage/prior-audits-text --src <scope>"),
)


def _generator_ran(eng: Path, name: str) -> bool:
    """Did this generator produce anything here? Output file OR an attributed ledger row.

    `bench/PREREG-generator-conversion.md` fixes the convention that a generator writes to a
    file whose basename STARTS WITH the generator's name, which is what makes its rows
    attributable through `imported_from` with no schema change. So the same prefix answers
    both questions: did it run, and did its rows reach the ledger.
    """
    for p in eng.rglob(f"{name}*"):
        if p.is_file() and "code" not in p.relative_to(eng).parts:
            return True
    events = eng / "ledger" / "events.jsonl"
    if events.is_file():
        for line in events.read_text(errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                src = json.loads(line).get("imported_from") or ""
            except json.JSONDecodeError:
                continue
            if Path(src).name.startswith(name):
                return True
    return False


def check_generators_unrun(eng: Path) -> list[tuple[str, str, str]]:
    """GAP when a generator has material to read and has never been run here.

    WHY A CHECK AND NOT PROSE. All three generators are Phase-1/Phase-3 steps described in
    `skill/SKILL.md`, and CLAUDE.md's layering table is blunt about what that buys: prose is
    advisory, and this repo has measured prose rules decaying within a session. This is the
    SCRIPT layer -- it reports, it does not gate. Row creation stays ungated (CLAUDE.md
    constraint 1), and nothing here refuses a promotion.

    WHY IT MATTERS NOW. `bench/PREREG-generator-conversion.md` decides whether each generator
    is kept or retired, and it needs them to have RUN on two engagements. At the time of
    writing the count is zero -- not because the prompt failed, but because all three landed
    on 2026-09-14 and no engagement has reached them yet. A generator that is never run is
    never scored, and a generator that is never scored never gets retired.

    GAP, not BAD: no guard refuses on this. It is rationed the same way the other GAPs are --
    `check()` only calls it when `docs=True`, which in --all mode means recently-active
    engagements, so a closed engagement does not re-litigate a tool that shipped after it.
    """
    refuted = sum(1 for led in engagement_ledgers(eng)
                  for line in parse_rows(led.read_text(errors="ignore")).values()
                  if "REFUTED" in line)
    # A generator's own output lands in 01-hunt/ too, and it is NOT a hunter file. Without
    # this filter, running refutation-critic would silence its own prompt and simultaneously
    # raise opposite-tail's -- an engagement with no hunter files at all would be told to run
    # a tool that reads them. Found by the test, not by reading the code.
    hunter_files = [f for d in ("hunters", "01-hunt") for f in (eng / d).glob("*.md")
                    if not f.name.startswith(tuple(n for n, _ in GENERATORS))]
    prior_text = list((eng / "00-triage/prior-audits-text").glob("*.txt")) + \
                 list((eng / "00-triage/prior-audits-text").glob("*.md"))
    material = {"refutation-critic": (refuted, f"{refuted} REFUTED row(s)"),
                "opposite-tail": (len(hunter_files), f"{len(hunter_files)} hunter file(s)"),
                "fix-adjacency": (len(prior_text), f"{len(prior_text)} prior-audit text file(s)")}

    # ONE row, not one per generator. Three GAPs each carrying the same three-line
    # explanation is how a check earns itself a place on the ignore list -- CLAUDE.md,
    # "a gate that fires often gets disabled". The commands go in the detail; the shared
    # reason is said once.
    pending = [(name, cmd, material[name][1]) for name, cmd in GENERATORS
               if material[name][0] and not _generator_ran(eng, name)]
    if not pending:
        return []
    what = ", ".join(w for _, _, w in pending)
    cmds = "; ".join(f"`{cmd}`" for _, cmd, _ in pending)
    return [(GAP, f"{len(pending)} row generator(s) never run here — {what} to read",
             f"[B2/B3] {cmds}. Rows import as UNTESTED through the ledger CLI and are "
             f"attributable only if the output filename starts with the generator's name "
             f"(bench/PREREG-generator-conversion.md). Until each has run on two "
             f"engagements there is nothing to keep or retire it on.")]


# --------------------------------------------------- generated rows missing from the ledger
#
# engagement 18: `fix-adjacency.py --json` wrote 73 rows to `01-hunt/fix-adjacency.rows.json`
# and nobody ever imported them. `check_generators_unrun` above only asks "did the generator
# run" -- an output file existing was enough to silence it, even though every one of those 73
# rows sat outside the ledger. This asks the question that check does not: of the rows a
# generator actually wrote, how many never reached the ledger.
GEN_ROWS_GLOBS = ("*.rows.json", "*.rows.md")


def _rows_file_ids(path: Path) -> tuple[list[str | None] | None, str | None]:
    """The ids in one `01-hunt/*.rows.{json,md}` file, or (None, reason) if its shape could
    not be read at all. Returning None rather than [] is the point (REF-21): a file this
    cannot parse must be reported as its own line, never silently counted as zero missing.

    `.md` is read as a literal ledger table (`parse_row_lines`) -- the shape `--emit-ledger`
    produces, and the shape `import` itself reads, so an id found here is directly comparable
    to a ledger id with no translation. `.json` has no such convention: fix-adjacency's
    `{claims, functions_indexed, rows}` and opposite-tail's bare list both emit rows with NO
    `id` field today. Those rows come back as None, one per row, and the caller counts them
    against the rows the ledger imported from that generator -- they cannot be matched by id.
    A row that DOES carry an `id` (conduct.py's `.rows.json` sidecar, refutation-critic's
    `--json`, which briefs EXISTING ledger rows) uses it directly.
    """
    if path.suffix == ".md":
        return list(parse_row_lines(path.read_text(errors="ignore")).keys()), None
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"could not be read ({e})"
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("rows"), list):
        items = data["rows"]                       # fix-adjacency's {claims, ..., rows}
    else:
        return None, "could not be read (not a list of rows, and no 'rows' list found)"
    if not all(isinstance(r, dict) for r in items):
        return None, "could not be read (row elements are not objects)"
    return [str(r["id"]) if r.get("id") else None for r in items], None


def _rows_imported_from(eng: Path, prefix: str) -> int:
    """How many distinct ledger rows `cli.py import` created from a file whose basename
    starts with `prefix` -- the generator-name attribution `_generator_ran` also uses."""
    events = eng / "ledger" / "events.jsonl"
    if not events.is_file():
        return 0
    ids = set()
    for line in events.read_text(errors="ignore").splitlines():
        try:
            ev = json.loads(line) if line.strip() else {}
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "created" and \
                Path(ev.get("imported_from") or "").name.startswith(prefix):
            ids.add(ev.get("id"))
    return len(ids)


def check_generated_rows_unimported(eng: Path) -> list[tuple[str, str, str]]:
    """GAP when a generator's own output file holds rows the ledger has never seen.

    ONE row bundling every offending file, not one GAP per file -- the same reasoning as
    check_generators_unrun: a check that speaks once per generator earns itself a place on
    the ignore list (CLAUDE.md, "a gate that fires often gets disabled").
    """
    hunt = eng / "01-hunt"
    if not hunt.is_dir():
        return []
    files = sorted({f for g in GEN_ROWS_GLOBS for f in hunt.glob(g)})
    if not files:
        return []

    ledger_ids: set[str] = set()
    for led in engagement_ledgers(eng):
        ledger_ids |= set(parse_row_lines(led.read_text(errors="ignore")))

    lines = []
    for f in files:
        ids, err = _rows_file_ids(f)
        if err:
            lines.append(f"{f.name}: {err}")
            continue
        if not ids:
            continue
        real_ids = [i for i in ids if i is not None]
        missing = [i for i in real_ids if i not in ledger_ids]
        if missing:
            lines.append(f"{f.name}: {len(missing)} of {len(real_ids)} ids not in the ledger")
        # Id-less rows have nothing to match, so matching them by id reported engagement 18's 73
        # rows missing even after all 73 were imported (as FA-1..FA-73, via a hand-converted
        # sibling .rows.md). Count them against the rows imported from any file carrying
        # this generator's name instead.
        id_less = len(ids) - len(real_ids)
        if id_less:
            shortfall = id_less - _rows_imported_from(eng, f.name.split(".rows")[0])
            if shortfall > 0:
                lines.append(f"{f.name}: {shortfall} of {id_less} rows not in the ledger")
    if not lines:
        return []
    return [(GAP, f"{len(lines)} generated-row file(s) under 01-hunt/ need attention",
             f"[B2/B3] {'; '.join(lines)}. Import through the ledger CLI, or -- for a "
             f"'.json' file with no id field -- nothing can import it until the generator "
             f"emits an importable table (see fix-adjacency.py --emit-ledger).")]


# ----------------------------------------------------------- poc/ empty with rows on the board
#
# REF-22's first, simple form (bench/improvement-backlog.md, decided 2026-09-24): `UNTESTED`
# is used as a resting state and nothing notices. The full check REF-22 asks for reads every
# row's status against the four legitimate exits; this is the narrower, cheaper fact that
# does not need that taxonomy at all -- if the ledger holds rows and poc/ holds NOTHING,
# every row on the board was closed by argument, which the repo's first immovable rule
# forbids outright. Deliberately does not attempt the rest of REF-22 (out of scope, this run).
def check_poc_empty(eng: Path) -> list[tuple[str, str, str]]:
    """GAP when the ledger has rows and poc/ holds no files (recursively; dotfiles ignored).

    Must not fire on an empty ledger -- G1b already covers the other direction (poc/ files
    before any row reaches TIER-1), and a fresh engagement that has not started hunting yet
    is not evidence of anything.
    """
    total = sum(len(parse_rows(led.read_text(errors="ignore"))) for led in engagement_ledgers(eng))
    if not total:
        return []
    poc = eng / "poc"
    files = []
    if poc.is_dir():
        for root, dirs, filenames in os.walk(poc):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files += [f for f in filenames if not f.startswith(".")]
    if files:
        return []
    return [(GAP, f"{total} row(s), 0 files under poc/",
             "[REF-22 first form] every row on the board was closed by argument, not evidence -- "
             "the repo's first immovable rule ('no argument-kills') forbids this outright. "
             "Write a harness, or if hunting has not reached PoC yet, this is expected -- "
             "it clears the moment anything lands under poc/.")]


# ------------------------------------------------------- REF-22: UNTESTED past close-out
#
# The full form of the check above: at close-out, EVERY legitimate way off the board forces
# a reason into a field -- REFUTED (evidence), BLOCKED (a reason, since slice 1), SCOPE-HELD
# (--human), BELOW-BAR (a reason). UNTESTED is the one status that needs none, so it is the
# one a prose argument can hide in. Two sightings a month apart (engagement 1 REF-6, then a second
# engagement cut from this release, REF-22) were both rows argued away in prose and left UNTESTED; Rich
# caught the second by hand and all three were refuted by real tests in about twenty minutes.
#
# The boundary is fixed by Rich, not inferred: an engagement has reached close-out once it
# has a submissions/ directory OR any CONFIRMED row. Before that, UNTESTED is the design --
# Phases 1-2 generate wide and suppress nothing (CLAUDE.md, "never gate row CREATION") -- so
# this must stay silent, or it would throttle the sweep it must not gate.
def check_untested_at_closeout(eng: Path) -> list[tuple[str, str, str]]:
    """GAP once the engagement has reached close-out and any ledger row is still UNTESTED.

    Silent before close-out, and silent at close-out with zero UNTESTED rows -- a GAP here
    is not the normal state, it is the one REF-22 exists to surface.

    Keyed by `led.name:rid`, not bare `rid` -- the same namespacing check_bundled_rows
    already uses, and for the same reason: engagement 3's EX-3 sits UNTESTED in ledger.md and
    SCOPE-HELD in composition-pass.md, a real collision on disk, not a hypothetical. Merging
    on the bare id and keeping the first-seen status would silently drop whichever file's
    reading lost the race -- exactly the silent argument-kill this check exists to catch.
    """
    statuses: dict[str, str] = {}
    for led in engagement_ledgers(eng):
        content = led.read_text(errors="ignore")
        for rid, line in parse_rows(content).items():
            statuses[f"{led.name}:{rid}"] = row_status(line)
    if not statuses:
        return []
    past_closeout = (eng / "submissions").is_dir() or "CONFIRMED" in statuses.values()
    if not past_closeout:
        return []
    untested = sorted(key for key, st in statuses.items() if st == "UNTESTED")
    if not untested:
        return []
    return [(GAP, f"{len(untested)} row(s) still UNTESTED past close-out: {', '.join(untested)}",
             "[REF-22] the four legitimate exits are REFUTED (with evidence), BLOCKED (with a "
             "--reason), SCOPE-HELD (with --human) and BELOW-BAR (with a --reason). UNTESTED "
             "is the one that needs none, so a hypothesis argued away in prose and never "
             "tested can sit here and nothing notices.")]


# --------------------------------------------------------------------- which phases ran
#
# engagement 18 skipped Phase 2 (static analysis) and Phase 3 (PoC) and nothing on disk
# said so. Phase list taken from skill/SKILL.md's own headings -- never invented separately,
# so the two cannot drift into naming different phases.
PHASES = ["-1", "0", "1", "2", "3", "4", "5"]
PHASES_FILE = "PHASES.md"
# The reason is whatever trails "done"/"skipped" on the line -- captured whole, in whatever
# punctuation someone used ("— reason", ": reason", ", reason", "(reason)", "due to reason",
# or a bare trailing "."), and cleaned up in `_clean_phase_reason` below. Found in review: the
# first version only recognised a leading -/–/—/: separator, so "skipped (no tooling)" or
# "skipped, no tooling" read as carrying NO reason at all -- indistinguishable from a skip
# that never explained itself.
PHASE_LINE_RE = re.compile(r"(?m)^[ \t]*Phase\s+(-1|[0-5])\s*:\s*(done|skipped)\b[ \t]*(.*?)[ \t]*$",
                           re.I)
_PHASE_REASON_LEADER_RE = re.compile(r"^[-–—:,;]+\s*")


def _clean_phase_reason(raw: str) -> str:
    r = _PHASE_REASON_LEADER_RE.sub("", raw.strip())
    if r.startswith("(") and r.endswith(")"):
        r = r[1:-1].strip()
    return r.rstrip(".").strip()


def parse_phases(text: str) -> dict[str, tuple[str, str]]:
    """phase -> (done|skipped, reason). A later line for the same phase wins, so a correction
    made by re-writing the file (not editing in place) still reads as the current answer."""
    out: dict[str, tuple[str, str]] = {}
    for m in PHASE_LINE_RE.finditer(text):
        out[m.group(1)] = (m.group(2).lower(), _clean_phase_reason(m.group(3)))
    return out


def check_phases_recorded(eng: Path) -> list[tuple[str, str, str]]:
    """GAP once the ledger holds a row unless PHASES.md accounts for every phase.

    Silent before the first row: a fresh engagement has not reached anywhere to report from.
    """
    total = sum(len(parse_rows(led.read_text(errors="ignore"))) for led in engagement_ledgers(eng))
    if not total:
        return []
    p = eng / PHASES_FILE
    if not p.is_file():
        return [(GAP, f"{total} ledger row(s), no {PHASES_FILE}",
                 f"[SKILL.md phases] one line per phase (-1, 0, 1, 2, 3, 4, 5), each `done` or "
                 f"`skipped — <reason>`. engagement 18 skipped Phase 2 and Phase 3 and "
                 f"nothing recorded it.")]
    parsed = parse_phases(p.read_text(errors="ignore"))
    problems = []
    missing = [ph for ph in PHASES if ph not in parsed]
    if missing:
        problems.append(f"missing: {', '.join(f'Phase {m}' for m in missing)}")
    unreasoned = [ph for ph, (status, reason) in parsed.items() if status == "skipped" and not reason]
    if unreasoned:
        problems.append(f"skipped with no reason: {', '.join(f'Phase {m}' for m in unreasoned)}")
    if not problems:
        return []
    return [(GAP, f"{PHASES_FILE} is incomplete", f"[SKILL.md phases] {'; '.join(problems)}")]


# -------------------------------------------------------------- REF-23: the ledger header
def check_ledger_header(eng: Path) -> list[tuple[str, str, str]]:
    """BAD once the ledger holds a row unless ledger/HEADER.md exists and carries all four
    required fields. Sixteen rows went into engagement 18's ledger with no header at all.

    BAD, not GAP -- deliberately unlike the other three checks added alongside this one.
    The predicate is `ledger_guard.header_missing_fields`, shared with `cli.py`'s
    promote-to-TIER-1 precondition: a `promote --to TIER-1` genuinely IS refused while this
    fires, on any row (a fresh one can always be created -- row creation is ungated), so
    calling it GAP would make `status_line()` print "no guard refuses on this" about a fact
    a guard demonstrably does refuse on. Found in review: a same-branch commit wired the
    guard AFTER this check was first written as GAP, and the level was never revisited.
    """
    total = sum(len(parse_rows(led.read_text(errors="ignore"))) for led in engagement_ledgers(eng))
    if not total:
        return []
    header = eng / "ledger" / "HEADER.md"
    if not header.is_file():
        return [(BAD, f"{total} ledger row(s), ledger/HEADER.md does not exist",
                 "[REF-23] blocks every TIER-1 promotion (cli.py). IMPACT BAR, MATERIALITY, RUN "
                 "and CUTOFF are read by the Phase 4 scope gate and by bench/ to compare one run "
                 "to another. Write it by hand (docs/hypothesis-ledger.md \"The ledger header\") "
                 "-- `cli.py render` composes it into the board, it never generates it.")]
    missing = header_missing_fields(header.read_text(errors="ignore"))
    if not missing:
        return []
    return [(BAD, f"ledger/HEADER.md is missing {', '.join(missing)}",
             "[REF-23] blocks every TIER-1 promotion (cli.py). \"not recorded\" is a legal value "
             "for any of these (an honest gap); the field being absent from the file entirely "
             "is not.")]


def check(eng: Path, docs: bool = True) -> list[tuple[str, str, str]]:
    """Returns [(level, headline, detail)]. `docs=False` skips the REF-20 check."""
    out = []
    for rel, _, guard, why in REQUIRED_DIRS:
        p = eng / rel
        if p.is_dir():
            out.append((OK, f"{rel}/", ""))
        else:
            out.append((BAD, f"{rel}/ MISSING", f"[{guard}] {why}"))

    out += check_filings(eng)
    out += check_statusless_rows(eng)
    out += check_bundled_rows(eng)
    out += check_finding_bodies(eng)

    pa, pr = eng / "00-triage/prior-audits", eng / "00-triage/potential-risks"
    marker = (eng / "00-triage/NO-PRIOR-ART.md").exists()
    if pa.is_dir() and not any(pa.iterdir()) and not marker:
        out.append((BAD, "prior-audits/ is EMPTY",
                    "[G1] blocks every TIER-1 promotion. Save the reports, or add "
                    "00-triage/NO-PRIOR-ART.md asserting there are none."))
    if pr.is_dir() and not any(pr.glob("*.txt")) and not marker:
        out.append((BAD, "potential-risks/ has no .txt",
                    "[G1] blocks every TIER-1 promotion. Run tooling/guards/extract_prior_art.py, "
                    "or write the extracts by hand."))

    # The alias that actually bit us. Deliberately NOT auto-fixed.
    alias = eng / "00-triage/prior-art"
    # new-engagement.sh makes prior-art a link to prior-audits; that is the fix, not the mistake.
    is_link_to_pa = alias.is_symlink() and pa.is_dir() and alias.resolve() == pa.resolve()
    if alias.is_dir() and not is_link_to_pa and (not pa.is_dir() or not any(pa.iterdir())):
        out.append((BAD, "corpus is in 00-triage/prior-art/, which no guard reads",
                    "[G1] the canonical name is prior-audits/. Move or symlink it -- not "
                    "auto-fixed, because which files are really prior art is your call."))

    # ledger/ and ledger/dedup/ are conveniences, not requirements: a flat <engagement>/ledger.md
    # is a layout two engagements already use and engagement_ledgers() reads it fine, and the dedup
    # directory is created by the first sidecar write. Reporting either as BLOCKING would make the
    # doctor cry wolf on engagements that work -- the same noisy-gate failure, in a report.
    if not (eng / "ledger" / "dedup").is_dir():
        out.append((WARN, "ledger/dedup/ not created yet",
                    "[G1] where DEDUP: sidecars go. Created by the first sidecar write; "
                    "--fix makes it now."))

    leds = engagement_ledgers(eng)
    if not leds:
        out.append((WARN, "no ledger file yet",
                    "expected once Phase 1 starts. Copy templates/ledger.template.md."))
    for lp in leds:
        rel = lp.relative_to(eng)
        content = lp.read_text(errors="ignore")
        rows, raw = parse_rows(content), parse_row_lines(content)
        if FORMAT_MARKER not in content:
            out.append((WARN, f"{rel}: no format declaration",
                        f"[G0c] add `{FORMAT_MARKER}` as line 1. Existing ledgers are "
                        f"grandfathered, so this is advisory."))
        if not rows:
            lvl = WARN if not raw else BAD
            out.append((lvl, f"{rel}: 0 readable rows ({len(raw)} id-keyed lines)",
                        "[G0b] a ledger the parser cannot read is exempt from EVERY guard. "
                        "Rows need an id in the FIRST cell and a status token."))
        else:
            out.append((OK, f"{rel}: {len(rows)} rows", ""))

    # Unconditional, unlike the checks below: a closed engagement is normally the LEAST
    # recently active one, and this must still fire on it in --all mode, which is the
    # whole point of the census (bench/improvement-backlog.md REF-22).
    out += check_untested_at_closeout(eng)

    if docs:
        out += check_protocol_docs(eng)
        out += check_ledger_is_cli_managed(eng)
        out += check_generators_unrun(eng)
        out += check_generated_rows_unimported(eng)
        out += check_poc_empty(eng)
        out += check_phases_recorded(eng)
        out += check_ledger_header(eng)
    return out


def status_line(results: list[tuple[str, str, str]]) -> str:
    """What the headline may claim. A GAP must never say a guard will block -- none will."""
    levels = {lvl for lvl, _, _ in results}
    if BAD in levels:
        return "would BLOCK a TIER-1 promotion"
    if GAP in levels:
        return "SETUP GAP — no guard refuses on this, so nothing else will tell you"
    return "advisory only" if WARN in levels else "ready"


# ---------------------------------------------------------------------------
# THE RUNTIME WORKTREE. Not an engagement check -- a machine-level one, which is
# why it runs once in main() rather than per engagement.
#
# Every guard and tool resolves the toolkit by ABSOLUTE PATH: SKILL.md's
# PreToolUse/Stop hooks run $HOME/audit-toolkit/tooling/guards/*.py and
# settings.json runs $HOME/audit-toolkit/tooling/engagement-doctor.py. So whatever
# branch that ONE directory has checked out is the code that runs for every
# engagement on the machine, whichever worktree the audit itself lives in.
#
# Measured 2026-09-14: the runtime sat on a feature branch predating a guard fix,
# so G1 misfired on an unrelated engagement three times in one session while the
# fix sat on main. The branch had since been merged and DELETED, so its absence
# read as the work being absent and the wrong diagnosis ("the fix never landed")
# was repeated for hours. Nothing errored. That is the definition of a silently
# violated, state-decidable rule, which CLAUDE.md says earns a check.
RUNTIME_ROOT = Path.home() / "audit-toolkit"


def check_runtime_branch(root: Path = RUNTIME_ROOT) -> list[str]:
    """Warn when the runtime worktree is not on main. Empty list means fine.

    Deliberately silent on every ambiguous case -- no git, not a repo, detached
    HEAD mid-rebase, directory absent. A setup check that guesses is worse than one
    that abstains (the same reason `burstiness` abstains under six sentences).
    """
    if not (root / ".git").exists():
        return []
    try:
        out = subprocess.run(["git", "-C", str(root), "branch", "--show-current"],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    if out.returncode != 0:
        return []
    branch = out.stdout.strip()
    if branch in ("", "main"):
        return []          # empty = detached HEAD; say nothing rather than guess
    return [
        f"audit-toolkit: THE RUNTIME IS ON {branch!r}, NOT main.",
        f"  {root} is what the hooks execute, by absolute path, for EVERY engagement",
        "  on this machine -- not just work done in that directory. Guards, the ledger CLI",
        "  and this script all run whatever is checked out there.",
        f"  Fix: commit or stash in {root}, then `git -C {root} checkout main`.",
        "  Feature work belongs in a worktree (see CLAUDE.md, Guardrails for changes).",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("engagement", nargs="?")
    ap.add_argument("--all", action="store_true", help=f"every engagement under {ENGAGEMENTS_ROOT}")
    ap.add_argument("--fix", action="store_true", help="create missing directories (never moves data)")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing when every engagement is clean (for a SessionStart hook)")
    a = ap.parse_args()

    # Machine-level, and printed FIRST: if the runtime is on the wrong branch then every
    # per-engagement result below was produced by the wrong code, so the reader needs to
    # know that before reading them.
    runtime = check_runtime_branch()
    if runtime:
        print("\n".join(runtime))

    if a.all:
        engs = [d for d in sorted(ENGAGEMENTS_ROOT.iterdir())
                if d.is_dir() and (d / "00-triage").is_dir()]
    elif a.engagement:
        engs = [Path(a.engagement).expanduser().resolve()]
    else:
        ap.error("give an engagement directory, or --all")

    worst = 0
    reports = []
    for eng in engs:
        if a.fix:
            for rel in [r for r, c, _, _ in REQUIRED_DIRS if c] + ["ledger/dedup", PROTOCOL_DOCS]:
                if not (eng / rel).is_dir():
                    (eng / rel).mkdir(parents=True, exist_ok=True)
                    print(f"  created {eng.name}/{rel}/")
        # In --all mode the REF-20 check is limited to engagements whose ledger moved recently.
        # A closed engagement cannot promote a row, and none of the back-catalogue has an extract,
        # so checking them all would add a permanent paragraph to every SessionStart.
        results = check(eng, docs=(not a.all) or recently_active(eng))
        fail = [r for r in results if r[0] in FAILING]
        warn = [r for r in results if r[0] == WARN]
        worst = max(worst, 2 if fail else (1 if warn else 0))
        if a.quiet and not fail:
            continue          # silence is the point: a hook that speaks every session gets muted
        lines = [f"\n{eng.name}  —  {status_line(results)}"]
        for lvl, headline, detail in results:
            if lvl == OK and (fail or warn):
                continue                      # keep the noise down when there is a problem
            if a.quiet and lvl not in FAILING:
                continue
            mark = {OK: "  ok  ", INFO: "  info", WARN: "  warn",
                    GAP: "  GAP ", BAD: "  BAD "}[lvl]
            lines.append(f"{mark} {headline}")
            if detail:
                lines.append(f"         {detail}")
        if not fail and not warn:
            lines.append("  ok   layout matches what every guard expects")
        reports.append("\n".join(lines))

    if reports:
        if a.quiet:
            print("audit-toolkit: engagement setup needs attention "
                  "(tooling/engagement-doctor.py <dir> --fix):")
        print("\n".join(reports))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
