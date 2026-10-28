"""Write a row's dedup sidecar skeleton, and find a verbatim quote in the prior-art text.

Engagement 23: three sidecars were refused for their form alone — a free-text first
line broke the YAML, a quote spanning a hyphenated PDF line break was not an exact substring, and a
search used fewer than three terms. The skeleton removes the form errors; the quote finder returns
text the G1 quote check accepts. Neither decides a match: the verdict is still the matcher's
(templates/known-issue-filter-brief.md), and the match verdict -> `result:` mapping is read from
tooling/match_rule.py, never restated here.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

TOOLING = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLING / "guards"))
from ledger_guard import SKELETON_TODO, entry_identifiers, g17_hits, g17_source_files  # noqa: E402

_spec = importlib.util.spec_from_file_location("match_rule", TOOLING / "match_rule.py")
match_rule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(match_rule)

# Where G1 and G14 look: the verbatim extracts and the full report text.
CORPUS_DIRS = ("00-triage/potential-risks", "00-triage/prior-audits-text")
TODO = SKELETON_TODO   # G1 refuses a sidecar that still holds it
MIN_TERMS = 3


def corpus_files(eng: Path) -> list[Path]:
    """Every text file G1 and G14 read, in sorted order."""
    return sorted(f for d in CORPUS_DIRS if (eng / d).is_dir()
                  for f in (eng / d).rglob("*") if f.is_file() and f.suffix in (".txt", ".md"))


def _q(text: str) -> str:
    """A YAML double-quoted scalar."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def skeleton(eng: Path, row_id: str, entry: str, verdict: str | None) -> str:
    """The sidecar text for one row.

    Pre: `verdict` is None or one of match_rule.MATCH_VERDICTS (the matcher's match verdict). Post: valid YAML whose answers are all
    `<FILL IN>` placeholders, which G1 refuses wherever they sit (it reads the parsed values, so
    deleting the comments does not help). `searched:` is NOT pre-filled: the corpus files are listed
    as comments for the agent to move up once each is actually searched, because a tool-written
    "searched every file" would satisfy G14 with no reading done (review of this tool). `terms:`
    starts with the entry's bare function names; G17's README and known-issue hits are listed with
    empty notes, which G17 does not accept.
    """
    if verdict is not None and verdict not in match_rule.MATCH_VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(match_rule.MATCH_VERDICTS)} (got {verdict!r})")
    # For KNOWN, result: stays a placeholder: G19 judges a MATCH sidecar in full once result: says
    # MATCH, so writing it is the last edit, after every claim is quoted (found in review).
    if verdict == "KNOWN":
        result = f"{TODO} MATCH once every claim below is quoted from the entry, else PARTIAL"
    else:
        result = match_rule.SIDECAR_RESULT[verdict] if verdict else TODO
    files = [str(f.relative_to(eng)) for f in corpus_files(eng)]
    names = entry_identifiers(entry or "")
    terms = names + [TODO] * max(0, MIN_TERMS - len(names))
    lines = [f"# dedup sidecar for {row_id}, written by `cli.py dedup-skeleton`. Replace every placeholder.",
             "# The match rule and the verdict table: templates/known-issue-filter-brief.md",
             "# (render it with tooling/known-issue-brief.py).",
             "# Corpus files G1 and G14 read. Move each one into searched: once you have searched it;",
             "# a NO-MATCH or PARTIAL must list every one (G14):"]
    lines += [f"#   - {_q(f)}" for f in files]
    lines += ["searched:", f"  - {_q(TODO + ' each file above, once searched')}"]
    lines += ["terms:"] + [f"  - {_q(t)}" for t in terms]
    lines += [f"result: {_q(result)}"]
    if verdict != "NEW":
        lines += [f"quote: {_q(TODO + ' the entry words, copied exactly; cli.py find-quote helps')}",
                  f"unmatched: {_q(TODO + ' what the row claims that the entry does not say')}"]
    if verdict in (None, "KNOWN", "ATTACKS-FIX"):
        lines += [f"clause: {_q(TODO + ' ' + ' | '.join(match_rule.CLAUSES))}",
                  f"attacks_entry: {_q(TODO + ' yes | no')}"]
    if verdict in (None, "KNOWN"):
        # G19: a MATCH quotes the entry for every caller and impact the row claims.
        lines += ["# One item per caller and per impact the row claims. A quote the entry does not",
                  "# hold, or `not stated`, makes the row PARTIAL (G19).",
                  "claims:",
                  f"  - caller: {_q(TODO + ' a caller the row claims')}",
                  f"    quote: {_q(TODO + ' the entry words that state it, or: not stated')}",
                  f"  - impact: {_q(TODO + ' an impact the row claims')}",
                  f"    quote: {_q(TODO + ' the entry words that state it, or: not stated')}"]
    hits = {n: g17_hits(n, g17_source_files(eng), eng) for n in names}
    hit_pairs = [(n, f) for n, by_file in hits.items() for f in by_file]
    if hit_pairs:
        lines += ["# G17: each function the entry names appears in these client documents. Read each",
                  "# hit and say why that line is not this bug; an empty note does not count.",
                  "name_hits_read:"]
        for n, f in hit_pairs:
            lines += [f"  - name: {_q(n)}", f"    file: {_q(f)}", '    note: ""']
    return "\n".join(lines) + "\n"


# A word broken across lines by the PDF extractor: "draw-" then "n" becomes "draw- n" once
# whitespace is collapsed, which is how G1 compares a quote.
_HYPHEN_BREAK = re.compile(r"(?<=\w)- (?=\w)")
_IN_WORD_HYPHEN = re.compile(r"(?<=\w)-(?=\w)")


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _strip_breaks(text: str) -> tuple[str, list[int]]:
    """`text` with hyphen breaks removed, and for each kept character its index in `text`."""
    keep, index, i = [], [], 0
    for m in _HYPHEN_BREAK.finditer(text):
        for j in range(i, m.start()):
            keep.append(text[j]); index.append(j)
        i = m.end()
    for j in range(i, len(text)):
        keep.append(text[j]); index.append(j)
    return "".join(keep), index


def find_quote(eng: Path, wanted: str) -> list[tuple[str, str]]:
    """(file, exact text) for each corpus file holding `wanted`, ignoring whitespace and PDF hyphen
    breaks. The text returned is what G1 compares (whitespace collapsed, hyphen breaks as the file
    has them), so pasting it as `quote:` passes the exact-substring check. Case-sensitive."""
    needle, _ = _strip_breaks(_collapse(wanted))
    if not needle:
        return []
    # A compound word the PDF broke at its own hyphen ("high-\nvalue") reads "highvalue" once the
    # break is stripped, so the typed "high-value" is also tried with its in-word hyphens dropped.
    needles = [needle] + ([_IN_WORD_HYPHEN.sub("", needle)] if _IN_WORD_HYPHEN.search(needle) else [])
    found = []
    for f in corpus_files(eng):
        flat = _collapse(f.read_text(errors="ignore"))
        joined, index = _strip_breaks(flat)
        for n in needles:
            at = joined.find(n)
            if at >= 0:
                start, end = index[at], index[at + len(n) - 1] + 1
                found.append((str(f.relative_to(eng)), flat[start:end]))
                break
    return found
