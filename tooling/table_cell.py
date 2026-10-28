"""One markdown table cell: the escape the row generators and the ledger CLI share (REF-30).

A ledger row is a markdown table line and its cells are separated by `|`, so a `|`
inside a value silently re-splits the row: `cli.py import` reads the wrong columns, and
`ledger_guard.field()` cuts the value off at that pipe because a value ends at the next
field key OR at a `|`. A newline breaks the row outright. Neither is visible to
`cli.py verify`, which compares the board with a fresh render -- the corruption
round-trips.

It has already happened on hand-written boards: hypotheses that use mathematical
absolute-value bars (`|U|`, `|q - p|`) had their cell split into three, so the guards
read only the fragment before the first bar. Since REF-26 every REFUTED promotion
carries a prose `--reason`, and prose is where a `|` comes from.

THE ENCODING IS FIXED, not a choice each caller makes: `|` becomes the HTML entity
`&#124;`, which GitHub renders as `|`, and every whitespace run -- newlines and tabs
included -- collapses to one space, which keeps a row on one line. The row generators
(`conduct.py`, `fix-adjacency.py`, `opposite-tail.py`) each carried their own copy of
that one line; this module is the one place it lives, so the write side and the read
side cannot drift.

LOSSY IN ONE DIRECTION, deliberately. `unescape_cell` turns `&#124;` back into `|` and
touches nothing else, so a value that never went through `escape_cell` decodes to
itself -- which is what lets the guards read every ledger already on disk unchanged.
The cost is that prose which contained the literal text `&#124;` before escaping cannot
be told from a pipe afterwards, and a pipe a human hand-escaped as `\\|` stays `\\|`.
"""
from __future__ import annotations

PIPE_ENTITY = "&#124;"


def escape_cell(s) -> str:
    """Make `s` safe to write as one markdown table cell. Not idempotent-safe against
    text that already reads `&#124;`; see the module docstring."""
    return " ".join(str(s).replace("|", PIPE_ENTITY).split())


def unescape_cell(s) -> str:
    """Recover the text `escape_cell` was given, up to whitespace. A value with no
    `&#124;` in it returns unchanged, so existing ledgers read exactly as before."""
    return str(s).replace(PIPE_ENTITY, "|")
