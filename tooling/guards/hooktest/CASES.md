# Live hook test — case suite

Proves the audit-toolkit ledger guards actually fire. `tooling/guards/test_*.py` (56 tests)
cover the guard logic; what only this suite covers is the **wiring and the write path** —
that a hook is registered, and that a rule holds no matter which tool made the change.

    ./reset.sh && python3 verify.py

**Fixtures are built outside this repo**, under `$TMPDIR/audit-toolkit-hooktest/cases`
(override with `HOOKTEST_CASES`). That is not tidiness — `ledger_guard` exempts every path
under `audit-toolkit/`, because `docs/`, `templates/` and `examples/` hold ledger-shaped
documentation that must not be gated. Fixtures kept beside this file inherit that exemption,
so all 22 cases return ALLOW and the suite reports **ALL PASS having run no guard at all**.
That happened on 2026-08-28, the first run after the suite moved here from `~/engagements/`.
`verify.py` now opens with a canary that refuses to run in that state.

`verify.py` drives the guards through their real stdin contract. It does **not** prove the
hooks are registered with Claude Code — only an actual tool call in a live session shows
that, and the frontmatter has silently mis-resolved before. Do one live `Edit` by hand after
any wiring change, then use `verify.py` for the rest.

## PreToolUse guard — `Write|Edit`

| # | case | expected | live 2026-08-20 |
|---|---|---|---|
| 01 | `UNTESTED`→`CONFIRMED` skips the TIER-1 waypoint | BLOCK | ok |
| 02 | →`TIER-1` with no prior-art corpus on disk | BLOCK | ok |
| 03 | →`TIER-1` with no `DEDUP:` pointer | BLOCK | ok |
| 04 | →`TIER-1`, sidecar says `NO-MATCH`, 2 identifiers co-occur | BLOCK | ok — **engagement 3 regression** |
| 05 | →`TIER-1`, `MATCH` with a paraphrased quote | BLOCK | ok |
| 06 | →`TIER-1`, `MATCH` with the real wrapped passage | ALLOW | ok |
| 07 | new `poc/` harness while no row is at `TIER-1` | BLOCK | ok |
| 08 | new `poc/` harness once a row is at `TIER-1` | ALLOW | ok |
| 09 | →`REFUTED` with reasoning and no evidence | BLOCK | ok — **REF-6 failure mode** |
| 10 | →`REFUTED` citing a path that does not exist | BLOCK | ok |
| 11 | →`REFUTED` citing a real `.t.sol`, its test function, and a `REASON:` | ALLOW | ok |
| 23 | →`REFUTED` citing the same evidence with no `REASON:` | BLOCK | ok — **REF-26, 2026-09-24** |
| 12 | →`SCOPE-HELD` with no human record | BLOCK | ok |
| 13 | →`SCOPE-HELD` with `HUMAN:` | ALLOW | ok |
| 14 | a row deleted outright | BLOCK | ok |
| 15 | a row deleted with `MERGED-INTO:` | ALLOW | ok |
| 16 | non-ledger file stuffed with status words | ALLOW, silent | ok |
| 17 | ledger with no `00-triage/` up the tree | BLOCK | ok — **was a silent pass until G0** |

## Stop guard — state, so any write path is covered

| # | case | expected | live 2026-08-20 |
|---|---|---|---|
| 19 | first run in an engagement | ALLOW, records a baseline | ok |
| 20 | `sed -i` promotes `UNTESTED`→`CONFIRMED` | BLOCK | ok — **the bypass, closed** |
| 21 | same violation on the next turn | ALLOW | ok — reported once, not every turn |

## What this suite found

Three silent holes, all fixed on `feat/methodology-guards`:

1. **The row parser could not read the repo's own template.** `ROW_RE` required a hyphen,
   so `H1` — the style `templates/ledger.template.md` emits — parsed as **zero rows**. Zero
   rows means every guard is inert *and says nothing*. Across all ledgers on disk: 79 rows
   parsed before the fix, **112 after**. This sat underneath the other guards, not beside them.
2. **A ledger with no `00-triage/` got no guard at all.** `evaluate()` returned no errors,
   which reads exactly like approval. Now G0, fails closed.
3. **Only `Write|Edit` was guarded.** `sed -i` did the exact promotion case 01 blocks. Now
   covered by the Stop-hook state guard.

**Still open, logged not built:** `engagement 9` and `engagement 7` use a ledger
table whose first column is not an id (`contract`, `subsystem`), so they parse zero rows and
get no guard — silently. The fix is a format convention plus a "looks like a ledger, parsed
no rows" detector, not a looser regex, which would start matching arbitrary tables.
