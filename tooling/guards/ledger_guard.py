#!/usr/bin/env python3
"""Ledger guards G1-G3. Runs as a Claude Code PreToolUse hook on Write/Edit.

Contract: exit 0 = no opinion (SILENT). exit 2 = block, reason on stderr.
Silence on every path that does not apply is the design: a guard that fires often
gets disabled, and guards are cheap precisely because they say nothing by default.

Guards (criteria: docs/guard-register.md):
  G1  dedup vs full prior-art text before a row leaves UNTESTED
  G2  disposition cites evidence that exists (REFUTED) or a human (SCOPE-HELD)
  G3  a row may never go from UNTESTED to gone
  G14 a NO-MATCH dedup is cleared against finding BODIES, not section extracts alone
  G17 every function the row's entry names is a dedup term on its own (new promotions)
  G19 a MATCH sidecar, when written, quotes the entry for every caller and impact it claims
  G20 a SCOPE-HELD declared to rest on a scope exclusion quotes it (REF-32; cli.py only)

NEVER gates row creation. Phases 1-2 generate wide and suppress nothing; throttling
that would trade a rare priced failure for a constant invisible one.
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from table_cell import unescape_cell  # noqa: E402  REF-30: the read half of the escape.
from match_rule import ATTACK_CLAUSES, CLAUSES  # noqa: E402  REF-31: G16 reads the one match rule.
from source_paths import in_dependency_lib  # noqa: E402  one rule for every source walker

# A ledger row is a markdown table line whose FIRST cell is a hypothesis id.
#
# The hyphen used to be mandatory (`[A-Z][A-Z0-9]{0,9}-[0-9]{1,3}`), which silently
# excluded the id style this repo's own templates/ledger.template.md emits -- `H1`. A
# guard that parses zero rows enforces nothing and says nothing, so a fresh engagement
# started from the template was completely unguarded -- that is the whole point of the
# fix. Counting only rows that carry a status token (the rows a guard can act on):
# 70 before, 92 after. Of the 22 gained, 20 are the worked example worked example and 1 is
# engagement 6's `H-01b`; on LIVE engagement ledgers the recovery is one row. The decisive
# gain is the template, 0 -> 1.
#
# Anchored to the first cell: unanchored .search() matched ids buried mid-row (it found
# a spurious `H8-04` on engagement 8). Requiring >=1 digit is what keeps header cells
# (`id`, `ID`, `File`, `status`, `contract`, `subsystem`) from parsing as rows.
# One row id, unanchored, for readers that find ids inside prose (tooling/poc_mentions.py).
ROW_ID = r"[A-Z][A-Z0-9]{0,5}-?[0-9]{1,3}[a-z]?"
ROW_RE = re.compile(rf"^\s*\|\s*\*{{0,2}}({ROW_ID})\*{{0,2}}\s*\|")
# The toolkit repo itself is never an engagement: its docs/, templates/ and examples/
# hold ledger-shaped files that must not be gated. .parents[2] == audit-toolkit root.
TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
STATUSES = ["UNTESTED", "TIER-1", "CONFIRMED", "REFUTED", "SCOPE-HELD",
            "BELOW-BAR", "BLOCKED-OUT-OF-HARNESS", "BLOCKED"]
# TIER-1 = selected for PoC spend. It exists so the dedup obligation lands BEFORE the
# harness hours, not after: without it G1 fired on UNTESTED -> CONFIRMED, which in
# practice happens once the PoC already passes.
SPEND_STATUSES = ("CONFIRMED", "REFUTED")      # reaching these implies harness work
NO_SPEND_STATUSES = ("BLOCKED", "BLOCKED-OUT-OF-HARNESS", "SCOPE-HELD")
POC_SUFFIXES = (".t.sol", ".spec.ts", ".test.ts", "_test.go", ".rs", ".py", ".txt", ".log")
# REF-1: a Forge citation names the test FUNCTION as well -- `poc/test/H7.t.sol::test_H7`.
# REF-25 measured why: evidence names a file, one file holds many rows' tests, and a row can
# read as tested because a DIFFERENT row's test in that file ran the line.
EVIDENCE_FN_SEP = "::"
FORGE_SUFFIX = ".t.sol"
# An evidence token, with the `::function` suffix kept -- check_g2's own tokeniser drops it,
# because its character class has no colon.
EVIDENCE_TOKEN_RE = re.compile(r"[\w./\-]+(?:::[A-Za-z_]\w*)?")
# Identifiers as our ledger actually writes them: `backticked` or as a call foo(.
IDENT_CALL = re.compile(r"\b([a-z][A-Za-z0-9_]{5,})\s*\(")
IDENT_TICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{5,})`")
# A search term that is itself one function or variable name: lower case or underscore first, so
# a phrase, a contract name (`VaultRouter`) or an auditor (`ChainSecurity`) is not one.
# Those co-occur with everything in a report about that contract (measured on engagement 23).
IDENT_TERM = re.compile(r"[a-z_][A-Za-z0-9_.]{5,}")
# A real identifier is camelCase, snake_case or dotted. Plain English words in backticks
# (`control`, `policy`) are not identifiers and matching them points at the wrong report.
CODEY = re.compile(r"(?:[a-z][A-Za-z0-9]*[A-Z])|_|\.")
# Identifiers so central they appear in every report; matching them is noise, not signal.
IDENT_STOPWORDS = {"require", "function", "returns", "address", "msg.sender", "revert"}
MIN_COOCCURRING_IDENTS = 2
# The placeholder `tooling/ledger/sidecar.py` writes into an unfilled skeleton.
SKELETON_TODO = "<FILL IN>"
# --------------------------------------------------------------- G14 (REF-3) constants
# Finding-ID shapes, one per auditor house, as they appear in the extracted text on disk:
# Hacken `F-2026-1000`, Macro/CodeHawks `[H-01]`, WatchPug `[WP-M3]` (with a UNICODE
# hyphen -- pdftotext preserves it, and an ASCII-only pattern misses every WatchPug report),
# ChainSecurity `CS-ABC-001`, and the bare `M-3:` heading style.
#
# Measured on every 00-triage/ text file on disk before shipping: an earlier pattern for
# Zellic's `3.1`-numbered findings matched ChainSecurity's `8.2` sub-headings INSIDE a Notes
# extract and turned three section files into false bodies. It was dropped, not narrowed --
# see is_finding_body() for why that error direction is the costly one.
FINDING_ID_RES = [
    re.compile(r"\bF-(?:20\d\d-)?\d{3,6}\b"),
    re.compile(r"\[[A-Z]{0,4}[-\u2010\u2011\u2012\u2013]?[CHMLI][-\u2010\u2011\u2012\u2013]?\d{1,3}\]"),
    re.compile(r"\bCS-[A-Z0-9-]+-\d{3}\b"),
    re.compile(r"\b[CHMLI]-\d{1,3}\b:"),
]
# A file is a BODY if it spends prose on each finding it names. The discriminator is
# bytes-per-finding, and it is what separates the two artifacts REF-3 is about: engagement 14's
# INDEX.txt names 12 WatchPug issues in 1.8KB (152 B each -- a title list), while WP-M3.txt
# spends 13.5KB on one. Without this ratio the guard would have accepted the title index as
# the body and cleared exactly the dedup it exists to stop.
BYTES_PER_FINDING = 800
# A single-finding extract still has to be a body and not a stub.
MIN_BODY_BYTES = 1500
# Written by extract_prior_art.py and documented there as "full text, for dedup grep": by
# construction this directory holds the finding BODIES, so it needs no per-finding id.
BODY_TEXT_DIR = "prior-audits-text"
# Only the prior-art corpus is asked about. protocol-docs/ and the target's own text can
# mention a finding id in passing, and demanding they be searched for dedup is a category error.
CORPUS_DIRS = ("prior-audits", BODY_TEXT_DIR, "potential-risks")
# A prefix read, because two files in one engagement's corpus are 30MB each. Reading less can
# only under-detect, which is the safe direction.
BODY_SCAN_BYTES = 1_000_000
# A hypothesis id written OUTSIDE a table: a `### R-1 -` heading or a `- **L-C1 ...**` bullet.
# Both shapes are in real ledgers on disk and both are invisible to every guard.
# Looser than ROW_RE on purpose: off-table ids carry a hunter/section letter that the table
# grammar never has (`L-C1`, `L-D1`). Anchoring the END on a digit is what keeps ordinary
# bold prose bullets ("- **Hint variants degrade safely.**") from matching.
OFFTABLE_ID = re.compile(r"^(?:#{2,6}\s+|\s*[-*]\s+)\*{0,2}\[?([A-Z][A-Z0-9-]{0,7}[0-9][a-z]?)\b")
MIN_OFFTABLE_IDS = 2
# Declared on line 1 of every ledger. Required on CREATION only -- see check_new_ledger.
FORMAT_MARKER = "<!-- ledger-format: table-v1 -->"


def row_status(text: str) -> str | None:
    """The status comes from the STATUS CELL, never from anywhere else on the line.

    This used to scan the whole line. `UNTESTED` is first in STATUSES, so a row whose status
    cell read `REFUTED` but whose PROSE contained the words "is still UNTESTED" reported as
    UNTESTED. Two failures, and the second is the one that matters: `evaluate()` then computed
    old_st == new_st == UNTESTED, hit `continue`, and returned PASS on a real
    UNTESTED -> TIER-1 -> REFUTED promotion -- no G1, no G2. Found live on an engagement cut
    from this release, in an honest cross-reference to another row. `ledger_state_guard` imports this function, so
    the Stop hook mis-read it too: BOTH layers were blind to the same row.

    A lexical convention (all-caps, backticks) cannot fix this -- the prose that broke it was
    already all-caps and the tokens are legitimate English in a note. Cell POSITION is
    structural and prose cannot reach it.
    """
    cells = text.split("|")
    if len(cells) >= 3:
        # A status cell holds the token and NOTHING else -- real ledgers write `UNTESTED`,
        # sometimes bolded. Position is not reliable: the status is the last cell in some
        # layouts and second-to-last in others (an EVIDENCE/DEDUP column may follow it).
        # "Cell whose entire content is a status" is layout-independent and prose cannot
        # satisfy it, which is the whole point.
        for cell in reversed(cells):
            bare = cell.strip().strip("`*_ ").strip()
            if bare in STATUSES:
                return bare
        # No clean cell. Fall back to a right-to-left scan so a trailing status column still
        # wins over prose earlier in the row.
        for cell in reversed(cells):
            for s in STATUSES:
                if s in cell:
                    return s
        return None
    for s in STATUSES:            # longest-first ordering matters for BLOCKED*
        if s in text:
            return s
    return None


def status_token_outside_cell(text: str) -> str | None:
    """A status token in a row's prose that DISAGREES with its status cell.

    Returns the offending token, or None. Deliberately narrow: a row may legitimately repeat
    its OWN status in prose, and firing on that would make this noisy, which is the one failure
    the register is most explicit about. Only a token that would have changed the reading is
    reported.
    """
    cells = text.split("|")
    if len(cells) < 3:
        return None
    actual = row_status(text)
    if actual is None:
        return None
    for cell in cells:
        bare = cell.strip().strip("`*_ ").strip()
        if bare in STATUSES:
            continue                       # this IS a status cell, not prose
        for s in STATUSES:
            if s in cell and s != actual:
                return s
    return None


def parse_row_lines(content: str) -> dict[str, str]:
    """{id: line} for every table line whose first cell looks like an id -- status or not."""
    rows = {}
    for line in content.splitlines():
        m = ROW_RE.search(line)
        if m:
            rows.setdefault(m.group(1), line)
    return rows


def parse_rows(content: str) -> dict[str, str]:
    """{row_id: full line} for real LEDGER rows: an id in the first cell AND a status token.

    The status requirement is not pedantry. Ledgers contain other tables -- a hunter roster,
    a status summary, a dedup matrix -- whose first cell also looks like an id. Without it,
    engagement 8's roster (`| H1 | territory: rewards.rs | 9 |`) parsed as 8 ledger rows.

    That mattered more than a miscount: G0b only fires when a file parses ZERO rows, so an
    incidental side table gave engagement 8 (9) and engagement 5 (5) a healthy-looking row
    count and SUPPRESSED the wrong-format detector -- while the real hypotheses in both sat
    in `## C1` / `### R-6` headings that no guard could read. engagement 9 escaped the same fate
    only because its side table happened to be keyed on contract names rather than ids.
    """
    return {k: v for k, v in parse_row_lines(content).items() if row_status(v)}


def engagement_root(p: Path) -> Path | None:
    for parent in p.resolve().parents:
        if (parent / "00-triage").is_dir() or (parent / "ledger").is_dir():
            if (parent / "00-triage").is_dir():
                return parent
    return None


# Heavy build/vendor trees: never hold a ledger, expensive to walk on a real checkout.
SKIP_DIRS = {"node_modules", "lib", "out", "cache", "target", "artifacts", "broadcast",
             "repo", "coverage", "venv", "__pycache__"}


def engagement_ledgers(eng: Path) -> list[Path]:
    """Every ledger file in an engagement, whatever layout it uses.

    check_g1b used to glob `<eng>/ledger/*.md` only. Two engagements on disk keep the ledger
    flat at `<eng>/ledger.md` (engagement 6, engagement 8), so it found NO ledger there and
    concluded no row was ever at TIER-1 -- blocking every poc/ file, permanently. That is the
    noisy-gate failure the register warns about, and it disagreed with is_ledger(), which
    accepts both layouts. One discovery function now serves both.
    """
    found = []
    for root, dirs, files in os.walk(eng):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            fp = Path(root) / f
            if is_ledger(fp):
                found.append(fp)
    return sorted(found)


def is_ledger(p: Path) -> bool:
    # `ledger/dedup/<row-id>.md` holds a row's DEDUP evidence as YAML, not a ledger. Treating
    # one as a ledger deadlocked the system: G1 refuses a TIER-1 promotion until the sidecar
    # exists, and G0c refused to let the sidecar be written because it was a new .md under
    # ledger/ with no format marker. Found live on an engagement cut from this release, at the
    # first real promotion attempt. The test suite missed it because its fixtures write sidecars
    # directly to disk, which never fires a PreToolUse hook.
    if "dedup" in p.parts:
        return False
    # ledger/HEADER.md holds the human-owned header render_text() composes into the board
    # (REF-23). It is free prose, not a row table, and G0c blocked it the same way it once
    # deadlocked a dedup sidecar: a new .md under ledger/ with no format marker refused.
    if p.name == "HEADER.md":
        return False
    return p.suffix == ".md" and ("ledger" in p.parts or "ledger" in p.stem.lower())


# All guard fields live inline on one row, so a value ends at the NEXT key, not at "|".
# A greedy [^|]+ makes `searched:` swallow `terms:` and `result:` (caught by the tests).
# REASON was missing here until 2026-09-10 and it is the field BELOW-BAR requires, so any row
# carrying BOTH a DEDUP and a REASON had the rest of the cell swallowed into the sidecar path and
# G1 reported a real sidecar as absent. The backlog records the same class of bug on 2026-09-01
# (the DEDUP parse swallowing a cell); FIELD_KEYS was introduced to fix it, and BELOW-BAR shipped
# with --reason the following day without being added to the list.
FIELD_KEYS = ["searched", "terms", "result", "quote", "EVIDENCE", "HUMAN", "REASON",
              "DEDUP", "MERGED-INTO", "LEDGER-DELETE-APPROVED"]
# `cli.py render` joins inline fields with a middle dot ("EVIDENCE: x - DEDUP: y" using U+00B7),
# so a value's captured text can end with that separator. Strip it, and let the lookahead skip it,
# or every extracted path carries a trailing dot that no filesystem will resolve.
SEP_CHARS = " \t\u00b7"


def field(line: str, key: str) -> str | None:
    """The value of one inline field, as the person who wrote it wrote it.

    REF-30: the pattern ends a value at `|`, because that is a cell boundary. So a `|`
    INSIDE a value -- `|U| <= 1`, or a prose --reason with a pipe in it -- used to cut
    the value off mid-sentence. `cli.py render` now writes `&#124;` instead; this is the
    half that reads it back. This is the reader the Stop-hook state guard funnels every
    G1/G2/G12/G14 input through, so it is the one place the decode has to happen.

    unescape_cell touches nothing else, so a value that never went through the escape
    returns unchanged, and a row written before the escape reads exactly as it did.
    """
    others = "|".join(re.escape(k) for k in FIELD_KEYS if k.lower() != key.lower())
    m = re.search(rf"\b{re.escape(key)}\s*:\s*(.*?)(?=[\s\u00b7]*\b(?:{others})\s*:|\||$)",
                  line, re.IGNORECASE | re.DOTALL)
    return unescape_cell(m.group(1).strip(SEP_CHARS)) if m else None


def load_sidecar(rel: str, eng: Path) -> tuple[dict | None, str | None]:
    """Load a per-row evidence sidecar. Returns (data, error).

    Sidecars exist because ledger rows are already ~700 chars on average and one is
    2,638; appending the dedup evidence inline made the least readable artifact worse,
    and a one-line format cannot hold a multi-line verbatim quote.
    """
    cand = Path(rel) if Path(rel).is_absolute() else (eng / rel)
    if not cand.exists():
        return None, f"sidecar does not exist: {rel}"
    try:
        import yaml
    except ImportError:
        return None, "__NOYAML__"
    try:
        data = yaml.safe_load(cand.read_text(errors="ignore"))
    except Exception as e:
        return None, f"sidecar {rel} is not valid YAML: {str(e).splitlines()[0]}"
    if not isinstance(data, dict):
        return None, f"sidecar {rel} must be a YAML mapping"
    data["__path__"] = cand
    return data, None


def as_list(v) -> list[str]:
    """A sidecar field as a list of strings. Sidecars are hand-written YAML, so a value that should
    be a list may arrive as a string, a number or a mapping; none of those may raise here, because
    an exception in the PreToolUse hook would let the write through. A number or a mapping counts
    as ONE entry (its string form), not as its keys."""
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;\n]", v) if x.strip()]
    if not isinstance(v, (list, tuple)):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()]


def searched_path(sp: str, eng: Path) -> Path | None:
    """A `searched:` entry as a path under `eng` (or absolute), or None when the string cannot be a
    path on this system. An embedded NUL is rejected by name: `exists()` reports it as missing, but
    `resolve()` raises ValueError on it."""
    if "\x00" in sp:
        return None
    try:
        return Path(sp) if Path(sp).is_absolute() else (eng / sp)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- G3
def check_g3(old: dict[str, str], new: dict[str, str], content: str) -> list[str]:
    vanished = [r for r in old if r not in new]
    if not vanished:
        return []
    if "LEDGER-DELETE-APPROVED:" in content:
        return []
    surviving = []
    for r in vanished:
        m = re.search(rf"{re.escape(r)}\b.{{0,120}}?MERGED-INTO:\s*({ROW_ID})", content)
        if not (m and m.group(1) in new):
            surviving.append(r)
    if not surviving:
        return []
    return [f"G3 rows vanished from the ledger: {', '.join(sorted(surviving))}. "
            f"A row may never go from UNTESTED to gone -- use BLOCKED / "
            f"BLOCKED-OUT-OF-HARNESS, or add 'MERGED-INTO: <id>' or "
            f"'LEDGER-DELETE-APPROVED: <reason>'. (A row also 'vanishes' if its status "
            f"token is removed -- a line without one is not a tracked row.)"]


# ---------------------------------------------------------------- G1
def _holds(value, needle: str) -> bool:
    """Does a parsed YAML value (a string, or lists and dicts of them) contain `needle`?"""
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_holds(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(_holds(v, needle) for v in value)
    return False


def check_g1(row_id: str, dedup_rel: str | None, row_text: str, eng: Path,
             with_terms: bool = False) -> list[str]:
    """G1, decoupled from the markdown row.

    Takes the DEDUP pointer and the row's descriptive text as separate arguments rather
    than parsing them out of a table line, so the SAME predicate serves the PreToolUse
    hook (which has a line) and `tooling/ledger` (which has an event). One predicate,
    one place to change it -- the register/code drift that produced G4-G9 rows with no
    implementation is exactly what a forked copy would recreate.
    """
    errs = []
    pa = eng / "00-triage" / "prior-audits"
    pr = eng / "00-triage" / "potential-risks"
    txt = eng / "00-triage" / "prior-audits-text"
    marker = (eng / "00-triage" / "NO-PRIOR-ART.md").exists()

    if not marker:
        if not (pa.is_dir() and any(pa.iterdir())):
            errs.append(f"G1 [{row_id}] no prior-audit sources on disk ({pa}). Save the reports, "
                        f"or add 00-triage/NO-PRIOR-ART.md asserting none exist.")
        if not (pr.is_dir() and any(pr.glob("*.txt"))):
            errs.append(f"G1 [{row_id}] no verbatim extracts ({pr}). Run "
                        f"tooling/guards/extract_prior_art.py <engagement>.")
        if errs:
            return errs

    rel = dedup_rel
    if not rel:
        return errs + [
            f"G1 [{row_id}] no DEDUP: pointer. Add `DEDUP: ledger/dedup/{row_id}.md` to the row "
            f"and write that file with: searched (>=1 path under potential-risks/), terms (>=3), "
            f"result (MATCH|PARTIAL|NO-MATCH), quote (verbatim, >=40 chars, for MATCH and "
            f"PARTIAL), unmatched (what was searched for and NOT found, PARTIAL only)."]

    data, err = load_sidecar(rel, eng)
    if err == "__NOYAML__":
        # Fail CLOSED. A guard that silently no-ops is the exact failure mode this
        # whole mechanism exists to remove -- it would look installed and enforce nothing.
        return errs + [f"G1 [{row_id}] cannot run: pyyaml is not installed. "
                       f"`pip3 install pyyaml` (or run tooling/bootstrap.sh). "
                       f"Refusing to pass a promotion unchecked."]
    if err:
        return errs + [f"G1 [{row_id}] {err}"]
    # An unfinished `cli.py dedup-skeleton`: its placeholders are long enough to pass the length
    # checks below, so they are refused by name. Read from the PARSED values, never the raw text:
    # a comment holding the word must neither trigger this nor be what triggers it (review of the
    # skeleton: its own header comment once satisfied the check while every field was pre-filled).
    unfilled = sorted({k for k, v in data.items() if _holds(v, SKELETON_TODO)})
    if unfilled:
        return errs + [f"G1 [{row_id}] {rel} still holds {SKELETON_TODO} in {', '.join(unfilled)} "
                       f"(from `cli.py dedup-skeleton`). Fill every one before promoting."]

    searched, resolved = as_list(data.get("searched")), []
    for sp in searched:
        cand = searched_path(sp, eng)
        if cand is None or not cand.exists():
            errs.append(f"G1 [{row_id}] searched: names a file that does not exist: {sp!r}")
        else:
            resolved.append(cand)
    if not marker and not any("potential-risks" in str(c) for c in resolved):
        errs.append(f"G1 [{row_id}] searched: must include at least one file under "
                    f"potential-risks/ -- a digest alone never satisfies this.")

    terms = as_list(data.get("terms"))
    if len(terms) < 3:
        errs.append(f"G1 [{row_id}] terms: needs >=3 search terms (got {len(terms)}).")

    # PARTIAL exists because dedup has two kinds of MATCH and the ledger could express one.
    # It is defined NARROWLY and factually -- the ROOT CAUSE matched, the IMPACT or the CONSUMER
    # did not -- and never as a confidence grade. A confidence-graded third verdict would repeat
    # the tier-selection and Critical-only failures, both read off a feeling and both refuted.
    #
    # The two verdicts owe the human different reviews: a MATCH needs a spot-check that the
    # matcher worked; a PARTIAL needs a judgement about spending a submission on a GRADING
    # argument (the severity is understated, or the listed finding does not reproduce) rather
    # than a DISTINCTNESS one. Added after one engagement, cut from this release, where a single
    # blanket ruling was applied to dozens of matched rows and silently overrode the sidecars that
    # had themselves recorded "this is a Phase-4 call and it belongs to the human". Nothing errored.
    result = str(data.get("result", "")).strip().upper()
    if result not in ("MATCH", "PARTIAL", "NO-MATCH"):
        errs.append(f"G1 [{row_id}] result: must be MATCH, PARTIAL or NO-MATCH (got {result!r}).")

    if result == "PARTIAL":
        # `unmatched:` is what turns a hedge into a brief the human can actually rule on. Without
        # it, PARTIAL degrades into "probably a duplicate, not sure" -- which is the confidence
        # grade this verdict exists to not be.
        unmatched = " ".join(str(data.get("unmatched", "")).split())
        if len(unmatched) < 40:
            errs.append(
                f"G1 [{row_id}] result: PARTIAL requires unmatched: naming what was searched for "
                f"and NOT found (>=40 chars). PARTIAL means the ROOT CAUSE matched and the impact "
                f"or consumer did not -- say which, or use MATCH.")

    if result in ("MATCH", "PARTIAL"):
        quote = " ".join(str(data.get("quote", "")).split())
        if len(quote) < 40:
            errs.append(f"G1 [{row_id}] result: {result} requires quote: with >=40 chars of "
                        f"verbatim source text.")
        else:
            # Whitespace-normalised comparison: pdftotext wraps lines, so an honest
            # copy-paste of a real passage must not fail on line breaks alone.
            if not any(quote in " ".join(c.read_text(errors="ignore").split())
                       for c in resolved if c.is_file()):
                errs.append(f"G1 [{row_id}] quote: is not an EXACT substring of any searched file. "
                            f"Paraphrase and digest text cannot satisfy this -- paste the source.")

    # (4) identifier cross-check: content, not form. This is the engagement 3 catch.
    #
    # Requires >=2 DISTINCT identifiers co-occurring in the SAME risk section. A single
    # shared identifier is noise -- `checkController` appears in every report on that
    # codebase, and a guard firing on it would be disabled within a day.
    #
    # NO-MATCH only, deliberately. On a PARTIAL the identifiers co-occur BY DEFINITION -- the
    # root cause matched, that is what PARTIAL asserts -- so this check would fire on every one
    # and be disabled within a day, which is constraint 3 in CLAUDE.md.
    #
    # WITH TERMS, FOR NEW PROMOTIONS (`with_terms=True`, the ledger CLI only). On engagement 23 a
    # row named one identifier, so nothing could co-occur and its NO-MATCH passed, while a sibling
    # row naming three was caught against a prior-audit note describing the same overflow. The
    # sidecar's own `terms:` (at least 3, by rule) widen the set: each term that is itself a code
    # identifier joins the row's. The hooks keep the row-only set, so sidecars written before this
    # keep passing (it fired on about 1.4% of NO-MATCH sidecars on disk when measured).
    if result == "NO-MATCH":
        idents = {i for i in (IDENT_CALL.findall(row_text) + IDENT_TICK.findall(row_text))
                  if i.lower() not in IDENT_STOPWORDS and CODEY.search(i)}
        if with_terms:
            idents |= {t for t in as_list(data.get("terms"))
                       if IDENT_TERM.fullmatch(t) and t.lower() not in IDENT_STOPWORDS
                       and CODEY.search(t)}
        best, best_hits = None, []
        for section in sorted(pr.glob("*.txt")):
            hit = sorted(i for i in idents if i in section.read_text(errors="ignore"))
            if len(hit) > len(best_hits):
                best, best_hits = section, hit
        if len(best_hits) >= MIN_COOCCURRING_IDENTS:
            errs += check_cross_check_answered(row_id, best, best_hits, data, pr)
    return errs


def check_cross_check_answered(row_id: str, section: Path, hits: list[str],
                               data: dict, pr: Path) -> list[str]:
    """Let a sidecar record that the identifier cross-check has BEEN ANSWERED.

    The check itself is the engagement 3 catch and stays. What it lacked was any way to say
    "I read it." It re-derives identifiers from the ROW every time, so once it fires it fires
    forever, and the only way to silence it was to delete function names from the row -- i.e.
    to degrade the ledger to get a green light. On one engagement, cut from this release, that
    blocked FOUR fully-evidenced rows.

    Worse, it rewarded vagueness. Two of its rows were about the same two functions in the same
    corpus; the one that named them was blocked, the one that described them in prose passed. A guard
    satisfied by writing less points the wrong way.

    So the answer is a field that demands MORE, not less: name each flagged identifier and the
    file:line you actually read. You cannot satisfy it by shortening the row, because it asks
    what you READ rather than what you WROTE -- and the file has to exist.
    """
    # NOT as_list(): it stringifies dicts, and every entry here IS a dict.
    raw = data.get("cross_check_answered") or []
    if isinstance(raw, dict):
        raw = [raw]
    answered: dict[str, str] = {}
    for entry in (raw if isinstance(raw, list) else []):
        if isinstance(entry, dict):
            ident, sect = str(entry.get("identifier", "")).strip(), str(entry.get("section", "")).strip()
            if ident and sect:
                answered[ident] = sect
    missing = [h for h in hits if h not in answered]
    if missing:
        return [f"G1 [{row_id}] declared NO-MATCH, but {len(hits)} identifiers from this row "
                f"co-occur in {section.name}: {', '.join(hits[:5])}"
                f"{' ...' if len(hits) > 5 else ''}. Read that section verbatim and re-dedup. "
                f"If you HAVE read it and the verdict stands, record it in the sidecar as "
                f"`cross_check_answered:` -- a list of {{identifier, section}} where section is "
                f"`<file under potential-risks/>:<line>`. Still unanswered: {', '.join(missing)}."]
    # Every flagged identifier is claimed as read. Check the citations resolve: a section that
    # names no real file is the same hand-wave the DEDUP quote rule exists to stop.
    bad = []
    for ident in hits:
        fname = answered[ident].split(":")[0].strip()
        if not fname or not (pr / fname).exists():
            bad.append(f"{ident} -> {answered[ident]!r}")
    if bad:
        return [f"G1 [{row_id}] cross_check_answered: names a section that does not resolve to a "
                f"file under potential-risks/. Use `<filename>:<line>`. Offending: {'; '.join(bad)}."]
    return []


# ---------------------------------------------------------------- G19
CLAIM_KINDS = ("caller", "impact")
MIN_CLAIM_QUOTE_CHARS = 20
NOT_STATED = "not stated"


def check_g19(row_id: str, data: dict, eng: Path) -> list[str]:
    """G19 (Richard, 2026-10-26): a `result: MATCH` quotes the entry for every caller and every
    impact the row claims, or the row is PARTIAL.

    Pre: `data` is a parsed dedup sidecar. Post: [] unless `result:` is MATCH and the `claims:` list
    is absent, empty, or holds a claim that is not exactly one of `caller:` / `impact:` with a
    `quote:` of at least MIN_CLAIM_QUOTE_CHARS that is a whitespace-normalised exact substring of a
    file in `searched:` under 00-triage/. A quote of `not stated` is the matcher saying the entry does not state the
    claim, and that is what PARTIAL means (`tooling/match_rule.py`).

    Why in code: one arm of a pre-registered grader experiment (`bench/PREREG-full-text-grader.md`)
    gave a model the prose rule "a row claiming a caller or impact the entry does not state is
    partial"; it found the extra claim, quoted it, and still answered "same". A wrong KNOWN is a
    finding never tested (REF-2), so the decision is taken out of the model's hands.

    It cannot check that the list holds EVERY claim the row makes; the human sees each list at
    close-out (`cli.py known-review`).
    """
    if str(data.get("result", "")).strip().upper() != "MATCH":
        return []
    claims = data.get("claims")
    how = (f"      Write `claims:` with one item per caller and per impact the row claims:\n"
           f"        - caller: <what the row claims>     (or impact:)\n"
           f"          quote: <the entry's words that state it, copied exactly, >= "
           f"{MIN_CLAIM_QUOTE_CHARS} chars> | {NOT_STATED}\n"
           f"      A claim the entry does not state makes the row PARTIAL: write `result: PARTIAL` "
           f"with `unmatched:` naming it.\n"
           f"      Why: a wrong KNOWN is a real finding never tested (G19, Richard 2026-10-26).")
    if not isinstance(claims, list) or not claims:
        return [f"G19 [{row_id}] result: MATCH with no `claims:` list.\n{how}"]
    # Only entries copied verbatim count (G19_VERBATIM_SOURCE): a quote from our own ledger, triage
    # notes or agent-written keys would let the row's words stand in for the entry's (found in review).
    texts = []
    for sp in as_list(data.get("searched")):
        cand = searched_path(sp, eng)
        if cand is None:
            continue
        try:
            cand = cand.resolve()
        except (OSError, ValueError):
            continue
        try:
            rel = cand.relative_to(eng.resolve()).as_posix()
        except ValueError:
            continue
        if cand.is_file() and G19_VERBATIM_SOURCE.match(rel) and not G19_NOT_VERBATIM_NAME.search(cand.name):
            texts.append(" ".join(cand.read_text(errors="ignore").split()))
    problems = []
    for n, claim in enumerate(claims, 1):
        kinds = [k for k in CLAIM_KINDS if isinstance(claim, dict) and str(claim.get(k) or "").strip()]
        if len(kinds) != 1:
            problems.append(f"claim {n} must name exactly one of caller: or impact:")
            continue
        label = f"{kinds[0]} {' '.join(str(claim[kinds[0]]).split())!r}"
        quote = " ".join(str(claim.get("quote") or "").split())
        if quote.lower() == NOT_STATED:
            problems.append(f"{label} is not stated by the entry")
        elif len(quote) < MIN_CLAIM_QUOTE_CHARS:
            problems.append(f"{label} has a quote under {MIN_CLAIM_QUOTE_CHARS} characters")
        elif not any(quote in t for t in texts):
            problems.append(f"{label} has a quote that is not an exact substring of any file in "
                            f"searched: under 00-triage/")
    if not problems:
        return []
    return [f"G19 [{row_id}] result: MATCH, but the entry does not state every claim:\n"
            + "".join(f"        - {p}\n" for p in problems) + how]


# Where a KNOWN claim's quote may come from: text copied verbatim from the programme, prior audits
# or other researchers, never our own files. Measured 2026-10-26 over the 408 MATCH sidecars on disk:
# 403 quote one of these, 276 potential-risks/,
# 109 prior-audits-text/, 12 fellow-issues/, 6 known-issues-verbatim.md, and filed-issues.md is a
# synced snapshot of researchers' issues. Excluded: target-triage.md and other triage notes,
# prior-audit-keys/ (agent-written), scope-exclusions.md, README.md.
G19_VERBATIM_SOURCE = re.compile(
    r"00-triage/(?:(?:prior-audits-text|potential-risks|fellow-issues|protocol-docs|program"
    r"|[\w-]+-rules)/|(?:known-issues-verbatim|filed-issues|brief)\.md$)")
# Notes we write inside those folders, by file name (found in review: a README in potential-risks/,
# CORPUS.md and FETCH-* lists in prior-audits/, generated FINDINGS-INDEX files). prior-audits/ itself is
# not admitted: it holds the source documents and our fetch notes, and no MATCH quote on disk came from it.
G19_NOT_VERBATIM_NAME = re.compile(r"(?i)^(?:readme|corpus|fetch-|index|findings-index)|not-retained|superseded")

# A sidecar's raw text declaring MATCH, read where its YAML cannot be.
SAYS_MATCH = re.compile(r"(?m)^result:\s*['\"]?MATCH\b")


def is_dedup_sidecar(p: Path) -> bool:
    return p.suffix == ".md" and p.parent.name == "dedup" and p.parent.parent.name == "ledger"


def check_sidecar_write(path: Path, content: str) -> list[str]:
    """The hook's half of G19: judge a dedup sidecar as the Write or Edit would leave it.

    Only sidecars written or changed from now on meet this; an edit to an old MATCH sidecar is judged
    on the whole file it leaves, so it must gain `claims:`. Silent outside an engagement, and while
    `result:` still holds a `cli.py dedup-skeleton` placeholder, which the skeleton leaves there for
    KNOWN: writing MATCH is the last edit and is judged in full. A placeholder anywhere else, claims:
    included, silences nothing (found in review). YAML that does not parse is refused when the
    text says MATCH: a KNOWN row is normally never promoted, so no later check would read it.
    """
    eng = engagement_root(path)
    if eng is None or _in_toolkit(path):
        return []
    try:
        import yaml
    except ImportError:
        if SAYS_MATCH.search(content):
            return [f"G19 [{path.stem}] cannot run: pyyaml is not installed. `pip3 install pyyaml` "
                    f"(or run tooling/bootstrap.sh). Refusing a MATCH sidecar unchecked."]
        return []
    try:
        data = yaml.safe_load(content)
    except Exception as e:
        if SAYS_MATCH.search(content):
            return [f"G19 [{path.stem}] a MATCH sidecar that is not valid YAML: {str(e).splitlines()[0]}. "
                    f"Nothing later reads a KNOWN row's sidecar, so it must parse when written."]
        return []
    if not isinstance(data, dict) or _holds(data.get("result"), SKELETON_TODO):
        return []
    return check_g19(path.stem, data, eng)


# The human's answer on each KNOWN row, one `<id>: <answer>` line per row, the last line for an id
# winning. Written by `cli.py known-review --record`, read by `engagement-doctor.py` at close-out.
# Under 03-evidence/, not ledger/, so is_ledger() never takes it for a ledger.
KNOWN_REVIEW_FILE = "03-evidence/known-review.md"
_KNOWN_REVIEW_LINE_RE = re.compile(rf"(?m)^[ \t]*[-*]?[ \t]*`?({ROW_ID})`?[ \t]*:[ \t]*(\S.*?)[ \t]*$")


def known_rows(eng: Path) -> list[tuple[str, str, str, dict]]:
    """Every ledger row whose dedup sidecar says `result: MATCH`: (id, row line, sidecar, data).

    The sidecar is the row's DEDUP pointer, or `ledger/dedup/<id>.md` when the row has none: a row
    the matcher called KNOWN usually stays UNTESTED, and nothing records a pointer until a promotion.
    A row held in two ledger files with the same sidecar is listed once. A sidecar that cannot be
    loaded but whose text says MATCH is listed with `__unreadable__` set to why, never dropped:
    a load failure must not read as "not KNOWN".
    """
    out, seen = [], set()
    for led in engagement_ledgers(eng):
        for rid, line in parse_rows(led.read_text(errors="ignore")).items():
            rel = field(line, "DEDUP")
            if not rel and (eng / "ledger" / "dedup" / f"{rid}.md").is_file():
                rel = f"ledger/dedup/{rid}.md"
            if not rel or (rid, rel) in seen:
                continue
            data, err = load_sidecar(rel, eng)
            if err:
                cand = Path(rel) if Path(rel).is_absolute() else eng / rel
                raw = cand.read_text(errors="ignore") if cand.is_file() else ""
                if not SAYS_MATCH.search(raw):
                    continue
                why = "pyyaml is not installed" if err == "__NOYAML__" else err
                data = {"result": "MATCH", "__unreadable__": why}
            if not data or str(data.get("result", "")).strip().upper() != "MATCH":
                continue
            seen.add((rid, rel))
            out.append((rid, line, rel, data))
    return out


def known_reviews(eng: Path) -> dict[str, str]:
    """id -> the human's recorded answer, from KNOWN_REVIEW_FILE (empty when it does not exist)."""
    p = eng / KNOWN_REVIEW_FILE
    text = p.read_text(errors="ignore") if p.is_file() else ""
    return {m.group(1): m.group(2) for m in _KNOWN_REVIEW_LINE_RE.finditer(text)}


