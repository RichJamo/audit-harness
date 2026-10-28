"""The target's trust model, read from `01-scope/privileged-actors.md` (REF-33).

Rows whose mechanism needs a trusted role to act first tend to be set aside wholesale as "admin
action, invalid". A prior audit's accepted Medium that needed only an honest governance pause
shows that shortcut loses real findings. So a row naming a privileged role, function or verb is
judged by a privileged-action test before it may leave the work, and G18 in
`guards/ledger_guard.py` refuses `SCOPE-HELD` or `BELOW-BAR` until that test's verdict is recorded.

This module is the part of that rule the guard needs: the roles-file parser, the selection of a
row's privileged terms, and the verdicts the test may return. The worklist tool that hands the
selected rows to a screening agent is part of the hunting workflow and is not included
(`docs/not-included.md`).

INPUT. A per-engagement roles file, `<eng>/01-scope/privileged-actors.md`, filled in per target
from its access-control code (`templates/privileged-actors.template.md` says how). No target's
role names live in this file: the method is generic, the roles are input.

SELECTION. A row is selected when its text names a listed trusted role (whole word, any case), a
listed privileged function (exact identifier) or a privileged verb (PRIVILEGED_VERBS). The bare
word "role" never selects: it matched phrases such as "borrower role" and "role-gated
`liquidate`", which name no trusted actor.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "templates" / "privileged-actors.template.md"

# The privileged-action test's verdicts; ledger_guard.check_g18 accepts these. The test asks
# (a) is the action an honest, plausibly routine one by the trusted role; (b) does an unprivileged
# actor exploit the window, or does the harm land outside the action's scope; (c) does the
# consequence go beyond what the action is documented to do. No verdict retires a row by itself.
#   PASS          (a), (b) and (c) all hold: goes to testing.
#   UNCLEAR       not decidable from the evidence: goes to testing.
#   FAIL          a clause fails, quoted: outside the trust model, so a scope call for the human.
#   NO-ACTION     the text matched but names no privileged action.
#   BOUND-CITED   a bound is cited that would stop the harm: a claim to test, never a kill.
#   SEMI-TRUSTED  only a semi-trusted party acts: the human says how far it is trusted.
VERDICTS = ("PASS", "UNCLEAR", "FAIL", "NO-ACTION", "BOUND-CITED", "SEMI-TRUSTED")

# Generic privileged verbs, true of any protocol with an access-controlled emergency or
# governance path. Deliberately no bare "role": see the module docstring.
PRIVILEGED_VERBS = re.compile(
    r"(?<![A-Za-z0-9_])(?:un)?paus\w*|(?<![A-Za-z0-9_])(?:freez\w*|frozen|halt\w*|deactivat\w*"
    r"|delist\w*|upgrad\w*|governance)(?![A-Za-z0-9_])",
    re.I)
# A role name that is only the generic word would reintroduce the noise the verb list removed.
GENERIC_ROLE_WORDS = {"role", "roles"}

_BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_])"
_BOUNDARY_AFTER = r"(?![A-Za-z0-9_])"




class RolesFileError(Exception):
    """The roles file is missing or holds no trusted role. Its message names the template."""


@dataclass
class PrivilegedActors:
    """The target's trust model as the roles file states it.

    Invariant: `trusted_roles` is non-empty (a file that lists none raises RolesFileError,
    because selecting on verbs alone would silently screen less than the file claims).
    """
    trusted_roles: list[str] = field(default_factory=list)
    trusted_functions: list[str] = field(default_factory=list)
    semi_trusted_parties: list[str] = field(default_factory=list)
    semi_trusted_functions: list[str] = field(default_factory=list)


def _cell_names(cell: str, phrases: bool = False) -> list[str]:
    """Names in one table cell: the backticked spans if any, otherwise comma-separated words.
    Trailing call parentheses are dropped, so `pause()` and `pause` are the same name. With `phrases`
    (the role and party cells), a name may be several words ("vault owner"). A function may
    be qualified by its contract (`Keeper.withdraw`, or `Keeper::withdraw`, stored with a dot),
    and then selects only rows naming that contract's function: a bare `withdraw` would also select
    every row about another contract's user-facing withdraw (engagement 21, 2026-10-21)."""
    spans = re.findall(r"`([^`]+)`", cell)
    raw = spans if spans else cell.split(",")
    names = []
    for item in raw:
        name = re.sub(r"\(.*\)$", "", item.strip()).strip().replace("::", ".")
        shape = r"[A-Za-z_][\w-]*(?: [A-Za-z_][\w-]*)*" if phrases else r"(?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*"
        if name and not name.startswith("<") and re.fullmatch(shape, name):
            names.append(name)
    return names


