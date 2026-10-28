"""The match verdicts a known-issue matcher returns, and what each one writes to a dedup sidecar.

Matching exists to set aside rows that duplicate what is already known, and it must never set
aside a row that is only partly known, because partial matches are where submittable bugs live.
So it is conservative, and it gives each row a match verdict rather than deleting it:

- KNOWN: the same bug as an entry -- the same root cause, the same impact and the same caller or
  call path. Kept, low priority.
- PARTIAL: the root cause matches and something else does not. Kept, and tested early.
- ATTACKS-FIX: the row claims an entry's fix, mitigation or bound is wrong, incomplete or
  bypassable. A different question from "is this known"; never KNOWN, always a test target.
- NEW: matches no entry.

This release carries only the constants the ledger CLI and the guards read. The prose rule a
matcher is given, and the brief that renders it, belong to the hunting workflow and are not
included (`docs/not-included.md`).
"""
from __future__ import annotations

# The match verdicts (called "routes" until 2026-10-20, renamed because "route" read as a work
# queue). KNOWN, PARTIAL, ATTACKS-FIX, NEW.
MATCH_VERDICTS = ("KNOWN", "PARTIAL", "ATTACKS-FIX", "NEW")
# Which part of an entry a row's claim is about: the issue itself, a risk the team accepts, a
# mitigation, a numeric bound, or a fix.
CLAUSES = ("issue", "accepted", "mitigation", "bound", "fix")
# A match on one of these clauses is an attack on the entry, never a duplicate of it.
ATTACK_CLAUSES = ("mitigation", "bound", "fix")
# What each match verdict writes as the dedup sidecar's `result:`. `cli.py dedup-skeleton` reads it.
SIDECAR_RESULT = {"KNOWN": "MATCH", "PARTIAL": "PARTIAL", "ATTACKS-FIX": "PARTIAL", "NEW": "NO-MATCH"}