# ---------------------------------------------------------------- G14
def is_finding_body(path: Path, head: str) -> bool:
    """Does this corpus file carry finding BODIES, or only their titles?

    Tuned for PRECISION, not recall, and the asymmetry is deliberate: a file we fail to
    recognise makes G14 SILENT (the safe direction), while a title index misread as a body
    would clear the very dedup this guard exists to stop.
    """
    if not any(d in path.parts for d in CORPUS_DIRS):
        return False
    ids = sum(len(set(r.findall(head))) for r in FINDING_ID_RES)
    if ids and len(head) / ids < BYTES_PER_FINDING:
        return False                        # many ids, no prose: an index or a summary table
    if BODY_TEXT_DIR in path.parts:
        return True                         # our own full-text dump, whatever its id scheme
    return ids >= 1 and len(head) >= MIN_BODY_BYTES


# Keyed on (path, mtime, size), so an edited file is re-read and a stale verdict cannot
# survive. Measured before adding: the Stop guard calls check_g14 once per TIER-1-or-spent
# row, and each call re-read the whole corpus -- 3.27 s per Stop hook on one real engagement
# (50 rows x 65 ms, dominated by the 1MB prefix of two 29MB files). A guard that adds three
# seconds to every turn is the guard that gets disabled, which is constraint 3 in CLAUDE.md.
_BODY_CACHE: dict[tuple[str, int, int], bool] = {}


