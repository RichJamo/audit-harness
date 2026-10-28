"""Which ledger rows a PoC test file names definitely. The one copy of this check.

Engagement 22, 2026-10-20: two priority-1 rows had been tested the day before, but their ledger
rows still read UNTESTED, so a later screen re-queued them. The ledger said one thing and poc/
another, and nothing compared the two. `tooling/engagement-doctor.py` (the stale-row WARN) and
`tooling/privileged-screen.py` (the existing-tests column) both ask this question, and both
import it from here, so the two cannot disagree about the same row.

Only DEFINITE naming counts, because a PoC comment mentions many rows in passing ("also bears on
X", "cluster: X", "X (PRIOR)") and a check that flagged those would be read as noise. A file
names a row by (a) the id as a whole token of its file name (`H3-HX-16.t.sol`); (b) a line saying "ledger row(s)" followed by a list
holding the id; or (c) a line saying "Representative for" followed by such a list. Validated on
engagement 22: forms (a)-(c) flag 12 rows and none of the 6 passing mentions found there (the
fixture in test_engagement_doctor.py keeps those comments' naming forms).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "guards"))
from ledger_guard import ROW_ID  # noqa: E402

POC_TEST_DIRS = ("poc", "test/poc")
POC_TEST_SUFFIXES = (".t.sol", ".rs", "_test.go", ".ts")
# Build output and dependencies (forge-std under poc/lib) hold no test of ours.
DEPENDENCY_DIRS = {"node_modules", "lib", "libs", "foundry-lib", "out", "output", "cache",
                   "artifacts", "target", "build", "dist", "coverage", "venv", "__pycache__",
                   "broadcast", "typechain", "typechain-types"}

# A list of ids, as written after "ledger rows" or "Representative for": `A-1, A-2 and A-3`.
# The list ends at the first token that is not an id or a separator, so the parenthesised
# "(cluster S4H1-10)" after "ledger rows RQ-14 and RQ-15" is NOT read as a third named row.
_ROW_ID_LIST = rf"`?{ROW_ID}`?(?:\s*(?:,|&|/|\band\b)\s*`?{ROW_ID}`?)*"
NAMING_LINE_RES = (
    re.compile(rf"\b(?i:ledger\s+rows?)\s+({_ROW_ID_LIST})"),
    re.compile(rf"\bRepresentative\s+for\s+({_ROW_ID_LIST})"),
)


def filename_names_row(file_name: str, rid: str) -> bool:
    """True when `rid` is a whole token of `file_name` (form a).

    `H3-HX-16.t.sol` names HX-16: the token before the hyphen, `H3`, is a label, not part of
    the id. `ESC-A-2.t.sol` does NOT name A-2: a bare upper-case prefix (`ESC-`) makes the whole
    of `ESC-A-2` one label. Mixed-case words (`PoC-HX-16`) are prose, so they do not block.
    The id must also end at a non-alphanumeric, so HX-1 is not found in HX-16.t.sol, and a
    split row's test (`HX-16a.t.sol`) is not credited to its parent HX-16.

    Hyphen spelling only. An underscore spelling (`OC_S1H1_2.t.sol`, engagement 22's over-claim
    tests) has the same shape as `ESC_A_2`, so no prefix rule can accept one and refuse the
    other; those files test rows already CONFIRMED, so nothing measured is lost.
    """
    spelled = rid
    start = file_name.find(spelled)
    while start != -1:
        end = start + len(spelled)
        after_ok = end == len(file_name) or not file_name[end].isalnum()
        if start == 0:
            before_ok = True
        elif file_name[start - 1].isalnum():
            before_ok = False
        elif file_name[start - 1] == "-":
            token = re.search(r"[A-Za-z0-9]*$", file_name[:start - 1]).group(0)
            before_ok = not (token.isalpha() and token.isupper())
        else:
            before_ok = True
        if before_ok and after_ok:
            return True
        start = file_name.find(spelled, start + 1)
    return False


def rows_named_in_line(line: str) -> set[str]:
    """Row ids a single line names DEFINITELY (forms b and c); passing mentions are ignored."""
    named = set()
    for pattern in NAMING_LINE_RES:
        for m in pattern.finditer(line):
            named |= set(re.findall(ROW_ID, m.group(1)))
    return named


def poc_test_files(eng: Path, dirs: tuple[str, ...] = POC_TEST_DIRS) -> list[Path]:
    """The engagement's PoC test files under `dirs` (default poc/** and test/poc/**), dependency
    trees pruned, in sorted path order."""
    found = set()
    for rel in dirs:
        base = eng / rel
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in DEPENDENCY_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(POC_TEST_SUFFIXES):
                    found.add(Path(dirpath) / fn)
    return sorted(found)


def files_naming_rows(eng: Path, ids: set[str],
                      dirs: tuple[str, ...] = POC_TEST_DIRS) -> dict[str, list[Path]]:
    """Map each id in `ids` to the PoC test files that name it definitely, in sorted path order.

    Post: only ids from `ids` appear as keys; an id no file names is absent (never an empty list).
    """
    hits: dict[str, list[Path]] = {}
    if not ids:
        return hits
    for test_file in poc_test_files(eng, dirs):
        named = {rid for rid in ids if filename_names_row(test_file.name, rid)}
        try:
            text = test_file.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            named |= rows_named_in_line(line) & ids
        for rid in sorted(named):
            hits.setdefault(rid, []).append(test_file)
    return hits
