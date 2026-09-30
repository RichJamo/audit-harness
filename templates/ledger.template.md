<!-- ledger-format: table-v1 -->
# Hypothesis Ledger — <PROTOCOL> (<contest>)

**The header lives in `ledger/HEADER.md`, not here** (REF-18). Impact bar, materiality, scope
exclusions, token model and `RUN`/`CUTOFF` provenance all go in that file; `render` composes it
back in above this table on every write. Anything written into this file is lost the moment the
ledger CLI next redraws it — which is now every `add`, `import` and `promote`.

Status taxonomy: `UNTESTED` → `CONFIRMED` | `REFUTED` | `SCOPE-HELD` | `BLOCKED`. Suppress nothing. No argument-kills.

**Keep the table shape.** The guards parse rows out of this table: id in the FIRST cell (`H1`, `H-01`, `AB-1` — at least one digit), status token in the row, and evidence keys (`EVIDENCE:`, `HUMAN:`, `DEDUP:`) written INLINE on the row. A ledger kept as headings or bullets instead parses as zero rows and is silently exempt from every guard — see `docs/hypothesis-ledger.md` §"The row format is a CONTRACT".

| id | hypothesis (one line) | entry point + access | invariant it would break | status | evidence (file:test / PoC / fuzz+canary / scope-rule) | $ / materiality |
|----|-----------------------|----------------------|--------------------------|--------|--------------------------------------------------------|------------------|
| H1 |  |  |  | UNTESTED |  |  |

## Adjudication notes (human-owned)
- `SCOPE-HELD` rows for the human to rule in/out against the literal brief: …
- `BLOCKED` residual blind spots: …

## Submission decision
- Submitting: … (each CONFIRMED + deduped + material + PoC + fix)
- Or: structured negative result — ledger above is the record.