def finding_body_files(eng: Path) -> list[Path]:
    """Corpus text files under 00-triage/ that carry prior-audit finding BODIES.

    Recognises both shapes on disk without a naming convention we do not have: a whole
    report (`prior-audits-text/*.txt`, e.g. a 29.5MB CodeHawks findings export) and a
    per-finding extract (engagement 14's WatchPug `WP-M3.txt`).

    NOT engagement 1's `prior-findings.txt`, and that is the rule working rather than failing:
    it renders 31 findings as id/title/file/function/severity/status metadata in 14.2KB
    (458 B each), with no description of any mechanism. It is a title list in table form,
    which is the artifact G14 exists to refuse as a dedup target.
    """
    tri = eng / "00-triage"
    if not tri.is_dir():
        return []
    out = []
    for f in sorted(tri.rglob("*.txt")):
        try:
            st = f.stat()
            key = (str(f), st.st_mtime_ns, st.st_size)
        except OSError:
            continue
        verdict = _BODY_CACHE.get(key)
        if verdict is None:
            try:
                with f.open(encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(BODY_SCAN_BYTES)
            except OSError:
                continue
            verdict = _BODY_CACHE[key] = is_finding_body(f, head)
        if verdict:
            out.append(f)
    return out


def check_g14(row_id: str, dedup_rel: str | None, eng: Path, every: bool = False) -> list[str]:
    """REF-3. A NO-MATCH is cleared against finding BODIES, never against section extracts alone.

    WHY THIS EXISTS. G1 already refuses a digest -- `searched:` must name a file under
    `potential-risks/`, and a MATCH quote must be an exact substring of one. What it does
    not ask is whether the corpus that produced a NO-MATCH could have held the match at
    all. `potential-risks/` holds SECTION extracts (Potential Risks, Notes, Trust Model);
    extract_prior_art.py stops at the heading "Findings" by design, so on a report whose
    relevant prior art is a FINDING, every one of those files is structurally incapable of
    matching -- and the dedup comes back clean.

    That is the failure REF-3 names. A hunter's highest-confidence Critical was Hacken
    F-2026-1000, whose title says "Bridge Deposits" and whose body covers the mechanism; the
    digest carried the title. Same shape, measured on disk: engagement 16 rows H7, H8 and H15 all
    declare NO-MATCH on `executeBatch` territory having searched only the Notes and Trust
    Model extracts, while H6's own sidecar quotes ChainSecurity finding 7.1, "Reentrancy in
    Proposal Execution", from the full report text that sat unsearched in the same tree.

    NO-MATCH ONLY, for the identifier cross-check's reason: a MATCH or PARTIAL has already
    engaged with the prior art, and the risk being guarded is a FALSE CLEAR.

    SILENT when the engagement holds no body-bearing file: there is then nothing that was
    skipped, and firing would be a demand to produce a corpus rather than to read one.

    Fire rate measured across all 174 dedup sidecars on disk before building: 3 (1.7%), all
    three engagement 16, all three true positives on hand review. On all verdicts rather than
    NO-MATCH alone it would be 7 (4.0%); the extra four are PARTIALs whose `unmatched:` text
    proves the bodies were read and only the `searched:` list under-recorded it.
    EVERY BODY, FOR NEW PROMOTIONS (`every=True`, the ledger CLI; REF-31). On engagement 22 a PARTIAL
    against the known issues hid a full MATCH in a report nobody had searched: a partial match
    against one source is exactly when a fuller one in another changes the filing. So a new
    promotion with NO-MATCH or PARTIAL must list EVERY body file in `searched:`, not just one.
    Measured 2026-10-19 over every sidecar on disk: "every body"
    fires on 70 of 530 PARTIALs and 96 of 1,433 NO-MATCHes, against 3 for the old rule, so the
    Stop-hook backstop keeps the old any-body, NO-MATCH-only check, and old rows stay silent.
    """
    if not dedup_rel:
        return []                      # G1 owns the missing-sidecar case
    data, err = load_sidecar(dedup_rel, eng)
    if err or not data:
        return []                      # G1 owns sidecar resolution; do not double-report
    result = str(data.get("result", "")).strip().upper()
    if result != "NO-MATCH" and not (every and result == "PARTIAL"):
        return []
    bodies = finding_body_files(eng)
    if not bodies:
        return []
    resolved = set()
    for sp in as_list(data.get("searched")):
        cand = searched_path(sp, eng)
        if cand is None:
            continue
        try:
            resolved.add(cand.resolve())
        except (OSError, ValueError):
            continue
    if every:
        # A folder in `searched:` counts for every body file under it ("grepped the whole folder").
        unsearched = [str(b.relative_to(eng)) for b in bodies
                      if not ({b.resolve(), *b.resolve().parents} & resolved)]
        if not unsearched:
            return []
        return [
            f"G14 [{row_id}] declared {result} without searching every file that holds prior-audit "
            f"finding bodies.\n"
            f"      A partial or no match against one source is exactly when a fuller match in an "
            f"unsearched one\n"
            f"      changes the decision. Search these and add them to `searched:`: "
            f"{', '.join(unsearched)}\n"
            f"      Why: REF-31 -- a PARTIAL against the known issues hid a full MATCH "
            f"in an unread report."]
    if any(b.resolve() in resolved for b in bodies):
        return []
    names = [str(b.relative_to(eng)) for b in bodies]
    shown = ", ".join(names[:3]) + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")
    return [
        f"G14 [{row_id}] declared NO-MATCH without searching any file that holds prior-audit "
        f"FINDING bodies.\n"
        f"      Everything in `searched:` is a section extract. potential-risks/ holds sections "
        f"(Potential Risks,\n"
        f"      Notes, Trust Model) and extract_prior_art.py stops at \"Findings\" by design, so a "
        f"finding whose\n"
        f"      TITLE names another subsystem cannot match there however carefully you grep.\n"
        f"      Search the bodies and add the file to `searched:`: {shown}\n"
        f"      Why: REF-3. A hunter's top Critical was Hacken F-2026-1000 -- title \"Bridge Deposits\", "
        f"body ours."]


# ---------------------------------------------------------------- G17
# What the entry field names as a function, in the three shapes our ledgers write it:
# `backticked` (optionally `Contract.fn` or `fn(...)`), Contract.fn unbackticked, and fn( as a call.
ENTRY_TICK_RE = re.compile(r"`([^`]+)`")
ENTRY_TICK_IDENT_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(\([^)]*\))?\s*$")
# The qualifier must be capitalised (a contract or interface name), which is what keeps
# `msg.sender` and `foo.sol` out of the unbackticked shape.
ENTRY_QUALIFIED_RE = re.compile(r"\b[A-Z]\w*\.([a-z_]\w*)\b")
# No space before the paren, and not a plural marker: "anyone (via X)" and "function(s)" are prose.
ENTRY_CALL_RE = re.compile(r"\b([a-z_]\w*)\((?!e?s\))")
# A dotted token whose last part is one of these names a file or a global, never a function.
ENTRY_NOT_FUNCTION = {"sol", "t", "json", "md", "rs", "go", "ts", "js", "py", "txt", "vy", "yaml",
                      "sender", "value", "origin", "timestamp", "number"}
