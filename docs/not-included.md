# What this repository references but does not contain

`README.md` explains why: the hunting workflow — the part of the method that tells a hunter where
to look — is competitive and stays private, while the enforcement machinery here is public. The
files below are the ones that half left behind. Every reference to them in this repository is kept
exactly as it is, on purpose, rather than edited away (`README.md` § "What is not here"). Found by
searching `docs/`, `skill/`, `tooling/` and `README.md` for paths that resolve to nothing in this
repository.

## Project-wide conventions

| file | what it is |
|---|---|
| `CLAUDE.md` | the design principle and guard-layer taxonomy that `docs/guard-register.md` points to for the reasoning behind its own structure |
| `STATUS.md` | a conversion-priority tracker, referenced for where an open backlog item currently stands |

## Phase instructions

| file | what it is |
|---|---|
| `skill/phases/phase-m1-triage.md` | the triage phase instructions — deciding `intended-mainnet` vs `strict-as-deployed` up front |
| `skill/phases/phase-1-hunt.md` | the hunt phase instructions |
| `skill/phases/phase-3-evidence.md` | the evidence phase instructions |
| `docs/target-triage.md` | triage guidance that `docs/hypothesis-ledger.md` cites alongside the triage phase file |
| `docs/gates-checklist.md` | the checklist of labels (reachable? unprivileged? recoverable? material?) attached to each hypothesis row |
| `conduct.py` | the conductor script that runs the phases; `docs/guard-register.md` cites its `OUTPUT_CONTRACT` |

## Hunting tools

| file | what it is |
|---|---|
| `tooling/opposite-tail.py` | a detector that flags a quantity resolved in one direction only (G8a) |
| `tooling/refutation-critic.py` | a red-team critic that checks what a refutation's proof-of-concept did not exercise (G8b) |
| `tooling/fix-adjacency.py` | a scanner that looks for findings adjacent to a prior fix |
| `tooling/known-issue-brief.py` | renders the known-issue matcher's brief and returns each row's match verdict, clause and whether the row attacks the entry (the answers G16 reads) |
| `tooling/poc-scaffold.py` | writes a row's PoC or symbolic check inside the target's test tree; G15 refuses evidence that still carries its unfilled mark |

## Agent briefs

| file | what it is |
|---|---|
| `templates/known-issue-filter-brief.md` | the brief a known-issue matcher is given, with the matching rule rendered into it |
| `templates/prior-audit-key-brief.md` | the brief for turning one prior-audit report into a per-finding key under `00-triage/prior-audit-keys/` |

## Measurement notes under `bench/`

| file | what it is |
|---|---|
| `bench/improvement-backlog.md` | the running backlog of logged defects and planned guards (the `REF-` entries `docs/guard-register.md` cites) |
| `bench/engagements.md` | a summary log of past engagements |
| `bench/cosmos-baseline.md` | a measurement note recording a live prose-kill violation |
| `bench/w6-engagement-notes.md` | measurement notes from one engagement |
| `bench/w6-conversion-result.md` | a measured conversion result from one engagement |
| `bench/yb6-refutation-coverage-2026-09.md` | a measurement of refutation-coverage on one engagement's ledger |
| `bench/ti9-scope-held-measurement-2026-09.md` | a measurement of `SCOPE-HELD` dispositions across engagements |
| `bench/ti9_scope_held_count.py` | the script that produced the measurement above |
| `bench/PREREG-clearance-rows.md` | a pre-registered experiment on whether a hunter's clearance should emit a row for the opposite tail |
| `bench/contract-clearance-clause.md` | the treatment arm of that pre-registered experiment |
| `bench/PREREG-generator-conversion.md` | a pre-registered experiment on hypothesis-generator conversion |
| `bench/PREREG-full-text-grader.md` | a pre-registered grader experiment; one arm showed a model find an unstated claim and still answer "same", which is why G19 decides in code |