def parse_privileged_actors(path: Path) -> PrivilegedActors:
    """Read the two tables of a roles file written from the template.

    Pre: `path` exists. Rows under "## Trusted roles" fill the trusted lists, rows under
    "## Semi-trusted parties" the semi-trusted ones; a row whose first cell starts with `<`
    is a template placeholder and is skipped. Post: at least one trusted role, or raises.
    """
    if not path.is_file():
        raise RolesFileError(
            f"no roles file at {path}. Copy {TEMPLATE.relative_to(REPO)} there and fill it in "
            f"from the target's access-control code.")
    actors = PrivilegedActors()
    section = None
    lines = path.read_text(errors="ignore").splitlines()
    for n, line in enumerate(lines):
        heading = re.match(r"^#{2,}\s+(.*)", line)
        if heading:
            title = heading.group(1).strip().lower()
            section = ("semi" if title.startswith("semi-trusted")
                       else "trusted" if title.startswith("trusted") else None)
            continue
        if section is None or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        is_separator = set(cells[0]) <= set("-: ")
        next_is_separator = n + 1 < len(lines) and re.fullmatch(r"\s*\|[\s|:-]*", lines[n + 1])
        if len(cells) < 2 or is_separator or next_is_separator:  # header or separator row
            continue
        if cells[0].startswith("<"):
            continue
        names, functions = _cell_names(cells[0], phrases=True), _cell_names(cells[1])
        if section == "trusted":
            for name in names:
                if name.lower() in GENERIC_ROLE_WORDS:
                    print(f"privileged-actors: ignoring role name {name!r}: the bare word selects "
                          f"noise, not privileged actions", file=sys.stderr)
                elif name not in actors.trusted_roles:
                    actors.trusted_roles.append(name)
            actors.trusted_functions += [f for f in functions if f not in actors.trusted_functions]
        else:
            actors.semi_trusted_parties += [n for n in names if n not in actors.semi_trusted_parties]
            actors.semi_trusted_functions += [
                f for f in functions if f not in actors.semi_trusted_functions]
    if not actors.trusted_roles:
        raise RolesFileError(
            f"{path} lists no trusted role under '## Trusted roles'. Fill it in from "
            f"{TEMPLATE.relative_to(REPO)} (placeholder rows starting with '<' are ignored).")
    return actors


def _word_pattern(names: list[str], ignore_case: bool) -> re.Pattern | None:
    if not names:
        return None
    # A qualified name (`Contract.fn`) matches `Contract.fn` or `Contract::fn`, never the bare `fn`.
    alternation = "|".join(re.escape(n).replace(r"\.", r"(?:\.|::)")
                           for n in sorted(names, key=len, reverse=True))
    return re.compile(f"{_BOUNDARY_BEFORE}(?:{alternation}){_BOUNDARY_AFTER}",
                      re.I if ignore_case else 0)


def _canonical(found: str, names: list[str], ignore_case: bool) -> str:
    found = found.replace("::", ".")
    for n in names:
        if (n.lower() == found.lower()) if ignore_case else (n == found):
            return n
    return found


TEXT_FIELDS = ("hypothesis", "entry", "invariant")


def row_text(row: dict) -> str:
    """The text a row is selected on: its hypothesis, entry and invariant, from the event log."""
    return " ".join(str(row["fields"].get(k, "") or "") for k in TEXT_FIELDS)


def _listed_terms(text: str, roles_or_parties: list[str], functions: list[str]) -> list[str]:
    """Listed names `text` mentions: role or party names as whole words in any case, then
    function names as exact identifiers (backticked). Stable order, no repeats."""
    terms: list[str] = []
    for names, ignore_case, fmt in ((roles_or_parties, True, "{}"), (functions, False, "`{}`")):
        pattern = _word_pattern(names, ignore_case)
        if pattern:
            for m in pattern.finditer(text):
                term = fmt.format(_canonical(m.group(0), names, ignore_case))
                if term not in terms:
                    terms.append(term)
    return terms


def privileged_terms(text: str, actors: PrivilegedActors) -> list[str]:
    """The selecting terms `text` names, in a stable order: roles, then functions, then verbs.
    Empty means the row is not selected."""
    terms = _listed_terms(text, actors.trusted_roles, actors.trusted_functions)
    # A verb that is also a listed function (`pause`, `upgradeToAndCall`) is already named.
    named_lower = {t.strip("`").lower() for t in terms}
    for m in PRIVILEGED_VERBS.finditer(text):
        term = m.group(0).lower()
        if term not in terms and term not in named_lower:
            terms.append(term)
    return terms


def semi_trusted_terms(text: str, actors: PrivilegedActors) -> list[str]:
    """Semi-trusted parties and their functions that `text` names. Annotation only."""
    return _listed_terms(text, actors.semi_trusted_parties, actors.semi_trusted_functions)