ENTRY_GLOBAL_QUALIFIERS = {"msg", "block", "tx", "abi", "type", "this", "super"}
# Solidity built-ins and casts, never a function of the target: an entry such as
# "amount = type(uint256).max" or "abi.encode(x) then keccak256(y)" names none (found in review).
SOLIDITY_BUILTINS = {"type", "keccak256", "sha256", "ripemd160", "ecrecover", "addmod", "mulmod",
                     "gasleft", "blockhash", "selfdestruct", "assert", "payable", "encode",
                     "encodePacked", "encodeWithSelector", "encodeWithSignature", "encodeCall",
                     "decode"}
SOLIDITY_CAST_RE = re.compile(r"(?:u?int|bytes)\d*")


def entry_identifiers(entry: str) -> list[str]:
    """The bare function names an entry field names, each once (backticked ones first).

    Conservative on purpose: a missed identifier only leaves the rule silent, while a word
    misread as an identifier refuses a promotion for nothing. So only code-shaped tokens
    count. A backticked token counts when it is qualified, a call, or camelCase/snake_case;
    a lone backticked lowercase word could be prose. Capitalised-only tokens (contract names
    such as `Registry`) and ALL-CAPS role words (GOVERNOR, KEEPER) are not functions.
    """
    found: list[str] = []

    def keep(qualified: str, is_call: bool) -> None:
        parts = qualified.split(".")
        bare = parts[-1]
        if len(parts) > 1 and (parts[0] in ENTRY_GLOBAL_QUALIFIERS or bare in ENTRY_NOT_FUNCTION):
            return
        if not re.match(r"[a-z_]", bare) or bare.lower() in IDENT_STOPWORDS:
            return                         # Contract names, role words, `require` and kin
        if bare in SOLIDITY_BUILTINS or SOLIDITY_CAST_RE.fullmatch(bare):
            return                         # `type(uint256)`, `abi.encode`, `keccak256`, casts
        if len(parts) == 1 and not is_call and not CODEY.search(bare):
            return                         # a lone lowercase word in backticks may be prose
        if bare not in found:
            found.append(bare)

    for tick in ENTRY_TICK_RE.findall(entry):
        m = ENTRY_TICK_IDENT_RE.match(tick)
        if m:
            keep(m.group(1), bool(m.group(2)))
    untick = ENTRY_TICK_RE.sub(" ", entry)
    for m in ENTRY_QUALIFIED_RE.finditer(untick):
        keep(m.group(0), True)
    for name in ENTRY_CALL_RE.findall(untick):
        keep(name, True)
    return found


# The documents G17 searches: the known and filed issues and the target's README, where the
# client describes its own design. Prior-audit report bodies are left to G1's cross-check and
# G14's every-body search; including them made G17 fire on about 83% of qualifying rows on disk
# against about 42% without (Richard's choice, 2026-10-20).
# Our own ledger and notes are never sources.
G17_SOURCE_GLOBS = ("00-triage/known-issues*", "00-triage/filed-issues*",
                    "target/README*", "repo/README*")
G17_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ""}
G17_LINES_SHOWN = 3


def g17_source_files(eng: Path) -> list[Path]:
    """The text files G17 searches, each once, in sorted order."""
    return sorted({f for g in G17_SOURCE_GLOBS for f in eng.glob(g)
                   if f.is_file() and f.suffix.lower() in G17_TEXT_SUFFIXES})


def g17_hits(name: str, files: list[Path], eng: Path) -> dict[str, list[tuple[int, str]]]:
    """Each file (relative to `eng`) whose text holds `name` as a whole identifier, with the
    line numbers and lines. Case-sensitive, like the identifier itself."""
    word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
    out: dict[str, list[tuple[int, str]]] = {}
    for f in files:
        try:
            lines = f.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        found = [(i, ln.strip()) for i, ln in enumerate(lines, 1) if word.search(ln)]
        if found:
            out[str(f.relative_to(eng))] = found
    return out


def g17_answered(data: dict) -> set[tuple[str, str]]:
    """(name, file) pairs the sidecar's `name_hits_read:` answers, each with a non-empty note."""
    pairs = set()
    raw = data.get("name_hits_read")
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name, file, note = (str(entry.get(k, "")).strip() for k in ("name", "file", "note"))
        if name and file and note:
            pairs.add((name, file))
    return pairs


def check_g17(row_id: str, dedup_rel: str | None, entry: str | None, eng: Path) -> list[str]:
    """Search each function the row's entry names, on its own, in the client's own documents (known
    and filed issues, the target README); refuse while a hit is unanswered.

    Pre: `entry` is the row's entry field as written (None or "" is fine). Post: one error naming
    every function with an unanswered hit and showing the lines, or [] -- silent when there is no
    sidecar to read (G1 owns that), when the result is MATCH, when the entry names no function,
    when the engagement has no source document, or when every hit is answered. A hit is answered
    by a `name_hits_read:` entry {name, file, note}, the note saying why that line is not this
    bug. The tool runs the search itself, so a term list cannot satisfy it on paper.

    NO-MATCH AND PARTIAL ONLY. Those are the verdicts where a document line the search missed
    can sink a filing (the row that motivated it was PARTIAL). A MATCH has already found its source.

    WHY THIS EXISTS. Engagement 22, 2026-10-20: a filed row's sidecar had searched the client README
    only with joined phrases, while the README described exactly that design in prose. Shown here
    with synthetic names: the entry is "`IPool.openPosition` by the pool owner, forwarded to
    `Registry.openPosition`"; the sidecar searched "openPosition lockPeriod" and "owner-chosen
    lock"; the README says "calls the pool's `openPosition` ... passes the initial lock period
    explicitly". No phrase matched, and `openPosition` alone would have hit.
    Richard chose this form 2026-10-20 over a term-list check, which an agent can satisfy by
    adding the word without searching.

    ROWS NOT YET HOLDING G1 ONLY, like G14's every-body rule: `cli.py promote` calls this; the
    Stop-hook backstop and the PreToolUse row driver do not, and State Locking means a row whose
    G1 is already discharged is not re-charged. It is not dated: an old UNTESTED row, or one that
    left by SCOPE-HELD, BELOW-BAR or BLOCKED without passing TIER-1, is charged when next promoted.
    It would refuse 14 of the 279 qualifying rows on disk when measured.
    """
    if not dedup_rel or not entry:
        return []
    needed = entry_identifiers(entry)
    if not needed:
        return []
    data, err = load_sidecar(dedup_rel, eng)
    if err or not data:
        return []                      # G1 owns sidecar resolution; do not double-report
    if str(data.get("result", "")).strip().upper() not in ("NO-MATCH", "PARTIAL"):
        return []
    files = g17_source_files(eng)
    if not files:
        return []
    answered = g17_answered(data)
    open_hits: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for name in needed:
        hits = {f: lines for f, lines in g17_hits(name, files, eng).items() if (name, f) not in answered}
        if hits:
            open_hits[name] = hits
    if not open_hits:
        return []
    shown = []
    for name, hits in open_hits.items():
        for f, lines in hits.items():
            for i, ln in lines[:G17_LINES_SHOWN]:
                shown.append(f"        {name} in {f}:{i}: {ln[:160]}")
            if len(lines) > G17_LINES_SHOWN:
                shown.append(f"        {name} in {f}: {len(lines) - G17_LINES_SHOWN} more line(s)")
    first_name, first_hits = next(iter(open_hits.items()))
    first_file = next(iter(first_hits))
    return [
        f"G17 [{row_id}] the entry names {', '.join(open_hits)}, and searched on "
        f"{'its' if len(open_hits) == 1 else 'their'} own "
        f"{'it appears' if len(open_hits) == 1 else 'they appear'} in documents this sidecar has "
        f"not answered:\n" + "\n".join(shown) + "\n"
        f"      Read each line. If one describes this row's mechanism, the verdict is not "
        f"{data.get('result')}. Otherwise answer each file in the sidecar:\n"
        f"        name_hits_read:\n"
        f"          - {{name: {first_name}, file: {first_file}, note: <why this line is not this bug>}}\n"
        f"      Why: a sidecar that searched only joined phrases missed the README line that "
        f"described the design in prose; the function's bare name alone would have hit it."]


# ---------------------------------------------------------------- G18
def _privileged_actors():
    """tooling/privileged_actors.py, imported on first use so a hook that never reaches G18 does
    not pay for it."""
    import privileged_actors
    return privileged_actors


G18_STATUSES = ("SCOPE-HELD", "BELOW-BAR")     # the two exits by which a row leaves the work on a ruling
G18_FILE_LINE = re.compile(r"([\w./-]+\.\w+):(\d+)")
G18_QUOTE = re.compile(r'"([^"]{20,})"')
G18_SKIP_DIRS = {"out", "cache", "node_modules", "broadcast", ".git", "artifacts"}
# Written or chosen by the auditor, or test code: not evidence about the audited code (review, 2026-10-21).
G18_NOT_SOURCE_DIRS = {"poc", "03-evidence", "test", "tests", "mock", "mocks", "ledger"}
# Auditor working folders at the engagement's top level (01-hunt, 02-static, ...). 00-triage is not one:
# it can hold the deployed source an engagement audits.
G18_WORK_DIR = re.compile(r"0[1-9]-")
# The programme's own text, copied verbatim into 00-triage/ (found in review): never the agent's
# triage notes, scope exclusions or the toolkit's README there.
G18_PROGRAMME_IN_TRIAGE = re.compile(r"00-triage/(?:brief\.md|(?:protocol-docs|potential-risks|prior-audits-text"
                                     r"|program|[\w-]+-rules)/)")
# Evidence must be in the audited source. A quote of the row itself, or a line of the engagement's own
# notes, proved nothing and turned the check into typing (review of G18, 2026-10-21).
G18_SOURCE_SUFFIXES = (".sol", ".vy", ".rs", ".go", ".move", ".cairo", ".fe", ".huff", ".yul")


def _g18_files(eng: Path):
    """Audited source files: no build or auditor folders, no test code, and no dependency `lib/`. A
    `lib` folder inside `src/` is first-party code (a project's own `src/**/lib/`) and is kept."""
    for p in eng.rglob("*"):
        if not p.is_file() or p.suffix not in G18_SOURCE_SUFFIXES or p.name.endswith(".t.sol"):
            continue
        parts = p.relative_to(eng).parts[:-1]
        if set(parts) & (G18_SKIP_DIRS | G18_NOT_SOURCE_DIRS) or (parts and G18_WORK_DIR.match(parts[0])):
            continue
        if in_dependency_lib(p, eng):     # the shared rule: a lib/ beside a foundry.toml
            continue
        yield p


def _g18_programme_docs(eng: Path, sources: list[Path]):
    """The programme's own documents, by provenance (found in review): the verbatim copies in
    `00-triage/` (`G18_PROGRAMME_IN_TRIAGE`), and the README and `docs/` of the target's own code, meaning
    a top-level folder that holds audited source. Where the trust model and an action's documented effect
    are written, which a FAIL on clause (c) rests on."""
    roots = {f.relative_to(eng).parts[0] for f in sources}
    for p in eng.rglob("*"):
        if not p.is_file() or p.suffix not in (".md", ".txt"):
            continue
        rel = p.relative_to(eng).as_posix()
        parts = p.relative_to(eng).parts
        if set(parts[:-1]) & (G18_SKIP_DIRS | G18_NOT_SOURCE_DIRS | {"lib"}):
            continue
        if G18_PROGRAMME_IN_TRIAGE.match(rel):
            yield p
        elif parts[0] in roots and parts[0] != "00-triage" and (
                p.name.lower().startswith("readme") or "docs" in parts[1:-1]):
            yield p


def _g18_cites(value: str, files, eng: Path) -> bool:
    """A `file:line` naming one of `files` with that many lines, or a 20+ character quote found in one."""
    norm = lambda t: " ".join(t.split())  # noqa: E731
    cites = G18_FILE_LINE.findall(value)
    quotes = [norm(q) for q in G18_QUOTE.findall(value)]
    if not cites and not quotes:
        return False
    for f in files:
        rel = f.relative_to(eng).as_posix()
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for path, line in cites:
            if (rel == path or rel.endswith("/" + path)) and 1 <= int(line) <= len(text.splitlines()):
                return True
        if quotes and any(_g18_quote_in_row(q, text) for q in quotes):   # same tolerance as NO-ACTION
            return True
    return False


# A NO-ACTION quote is the matched words, so it may be short ("any borrower").
G18_ROW_QUOTE = re.compile(r'"([^"]+)"')


def _g18_quote_in_row(quote: str, row_text: str) -> bool:
    """`quote` appears in the row as screeners write quotes: any case, backticks dropped, whitespace collapsed,
    and "..." or "…" standing for skipped words, with the pieces in order (engagement 21 replay)."""
    plain = lambda t: " ".join(t.replace("`", "").split()).lower()  # noqa: E731  roles match in any case
    text, at = plain(row_text), 0
    pieces = [plain(p) for p in re.split(r"\.\.\.|…", quote) if plain(p)]
    for piece in pieces:
        at = text.find(piece, at)
        if at < 0:
            return False
        at += len(piece)
    return bool(pieces)


def _g18_evidence_ok(verdict: str, value: str, row_text: str, eng: Path) -> bool:
    """Evidence per verdict (Richard, 2026-10-21). FAIL and NO-ACTION follow Phase 4's own definitions;
    the other verdicts set nothing aside on admin grounds, so G18 records them without a check (Richard's
    choice: Phase 4 also asks BOUND-CITED to cite its bound, which the screen, not this guard, holds).
    - FAIL lets an admin row out of the work, so it cites what proves the clause fails: a line or quote in
      the audited source (`_g18_files`) or in the programme's own documents (`_g18_programme_docs`).
      Never the row, the auditor's notes, PoCs or test code.
    - NO-ACTION is a claim about the row's wording, so it quotes words from the row.
    - PASS, UNCLEAR, BOUND-CITED and SEMI-TRUSTED set nothing aside on admin grounds: recorded, no check."""
    if verdict == "FAIL":
        sources = list(_g18_files(eng))
        return _g18_cites(value, sources + list(_g18_programme_docs(eng, sources)), eng)
    if verdict == "NO-ACTION":
        # Not required to contain the matched word: real screeners quote the words that show no role acts
        # ("any lender"), and that rule failed 55 of engagement 21's 125 NO-ACTION cells (2026-10-21).
        return any(_g18_quote_in_row(q, row_text) for q in G18_ROW_QUOTE.findall(value) if len(q.strip()) >= 3)
    return True


def check_g18(row_id: str, row_text: str, privileged_test: str | None, eng: Path) -> list[str]:
    """A row that names a privileged action does not leave the work on a ruling (SCOPE-HELD or
    BELOW-BAR) without the privileged-action test.

    Engagement 23 (REF-33): about a third of its untested rows involved an admin step and were
    ranked weak largely for that, while a prior audit's accepted Medium needed only an honest admin
    pause. The privileged-action test judges such rows by clause (`tooling/privileged_actors.py`);
    this makes its verdict a precondition of the two exits. It records that the test ran and what it found;
    it does not enforce the outcome (a PASS can stand beside a ruling that the row is a duplicate).

    Pre: `row_text` is the row's hypothesis, entry and invariant. Post: [] wherever no filled
    `01-scope/privileged-actors.md` exists (engagements before the file, and any engagement before
    Phase 0 writes it), when the row names no privileged
    role, function or verb, or when `privileged_test` STARTS with exactly one of the screen's verdicts
    with the evidence that verdict needs (`_g18_evidence_ok`): FAIL cites a line or quote in the audited
    source or the programme's own documents; NO-ACTION quotes the matched words from the row; the other
    verdicts need none. Otherwise one error. CLI only: the hooks never call it.
    """
    roles = eng / "01-scope" / "privileged-actors.md"
    if not roles.is_file():
        return []
    ps = _privileged_actors()
    try:
        actors = ps.parse_privileged_actors(roles)
    except ps.RolesFileError:
        return []                      # an unfilled template: the screen itself refuses to run
    terms = ps.privileged_terms(row_text, actors)
    if not terms:
        return []
    value = (privileged_test or "").strip()
    alternation = "|".join(re.escape(v) for v in ps.VERDICTS)
    lead = re.match(rf"({alternation})(?![\w-])", value)
    others = [v for v in ps.VERDICTS if re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", value[lead.end():] if lead else value)]
    if lead and not others and _g18_evidence_ok(lead.group(1), value, row_text, eng):
        return []
    return [f"G18 [{row_id}] the row names a privileged action ({', '.join(terms[:4])}), so it does not leave "
            f"the work before the privileged-action test. Run it (`tooling/privileged_actors.py` lists the verdicts) and pass "
            f"--privileged-test starting with ONE verdict ({' | '.join(ps.VERDICTS)}) and citing evidence that "
            f"its verdict needs: FAIL cites a real file:line or quote in the audited source or the programme's "
            f"documents (00-triage/, README, docs/); NO-ACTION quotes the matched words from the row, e.g. "
            f"--privileged-test \"FAIL (c): the harm is the documented effect, src/Vault.sol:212\".\n"
            f"      Why: an honest admin pause was the setup step of a prior audit's Medium, "
            f"while admin-dependent rows had been set aside wholesale."]


# ---------------------------------------------------------------- G2
def _in_toolkit(path: Path) -> bool:
    """The toolkit repo is never an engagement: docs/, templates/ and examples/ hold
    ledger-shaped documentation that must not be gated."""
    try:
        return path.resolve().is_relative_to(TOOLKIT_ROOT)
    except (OSError, ValueError):
        return False


def check_new_ledger(path: Path, content: str) -> list[str]:
    """The format contract, enforced where it is cheapest: at ledger CREATION.

    G0b is a DETECTOR -- it notices a wrong format only when the ids are shaped like
    something it recognises. A ledger written in a shape nobody anticipated still parses
    as zero rows and is still silently exempt. Detection can always be out-run by a format
    we have not seen; a declaration cannot.

    So a NEW ledger must declare the format it is written in. Existing ledgers are
    grandfathered -- requiring the marker everywhere would block five engagements on disk
    for no gain, and a gate that fires on everything gets disabled.

    This gates FILE creation, never ROW creation: the cost is one line, it demands no
    justification for any hypothesis, and it cannot throttle the Phase-1 sweep.
    """
    if path.exists() or FORMAT_MARKER in content:
        return []
    return [f"G0c [{path.name}] is a new ledger with no format declaration. Add "
            f"`{FORMAT_MARKER}` as the first line, and write hypotheses as markdown table "
            f"rows (id in the FIRST cell, status token and EVIDENCE:/HUMAN:/DEDUP: keys "
            f"inline on the row). Easiest: copy templates/ledger.template.md, or run "
            f"tooling/new-engagement.sh <name>. A ledger the parser cannot read is exempt "
            f"from every guard, silently -- see docs/hypothesis-ledger.md."]


def check_format(path: Path, content: str) -> list[str]:
    """G0b -- a ledger whose hypotheses are not table rows is invisible to every guard.

    Measured 2026-08-20: three ledger formats were in use across 7 engagements. Only the
    table is machine-readable. `engagement 9` writes hypotheses as `### R-1` section headings
    and `engagement 7` as `- **L-C1 ...**` bullets, so BOTH parsed zero rows
    and were silently exempt from every rule. engagement 9's R-6 closes a 403-line custom
    library with "Refuted on every arm read" and no evidence path -- the exact argument-kill
    G2 blocks, never seen because the row was a heading.

    Teaching the parser all three formats is the wrong fix: evidence keys live inline on a
    row and have no agreed place in a heading or a bullet, so G1/G2 would still have nothing
    to read. One format, stated in docs/hypothesis-ledger.md, with deviation made loud.

    Requires >=2 off-table ids, so a freshly-created ledger that has a header block and no
    hypotheses yet stays silent -- row creation is never gated.
    """
    rows = parse_rows(content)
    ids = {m.group(1) for line in content.splitlines()
           if (m := OFFTABLE_ID.match(line))}

    # Trigger 1: the hypotheses live OUTSIDE the table. Comparing against the row count
    # rather than requiring zero rows is what makes this robust: a ledger can carry a
    # roster or a summary table (or one stray real row) and still keep its hypotheses in
    # `## C1` headings. engagement 8 is exactly that -- 1 table row, 14 heading ids --
    # and an is-it-zero test lets it through.
    if len(ids) >= MIN_OFFTABLE_IDS and len(ids) > len(rows):
        return [f"G0b [{path.name}] has {len(ids)} hypotheses written as headings or bullets "
                f"({', '.join(sorted(ids)[:4])}...) but only {len(rows)} readable table row(s). "
                f"Every guard reads table rows, so those hypotheses are exempt from all of them "
                f"-- silently. Convert to one markdown table row per hypothesis, id in the FIRST "
                f"cell, status token and EVIDENCE:/HUMAN:/DEDUP: keys inline on the row. See "
                f"docs/hypothesis-ledger.md 'The row format is a CONTRACT'."]

    # Trigger 2: it IS a table of id-keyed rows, but not one carries a status token, so every
    # transition check skips every row.
    if not rows:
        untyped = parse_row_lines(content)
        if len(untyped) >= MIN_OFFTABLE_IDS:
            return [f"G0b [{path.name}] has {len(untyped)} id-keyed table rows and NONE carries "
                    f"a status token ({', '.join(sorted(untyped)[:4])}...). Every guard keys off "
                    f"the status, so all of them skip every row -- silently. Add a status to each "
                    f"hypothesis row, or, if this table is a roster/summary rather than the "
                    f"ledger, move the hypotheses into a table that has one."]
    return []


def split_evidence(token: str) -> tuple[str, str | None]:
    """`path::function` -> (path, function); a bare path -> (path, None).

    REF-1. Every reader of an evidence value goes through here, so the path part resolves
    whichever form the citation takes and a correct citation is never refused for its form.
    """
    path, sep, fn = token.partition(EVIDENCE_FN_SEP)
    return path, (fn.strip() or None) if sep else None


def resolve_artifact(token: str, eng: Path) -> Path | None:
    """Resolve a cited evidence path: literal first, then by basename inside the engagement.

    Real ledgers cite bare basenames. Measured 2026-08-20 across every row at CONFIRMED or
    REFUTED on disk: only 1 of 16 resolved under a literal-path-only rule, and 4 resolve by
    basename. Three of engagement 6's five CONFIRMED rows name `PoC_H01_FeeBypass.t.sol` and
    friends with no path at all, while the files live in `test/` -- a literal-only resolver
    blocks all three, which is exactly the noisy-gate failure this register keeps warning about.

    Known limit, inherited: this proves an artifact with that name EXISTS, not that it tests the
    right property, and a bare basename could match the target's own test rather than ours.
    Citing a repo-relative path avoids the ambiguity and is what the template asks for.
    """
    p = Path(split_evidence(token)[0])
    cand = p if p.is_absolute() else (eng / p)
    if cand.is_file():
        return cand
    name = p.name
    for root, dirs, files in os.walk(eng):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if name in files:
            return Path(root) / name
    return None


def check_g0(path: Path, content: str) -> list[str]:
    """A ledger whose engagement root cannot be found gets NO guard. Say so; never pass.

    engagement_root() anchors on a 00-triage/ directory. When it returns None, evaluate()
    used to return no errors -- indistinguishable, from the outside, from "checked and
    fine". That is the same failure the frontmatter path bug taught us: an absent guard
    that reads exactly like a satisfied one. Measured live (hooktest case 17): the very
    promotion blocked in case 01 went through untouched purely because the directory had
    no 00-triage/.

    Deliberately narrow, so it cannot become the gate everyone disables:
      - files inside the toolkit repo are exempt -- docs/hypothesis-ledger.md,
        templates/ and examples/ are documentation, not engagements;
      - a file with no parsed rows is exempt -- there is nothing ledger-shaped to protect,
        and firing on any .md with "ledger" in its name would be pure noise.
    """
    if not parse_rows(content):
        return []
    # The engagement dir is the ledger's parent, or its grandparent under the usual
    # <engagement>/ledger/ledger.md layout. Naming a real path beats printing "..".
    eng = path.parent.parent if path.parent.name == "ledger" else path.parent
    return [f"G0 [{path.name}] has ledger rows but no engagement root: no 00-triage/ "
            f"directory in any parent of {path.parent}. Every guard keys off that root, so "
            f"none of them can run here. Refusing rather than passing unchecked -- run "
            f"`mkdir -p {eng}/00-triage` to bring this ledger under guard."]


FILED_RE = re.compile(r"\bFILED:\s*(\S+)", re.I)
DRAFTED_RE = re.compile(r"\bDRAFTED:\s*(\S+)", re.I)
# A filing is proved by a platform URL. Anything else is a claim about our own past.
FILED_URL_RE = re.compile(r"https?://\S+")


def check_g13(row_id: str, row_text: str) -> list[str]:
    """G13 -- a FILED row cites the platform issue; `SUBMITTED` is not a status.

    WHY THIS EXISTS. `LEDGER.md` used the status `SUBMITTED` to mean *a draft was written*.
    Nothing distinguished drafted from filed-on-the-platform, and on 2026-09-08 that cost us a
    real misreading: `bench/engagements.md` recorded engagement 2 as "4 SUBMITTED ... plus 5 written
    reports" and the platform's own account page showed **1 Submitted, 0 Valid**. Two filed, one
    withdrawn, one judged. **Both documents overstated our filing history four-fold.**

    That is not cosmetic. On Sherlock the Issues Ratio gates all USDC; on any reputation-gated
    bounty an invalid filing is a permanent cost. A word that cannot tell a draft from a filing
    cannot answer the question that decides whether we get paid.

    FILING IS AN ATTRIBUTE, NOT A STATUS -- and the reason is the defect itself. The taxonomy is
    EPISTEMIC: it says whether we believe the hypothesis (`UNTESTED`, `CONFIRMED`, `REFUTED`,
    `SCOPE-HELD`, `BELOW-BAR`). Filing is an ACTION taken on a row we already believe. Putting it
    in the status cell is what made `SUBMITTED` ambiguous in the first place -- one field carrying
    two axes -- so promoting `FILED` to a status would repeat the mistake with a better word. A
    row is `CONFIRMED` **and** carries `FILED: <url>`; those are independent facts.

    `SUBMITTED` is also not in STATUSES, so such a row parses as statusless and is invisible to
    EVERY guard (see the doctor's `check_statusless_rows`). The register already logged this
    taxonomy gap and called the resolution "a human call, not a parser change". This is that call.
    """
    out = []
    # Read the CELL, never the line (G0d's rule): a row may legitimately say "submitted to the
    # sponsor" in prose. Only a cell whose entire content is a SUBMITTED-shaped word counts.
    # ALL-CAPS `SUBMITTED` anywhere in the row, not just in the status cell. Measured against
    # the ledger that motivated this: engagement 2 never put it in a status cell -- H2 carried
    # `**[SUBMITTED - issue #1, High label, 2026-07-09]**` inside the HYPOTHESIS cell, and the
    # bullets below the table said "H2 - SUBMITTED (issue #1)". A cell-only check fires on none
    # of that, so it would not have caught the error it exists for.
    # Case is the discriminator, and it is a real one: a status is written in caps, ordinary
    # prose says "submitted a courtesy note" in lower case. Measured false-positive rate across
    # every ledger on disk is recorded in the commit message.
    cells = [c.strip().strip("`*_ ").strip() for c in row_text.split("|")]
    if any(re.fullmatch(r"SUBMITTED(-\w+)?", c) for c in cells) or \
       re.search(r"\bSUBMITTED\b", row_text):
        out.append(f"G13 [{row_id}] `SUBMITTED` is not a status -- it means 'a draft exists' to "
                   f"some readers and 'we filed it' to others, and that ambiguity overstated our "
                   f"own filing history four-fold. It is also outside STATUSES, so this row is "
                   f"invisible to every other guard. Keep the EPISTEMIC status (CONFIRMED / "
                   f"SCOPE-HELD / ...) and record the action separately: `FILED: <platform url>` "
                   f"if it was filed, `DRAFTED: <path>` if only written.")
    m = FILED_RE.search(row_text)
    if m and not FILED_URL_RE.search(row_text):
        out.append(f"G13 [{row_id}] FILED: with no platform URL. A filing is proved by the issue "
                   f"it created; without the link this is a claim about our own past, which is "
                   f"exactly what went wrong on engagement 2. Write `FILED: <https://...>`, or "
                   f"`DRAFTED: <path>` if it was written but never filed.")
    return out


def check_g2(row_id: str, dedup_rel: str | None, evidence: str | None, human: str | None,
             row_text: str, status: str, eng: Path) -> list[str]:
    """G2/G10, decoupled from the markdown row -- same reasoning as check_g1.

    `evidence` and `human` are the explicit keys when a caller has them; `row_text` is the
    fallback scanned for artifact paths, because three of engagement 6's five CONFIRMED
    rows carry the artifact in a plain column with no key and are properly evidenced.
    """
    side = {}
    rel = dedup_rel
    if rel:
        d, e = load_sidecar(rel, eng)
        if d and not e:
            side = d

    # G2 protects KILLS; G10 protects CLAIMS. Same predicate, opposite failure: a REFUTED row
    # with no evidence is an argument-kill, a CONFIRMED row with no evidence is an unbacked
    # finding. Nothing was required of CONFIRMED until 2026-08-20, so a row could claim a bug
    # with no PoC at all -- and on an invite-only review platform, where the submission form
    # marks Proof of Concept "(optional)", nothing outside the model would have caught it either.
    if status in ("REFUTED", "CONFIRMED"):
        gid = "G2" if status == "REFUTED" else "G10"
        why = ("A hypothesis is killed by a failed PoC, never by prose."
               if status == "REFUTED" else
               "A finding is claimed with a PoC, never with prose. No PoC means no submission -- "
               "and on a platform where the PoC field is optional, this guard is the only thing "
               "enforcing that.")
        # The EVIDENCE: key is the documented form, but judge on CONTENT, not form: three of
        # engagement 6's five CONFIRMED rows carry the artifact in a plain evidence COLUMN with
        # no key, and they are properly evidenced rows. Falling back to a scan of the whole line
        # is the same "content, not form" principle the G1 identifier cross-check is built on.
        ev = evidence or side.get("evidence") or row_text
        if not any(resolve_artifact(tok, eng)
                   for tok in re.findall(r"[\w./\-]+", ev) if tok.endswith(POC_SUFFIXES)):
            named = [tok for tok in re.findall(r"[\w./\-]+", row_text) if tok.endswith(POC_SUFFIXES)]
            if not named:
                return [f"{gid} [{row_id}] {status} with no PoC artifact named anywhere on the row. "
                        f"{why} Write `EVIDENCE: <path>` on the row."]
            return [f"{gid} [{row_id}] names {named[0]!r} but it does not resolve to a file under "
                    f"{eng}. A back-reference like \"same file\" is not a citation -- name the path."]

    if status == "SCOPE-HELD" and not (human or side.get("human")):
        return [f"G2 [{row_id}] SCOPE-HELD with no HUMAN: record. Scope is the human's call; "
                f"a model recording its own reasoning here IS the failure mode."]
    return []


# ---------------------------------------------------------------- driver
def check_g1b(path: Path, eng: Path) -> list[str]:
    """Harness work under poc/ requires at least one row already promoted to TIER-1.

    Deliberately coarse: it does not map a PoC file to a specific row (that would need a
    naming convention we do not have). It catches the case that actually cost us -- building
    a harness with ZERO dedup done anywhere -- and stops firing as soon as one row is
    promoted, so it stays quiet for the rest of the engagement.
    """
    for lp in engagement_ledgers(eng):
        for line in lp.read_text(errors="ignore").splitlines():
            if ROW_RE.search(line) and row_status(line) in ("TIER-1",) + SPEND_STATUSES:
                return []
    return [f"G1b no row is at TIER-1 yet, so no candidate has been deduped against prior art. "
            f"Building a harness at {path.name} spends the hours this guard exists to protect. "
            f"Promote the row you are about to test to TIER-1 with a DEDUP: sidecar first."]


def check_g12(row_id: str, dedup_rel: str | None, eng: Path) -> list[str]:
    """REF-2. A row retired against a published Known Issue must record what the listed
    issue does NOT cover.

    The Guidelines' duplicate test is a three-way AND -- same root cause, AND affects
    in-scope code, AND describes the same underlying vulnerability. Sharing a root cause
    is necessary, not sufficient. On one engagement, cut from this release, we treated it as
    sufficient: most of the ledger was retired as SCOPE-HELD, every sidecar recorded
    `result: MATCH` on the root cause alone, and every finding the contest paid for was living
    in the residue -- a milder listed impact, a different clause of a compound statement, or a
    different cause entirely.

    A row asserts a GRID of claims; a Known Issue is a finding and occupies exactly one
    cell (cause x clause x consequence). A match retires that cell, not the grid.

    WHAT THIS DOES NOT DO. It never judges whether a residue is real -- that needs
    judgement, is not state-decidable, and belongs to the human or a prompt hook. It
    checks only that the three questions were ANSWERED, which is the thing that silently
    did not happen on dozens of rows in a row. `unmatched: none` is a legal answer.

    SCOPE. Fires only when a dedup sidecar exists AND says MATCH. A SCOPE-HELD row with
    no sidecar is a different animal -- a scope judgement (admin-gated, out-of-scope
    contract, front-running exclusion), where dedup was never the reason. Demanding a
    sidecar there would be a false positive on every one of them, and a gate that fires
    wrongly gets disabled.

    THE COUNT, CORRECTED. This docstring read "22 such rows across 6 engagements" from the
    day it shipped (2026-09-01 14:39). The dry run was re-run and corrected the same day at
    16:23 -- `field()` returned the whole rest of the cell where DEDUP: was the last key, so
    real sidecars scored as absent -- and the corrected table
    (`docs/guard-register.md`, "Dry run over every ledger on disk") gives **19** over the
    same six engagements. That commit never touched this file, so 22 sat here superseded.
    Re-measured 2026-09-29 (`bench/ti9-scope-held-measurement-2026-09.md`,
    `bench/ti9_scope_held_count.py`): **62** across 8 engagements (63 before excluding one
    prose line that parses as a row -- see that file's amendment), of which the five the
    register grouped still contribute exactly the 17 it recorded. The rest are engagements
    that did not exist on 2026-09-01. 22 is reproducible from no document and from no disk
    state; do not propagate it.
    """
    if not dedup_rel:
        return []
    data, err = load_sidecar(dedup_rel, eng)
    if err or not data:
        return []                      # G1 already owns sidecar resolution; do not double-report
    if str(data.get("result", "")).strip().upper() != "MATCH":
        return []                      # PARTIAL already requires `unmatched:` via G1
    if str(data.get("unmatched", "") or "").strip():
        return []
    return [
        f"G12 [{row_id}] SCOPE-HELD on `result: MATCH` with an empty `unmatched:`.\n"
        f"      A Known Issue is ONE finding and retires ONE claim; the row asserts a grid.\n"
        f"      Answer three questions in the sidecar's `unmatched:` field first:\n"
        f"        1. CAUSE       is the listed issue's mechanism the ONLY way to break this row?\n"
        f"        2. CLAUSE      if the statement is compound (AND/OR/UNLESS), does it cover EVERY leg?\n"
        f"        3. CONSEQUENCE does the issue state the WORST impact, or a milder one?\n"
        f"      Any \"no\" is a residue, and a residue keeps the row live.\n"
        f"      `unmatched: none` is a legal answer -- this checks that you asked, not what you concluded.\n"
        f"      Why: REF-2. An engagement that answered MATCH on the root cause alone lost every finding its contest paid for."]


def check_g16(row_id: str, dedup_rel: str | None, eng: Path,
              require_answers: bool = False) -> list[str]:
    """REF-31. A row that attacks a known issue's fix, mitigation or bound is never retired as a
    duplicate of that issue.

    On engagement 22 rows generated as attacks on a known-issue entry (a critic attacking its stated
    mitigation; a fix-adjacency row saying a fix is stricter than its wording) shared the entry's
    root cause by construction, so a root-cause matcher retired them against the very entry they
    attacked. Other researchers later filed them. Richard's rule (2026-10-19, tooling/match_rule.py):
    such a row is ATTACKS-FIX, a test target, never KNOWN.

    The dedup sidecar records two answers beside `result: MATCH`:
      clause:        issue | accepted | mitigation | bound | fix   (which part of the entry the row's claim is about)
      attacks_entry: yes | no                                       (was the row generated to attack this entry?)
    SCOPE-HELD on a MATCH is refused when `clause` is mitigation, bound or fix, or `attacks_entry`
    is yes: test the row instead (TIER-1, then REFUTED with evidence, or CONFIRMED).

    `require_answers` (the CLI, i.e. new promotions) also refuses a MATCH sidecar that has not
    answered both. The Stop-hook backstop passes False, so the many MATCH sidecars written before
    this rule stay silent; it still enforces the refusal wherever the answers exist. SCOPE: like
    G12, only a sidecar that says MATCH; a SCOPE-HELD with no sidecar is a scope judgement.
    It cannot check that `attacks_entry` is answered truthfully: the ledger does not record a
    row's generator or target. It makes the question unavoidable, as G12 does.
    """
    if not dedup_rel:
        return []
    data, err = load_sidecar(dedup_rel, eng)
    if err or not data or str(data.get("result", "")).strip().upper() != "MATCH":
        return []
    clause = str(data.get("clause", "") or "").strip().lower()
    raw = data.get("attacks_entry")
    # YAML reads `yes`/`no` as booleans; `False or ""` would turn a real "no" into "unanswered".
    attacks = ("yes" if raw else "no") if isinstance(raw, bool) else str(raw or "").strip().lower()
    if clause in ATTACK_CLAUSES or attacks == "yes":
        why = (f"its claim is about the entry's {clause}" if clause in ATTACK_CLAUSES
               else "it was generated to attack this entry")
        return [f"G16 [{row_id}] SCOPE-HELD on `result: MATCH`, but {why}.\n"
                f"      A row that says a known issue's fix, mitigation or bound is wrong ATTACKS the entry;\n"
                f"      it is not a duplicate of it (ATTACKS-FIX, tooling/match_rule.py). Test it instead:\n"
                f"      promote to TIER-1, then REFUTED with evidence or CONFIRMED.\n"
                f"      Why: REF-31, rows were retired this way that other researchers then filed."]
    if require_answers and (clause not in CLAUSES or attacks not in ("yes", "no")):
        return [f"G16 [{row_id}] the MATCH sidecar must answer two questions before SCOPE-HELD:\n"
                f"        clause:        {' | '.join(CLAUSES)}   (which part of the entry the row's claim is about)\n"
                f"        attacks_entry: yes | no   (was this row generated to attack this entry?)\n"
                f"      tooling/known-issue-brief.py returns both with every row's match verdict. Why: REF-31."]
    return []


SCOPE_EXCLUSIONS = "00-triage/scope-exclusions.md"
MIN_EXCLUSION_QUOTE_CHARS = 40


def check_g20(row_id: str, reason: str | None, eng: Path) -> list[str]:
    """G20 (REF-32, Richard 2026-10-26): a hold declared as resting on a scope exclusion quotes it.

    Pre: the row is arriving at SCOPE-HELD and the caller declared that the hold rests on a scope
    exclusion (`cli.py promote --exclusion`). Holds on other grounds (materiality, a partial known
    issue, front-running) are not judged; which holds must declare is parked for Richard. Post: []
    when some run of at least MIN_EXCLUSION_QUOTE_CHARS characters of the reason appears exactly,
    whitespace-normalised, in SCOPE_EXCLUSIONS; otherwise one refusal naming that file, including
    when the file does not exist.

    No exemption for a row whose sidecar says MATCH: one would make calling a row KNOWN the cheapest
    way past this, and a wrong KNOWN is the costly direction (review of this guard, 2026-10-26).

    Engagement 25 (REF-32): the exclusion list was right and a "steer clear" note six lines later
    widened two exclusions into one class-wide kill; four paid findings sat inside it. A ruling that
    cannot quote a rule is our own inference, and the human should see that at Phase 4.
    """
    path = eng / SCOPE_EXCLUSIONS
    n = MIN_EXCLUSION_QUOTE_CHARS
    said = " ".join(str(reason or "").split())
    if path.is_file():
        rules = " ".join(path.read_text(errors="ignore").split())
        if any(said[i:i + n] in rules for i in range(len(said) - n + 1)):
            return []
        why = "no REASON: given" if not said else f"no {n}-character run of the reason is in that file"
    else:
        why = "that file does not exist: write Phase 0's literal exclusion list there"
    return [f"G20 [{row_id}] SCOPE-HELD on a scope exclusion must quote it: the REASON (--reason) needs "
            f"at least {n} characters copied exactly from {SCOPE_EXCLUSIONS}, the Phase 0 exclusion "
            f"list ({why}).\n"
            f"      A ruling that cannot quote a rule is our own inference. Why: REF-32, on engagement 25 a "
            f"\"steer clear\" note widened an exclusion and cost four paid findings."]


# tooling/poc-scaffold.py writes this into every test body it generates, beside the statement
# that makes the unfilled test fail. A cited file that still holds it has a test nobody wrote.
SCAFFOLD_UNFILLED_MARK = "SCAFFOLD-UNFILLED"


def check_evidence_function(row_id: str, evidence: str | None, status: str,
                            eng: Path) -> list[str]:
    """G15 (REF-1): a Forge citation names the test FUNCTION, and that function must exist.

    NEW PROMOTIONS ONLY, and that is the whole design constraint. Rows already REFUTED or
    CONFIRMED citing a bare file keep passing every check -- the state guard runs at `Stop`
    on every engagement on the machine, so a rule that re-judged closed rows would block
    every live engagement the moment the runtime pulled it. So this is called from the
    promotion path, never from the state guard, and the tool-call guard calls it only for a
    ledger file that already existed (see `evaluate`: a file written to a new path has no
    "before", so every row in it would otherwise read as a fresh promotion).

    Why the function and not the file (REF-25, bench/yb6-refutation-coverage-2026-09.md, PR
    #89): 186 refuted rows cite a Forge test, one file holds many rows' tests, and on one
    engagement nine rows cite the same file while one of them is covered only by a different
    row's test. A file citation can read as tested when nothing tested this row.

    Judged on the EXPLICIT evidence value only. check_g2 may fall back to the dedup sidecar
    or to a scan of the whole row, which exists for legacy tables that carry a path in a
    plain column; demanding a function of those would re-judge exactly the rows this must
    leave alone.

    What `function <name>(` does not catch: a declaration that is commented out, one in a
    different contract in the same file, an interface or abstract stub, a test inherited
    from a base contract in another file -- and, always, whether the named test asserts
    anything about this row.

    One thing it does catch: a file written by tooling/poc-scaffold.py and not finished. The
    scaffold declares `test_<ID>_exploit` and `test_<ID>_refuted` itself, so the declaration
    check above passes on a file nobody has touched. Every generated test body carries
    SCAFFOLD_UNFILLED_MARK until it is written or deleted, and a cited file that still holds
    the mark anywhere is refused. Whole file, not the one function: the template says to
    delete the test that does not apply, and a leftover unfilled test is that step skipped.
    """
    if status not in ("REFUTED", "CONFIRMED") or not evidence:
        return []
    out = []
    for tok in EVIDENCE_TOKEN_RE.findall(evidence):
        path, fn = split_evidence(tok)
        if not path.endswith(FORGE_SUFFIX):
            continue
        if not fn:
            out.append(
                f"G15 [{row_id}] {status} cites the test file {path!r} but not the test "
                f"function.\n"
                f"      One file holds many rows' tests, so a file citation reads as tested "
                f"when a different row's test ran the line (REF-25).\n"
                f"      Cite the test function: `poc/test/H7.t.sol::test_H7_refuted`.")
            continue
        art = resolve_artifact(path, eng)
        if art is None:
            continue                   # G2/G10 already own "it does not resolve"
        text = art.read_text(errors="ignore")
        if not re.search(rf"\bfunction\s+{re.escape(fn)}\s*\(", text):
            out.append(
                f"G15 [{row_id}] {art.name} declares no `function {fn}(`. Name a test "
                f"function that exists in the file you cited, e.g. `{path}::test_{row_id}_"
                f"refuted`.")
        elif SCAFFOLD_UNFILLED_MARK in text:
            out.append(
                f"G15 [{row_id}] {art.name} still holds {text.count(SCAFFOLD_UNFILLED_MARK)} "
                f"unfilled scaffold test(s) (marked {SCAFFOLD_UNFILLED_MARK}). A scaffold is not "
                f"evidence. Write each test, or delete the ones that do not apply, then promote.")
    return out


def check_below_bar(row_id: str, reason: str | None, dedup_rel: str | None, eng: Path) -> list[str]:
    """BELOW-BAR (added 2026-09-02): a row that is REAL but cannot clear THIS program's reward
    bar -- a valid Low on a Critical-only contest, say. It is a terminal status needing no
    waypoint (no PoC spend is owed), but it must not become the silent-drop channel the
    immovable rules forbid, so it requires a cited reason NAMING the bar it fails.

    Deliberately NOT the human's call. Scope (in/out of the literal brief) is SCOPE-HELD and
    stays the human's; severity-vs-bar is a judgement the model may make WITH the citation.
    The distinction that matters: the row is LABELLED, never deleted, so a courtesy disclosure
    or a re-file on a platform with a lower bar stays open. Contest-relative, never "not a bug".

    The reason may come from --reason or from a `below_bar_reason:`/`reason:` key in the dedup
    sidecar. A bare "too small" fails the length floor on purpose -- that IS the silent drop.
    """
    r = reason
    if not r and dedup_rel:
        d, e = load_sidecar(dedup_rel, eng)
        if d and not e:
            r = d.get("below_bar_reason") or d.get("reason")
    r = (str(r or "")).strip()
    if len(r) < 20:
        return [f"BELOW-BAR [{row_id}] needs a --reason naming the program bar this row fails to "
                f"clear\n"
                f"      (e.g. 'Critical-only program; this is griefing DoS, not theft or permanent "
                f"lock of principal').\n"
                f"      A bare 'too small' is the silent drop this label exists to prevent. The row "
                f"is LABELLED, not dropped --\n"
                f"      courtesy disclosure or a re-file on a lower-bar platform stays open."]
    return []


def check_blocked(row_id: str, reason: str | None, eng: Path,
                  status: str = "BLOCKED") -> list[str]:
    """BLOCKED (REF-22, bench/improvement-backlog.md, decided 2026-09-24): a row that could
    not be PoC'd. Same shape as check_below_bar's reason requirement -- a bare BLOCKED is
    the silent-drop channel the immovable rules forbid just as much as a bare BELOW-BAR,
    because it needs no waypoint and no evidence, so nothing else forces a reason into a
    field. docs/hypothesis-ledger.md: "record exactly why (missing infra, fork needed,
    unclear oracle)".

    BLOCKED-OUT-OF-HARNESS (2026-09-29) is the same animal one step further out -- the
    exploit needs a relayer or a VM this harness cannot drive -- and it was the last exit
    from the board that recorded no reason at all, so it takes the same requirement.
    """
    r = (str(reason or "")).strip()
    if len(r) < 20:
        return [f"{status} [{row_id}] needs a --reason recording exactly why this row could not "
                f"be PoC'd\n"
                f"      (e.g. 'missing infra', 'fork needed', 'unclear oracle' --"
                f" docs/hypothesis-ledger.md).\n"
                f"      A bare 'too small' is the silent drop this label exists to prevent."]
    return []


def check_refuted_reason(row_id: str, reason: str | None) -> list[str]:
    """REF-26 (decided 2026-09-24, built once REF-22's close-out check shipped): a kill must
    state the argument behind it, not only the file that ran.

    The evidence says a test exists and passed; it does not say what the tester concluded
    from it, so the refutation critic has nothing to attack. Counted on disk 2026-09-29:
    **1 of 237 `REFUTED` rows across ~/engagements carries a REASON: field** (engagement 14
    H7). `tooling/refutation-critic.py`'s docstring recorded the same shape against a smaller
    population. Same length floor as check_below_bar and check_blocked.

    Ordered AFTER REF-22 on purpose: paperwork on a kill pushes rows into `UNTESTED` unless
    something already watches that exit, and the close-out check now does (PR #90).

    New promotions only. `cli.py promote` and the row driver call this; the Stop-hook state
    guard never does, because 236 of those 237 rows predate the rule and must keep passing on
    every live engagement (the population is bench/yb6-refutation-coverage-2026-09.md's).
    """
    r = (str(reason or "")).strip()
    if len(r) < 20:
        return [f"REFUTED [{row_id}] needs a --reason stating the argument this kill rests on\n"
                f"      (e.g. 'the mint path reverts before the overflow, pinned by "
                f"test_R6_refuted at line 41').\n"
                f"      The evidence shows a test ran; the reason is what the critic attacks."]
    return []


# REF-23: the four Phase -1 / provenance fields `ledger/HEADER.md` carries
# (docs/hypothesis-ledger.md "The ledger header"). The six real HEADER.md files on disk
# (2026-09-25) use two spellings: five write `IMPACT BAR  value` (upper case, space-aligned);
# a sixth writes `- **Impact bar:** value` for two of its fields. Both must read
# as present -- the promote check refuses on absence.
HEADER_REQUIRED_FIELDS = ["IMPACT BAR", "MATERIALITY", "RUN", "CUTOFF"]

# RUN is the one field with a required KEY inside it. Since the scaffold started stamping
# `skill=<commit>` into that line (REF-17), a label check alone would read RUN as filled while
# the model and effort that produced the run were still blank -- and RUN exists precisely so
# that two runs can be compared (docs/hypothesis-ledger.md "Why RUN and CUTOFF are in the
# header"). All six HEADER.md files on disk (2026-09-29) write `model=<value>`, so this
# refuses none of them. `model=not recorded` is still a legal answer; an EMPTY one is not.
_RUN_NAMES_A_MODEL_RE = re.compile(r"(?mi)^\s*(?:[-*+]\s+)?[*_]*RUN\b.*\bmodel\s*=\s*[^\s·|]")
RUN_WITHOUT_MODEL = "RUN (names no model=)"


def header_missing_fields(text: str) -> list[str]:
    """Which of the four required header fields are absent from `text`.

    Decoupled from the file path, like check_g1 above, so the same predicate serves the
    doctor (engagement-level: is there a header at all) and the CLI (a promote-to-TIER-1
    precondition, so a false "absent" here would wrongly refuse a real promotion). A field
    counts as present the moment its label is followed by a separator (one space, or a
    colon with optional surrounding space) and then any value -- "not recorded" is a legal
    value (docs/hypothesis-ledger.md: "'not recorded' is a legal value. A guessed value is
    not."), so this only detects the label's total ABSENCE, never judges what it says -- with
    one exception, RUN, which must also name a non-empty `model=` (see _RUN_NAMES_A_MODEL_RE
    above); it is reported as RUN_WITHOUT_MODEL so the message says which half is missing.
    Accepts `LABEL  value` and `LABEL: value` in upper case, and a markdown key form in any
    case -- optional list marker, optional bold/italic, then a REQUIRED colon
    (`- **Impact bar:** value`). The colon is what keeps case-insensitivity safe: a prose
    line such as "Run the generators" has none, so it cannot pass for the RUN field.
    """
    def present(field: str) -> bool:
        label = r"\s+".join(map(re.escape, field.split()))
        canonical = rf"(?m)^\s*{label}(?:[ \t]|\s*:\s*)\s*\S"
        markdown_key = rf"(?mi)^\s*(?:[-*+]\s+)?[*_]*{label}[*_]*\s*:[*_]*\s*\S"
        return bool(re.search(canonical, text) or re.search(markdown_key, text))

    missing = []
    for f in HEADER_REQUIRED_FIELDS:
        if not present(f):
            missing.append(f)
        elif f == "RUN" and not _RUN_NAMES_A_MODEL_RE.search(text):
            missing.append(RUN_WITHOUT_MODEL)
    return missing


def check_g11(path: Path, eng: Path) -> list[str]:
    """A CLI-managed ledger may not be edited as a document.

    G0-G10 all police the CONTENT of a markdown table. G11 polices the CHANNEL: once an
    engagement has an event log, its markdown is a generated render and hand-editing it
    forks the state -- the log says one thing, the file another, and both look
    authoritative.

    Why this is a hook and not prose. `skill/SKILL.md` now tells the agent to use
    `tooling/ledger`, and this repo's own measurement is that prose rules have a
    violation rate: "no argument-kills" is bold, immovable, in two files, and 7 of 11
    parked rows on the engagement 1 run broke it. A wiring instruction is exactly that kind of
    rule, so it needed something outside the model checking it. State-decidable (does
    the log exist?) and silently violated (nothing errors today) -- both criteria in
    CLAUDE.md are met.

    It fires ONLY on engagements that have migrated, so it is silent everywhere else.
    A gate that fires on the common path gets disabled, which is constraint 3.

    The CLI's own renders are invisible here: it writes from Python inside a Bash call,
    and main() only ever sees Write/Edit payloads. No exemption is needed -- verified,
    not assumed (test_the_cli_render_is_not_blocked_by_g11).
    """
    if not (eng / "ledger" / "events.jsonl").exists():
        return []
    cli = TOOLKIT_ROOT / "tooling" / "ledger" / "cli.py"
    return [f"G11 this engagement's ledger is CLI-managed -- `{path.name}` is a GENERATED "
            f"render, and editing it forks the state from ledger/events.jsonl.\n"
            f"      Change state:  python3 {cli} promote "
            f"--id <ID> --to <STATUS> ...\n"
            f"      Then:          python3 {cli} render\n"
            f"      Adding rows:   ... add --id <ID> --hypothesis \"...\"  (or `import <file>`)\n"
            f"      If this is a pre-migration ledger you are retiring, import it and "
            f"delete it -- do not keep two sources of truth."]


def evaluate(path: Path, new_content: str) -> list[str]:
    if is_dedup_sidecar(path):
        return check_sidecar_write(path, new_content)
    if not is_ledger(path):
        eng = engagement_root(path)
        if eng and "poc" in path.parts and not path.exists():
            return check_g1b(path, eng)          # new harness file only, not edits
        return []
    if _in_toolkit(path):
        return []
    eng_early = engagement_root(path)
    if eng_early is not None:
        g11 = check_g11(path, eng_early)
        if g11:
            return g11                         # wrong channel: content checks are moot
    fresh = check_new_ledger(path, new_content)
    if fresh:
        return fresh
    fmt = check_format(path, new_content)
    if fmt:
        return fmt                             # an unparseable ledger cannot be row-checked
    eng = engagement_root(path)
    if eng is None:
        return check_g0(path, new_content)
    existed = path.exists()
    old_content = path.read_text(errors="ignore") if existed else ""
    old, new = parse_rows(old_content), parse_rows(new_content)

    errs = check_g3(old, new, new_content)
    for rid, line in new.items():
        new_st = row_status(line)
        old_st = row_status(old[rid]) if rid in old else None
        # An ambiguous row is reported even when nothing transitioned. The case that found this
        # was exactly a row that LOOKED unchanged: the prose token made old_st == new_st, so the
        # loop `continue`d past a real promotion. Checking before the continue is the point.
        stray = status_token_outside_cell(line)
        if stray:
            errs.append(
                f"G0d [{rid}] the status token `{stray}` appears in this row's PROSE while its "
                f"status cell says `{new_st}`. The guard reads the status cell, so the two "
                f"disagree and the row's status is ambiguous to any human reading it. Reword the "
                f"prose -- say \"has not been run\" rather than naming another row's status.")
        # G13 before the `continue`, for G0d's reason: a row asserting it was FILED, or using
        # `SUBMITTED` as a status, is wrong whether or not it transitioned this edit. It checks
        # an ASSERTION the row makes about itself -- it never gates row creation.
        errs += check_g13(rid, line)
        if old_st == new_st or new_st is None:
            continue
        if new_st == "TIER-1":
            # dedup is owed HERE -- before the spend, which is the whole point
            errs += check_g1(rid, field(line, "DEDUP"), line, eng)
            errs += check_g14(rid, field(line, "DEDUP"), eng)
        elif old_st == "UNTESTED" and new_st in SPEND_STATUSES:
            errs.append(
                f"G1 [{rid}] UNTESTED -> {new_st} skips TIER-1. Reaching {new_st} implies harness "
                f"work, and the dedup obligation is owed BEFORE that spend, not after. Promote to "
                f"TIER-1 with a DEDUP: sidecar first.")
        elif old_st is None and rid in old and new_st in SPEND_STATUSES:
            errs += check_g1(rid, field(line, "DEDUP"), line, eng)
            errs += check_g14(rid, field(line, "DEDUP"), eng)
        if new_st in ("REFUTED", "CONFIRMED", "SCOPE-HELD"):
            errs += check_g2(rid, field(line, "DEDUP"), field(line, "EVIDENCE"), field(line, "HUMAN"), line, new_st, eng)
            # REF-1. Past the `continue` above, so it judges a row ARRIVING at
            # REFUTED/CONFIRMED -- and only when there is a real "before" to compare with.
            # `old` comes from the file on disk, so writing a ledger to a path that does not
            # exist yet reads EVERY row as a fresh transition; without this, copying,
            # splitting or restoring a board would re-judge rows closed before the rule.
            if existed:
                errs += check_evidence_function(rid, field(line, "EVIDENCE"), new_st, eng)
                # REF-26, same reach as G15 above and for the same reason: a row ARRIVING at
                # REFUTED in a file that already existed is a new kill, and a new kill states
                # its argument. Rows already REFUTED on disk are never re-read here.
                if new_st == "REFUTED":
                    errs += check_refuted_reason(rid, field(line, "REASON"))
    return errs


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0                                   # not hook input: stay silent
    ti = payload.get("tool_input", {}) or {}
    fp = ti.get("file_path")
    if not fp:
        return 0
    path = Path(fp)
    try:
        if "content" in ti:                        # Write
            content = ti["content"]
        elif "new_string" in ti:                   # Edit: apply the patch
            base = path.read_text(errors="ignore") if path.exists() else ""
            content = base.replace(ti.get("old_string", ""), ti["new_string"], 1)
        else:
            return 0
        errs = evaluate(path, content)
    except Exception as e:                       # noqa: BLE001  any crash must refuse, not allow
        # Claude Code blocks only on exit 2; a traceback exits 1 and the write goes through. This
        # hook fails CLOSED, so a check that raises refuses the write and says which one failed.
        print(f"BLOCKED by ledger guard: a check raised {type(e).__name__}: {e}. The guard is "
              f"failing closed, so this write is refused. Fix the file being written or the sidecar "
              f"it cites, or report the crash (docs/guard-register.md).", file=sys.stderr)
        return 2
    if errs:
        print("BLOCKED by ledger guard (docs/guard-register.md):", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
