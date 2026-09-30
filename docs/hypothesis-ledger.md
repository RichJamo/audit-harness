# The Hypothesis Ledger — suppress nothing

The ledger is the spine of the recall-optimized process and the primary deliverable. **Every hypothesis ever
formed gets a row and a visible status.** Nothing is deleted; nothing is killed by argument. The ledger is what
the human reads to adjudicate scope and approve submissions.

## Contents

- The ledger header — REQUIRED, written before the first row
  - Why `RUN` and `CUTOFF` are in the header
  - Fields `SKILL.md` already requires here
- Status taxonomy (a row only ever moves toward evidence)
  - Filing is an ATTRIBUTE of a row, never a status (O-9, added 2026-09-09)
- Row format
  - The row format is a CONTRACT, not a style preference
- Labeling rows for the human (the four gates as a CLASSIFIER, not a killer)
- Why this beats argument-gating

Keep it as a markdown table in the engagement notes (e.g. `audit-notes.md`), one row per hypothesis.

## The ledger header — REQUIRED, written before the first row

Every ledger opens with this block. It exists for two different readers: **the human**, who needs the
scope and materiality rules in front of them when adjudicating rows, and **`bench/`**, which needs to
know what produced the run before any recall number from it can be compared to another.

```
TARGET      <org/repo> @ <scope commit> (<tag or label>), <chain>
INTENSITY   quick pass | standard | differential | exhaustive  (binding) — confirmed <date>
IMPACT BAR  <what actually pays on this program>
MATERIALITY <basis> — ruled <date>
PRIOR-ART   <n> reports; T1 <PASS|FAIL>; digest at <path>
DEDUP RULE  by MECHANISM, not keyword; checked before any PoC spend
FEE         <per-report fee, if any> ⇒ submit only where expected payout > <threshold>
RUN         skill=<toolkit commit> · model=<exact model id> · effort=<low|medium|high|xhigh|max> · harness=<tool + version>
CUTOFF      model cutoff ≤ <date> vs findings published <date> → CONTAMINATED | CLEAN | N/A (live contest)
DATES       opened <date> · closed <date> · results expected <date>
```

**`not recorded` is a legal value. A guessed value is not.** An honest gap is a row `bench/` can exclude;
an invented one silently corrupts a comparison. `bench/w6-engagement-notes.md` already does this
correctly — it says *"pass 1 not recorded"* rather than reconstructing a plausible model string.

### Why `RUN` and `CUTOFF` are in the header

These two lines were added 2026-08-17 because neither was ever recorded, on any run, anywhere in `bench/`.

- **`RUN`** — model and effort are the two settings that change what the same process produces, and they
  can drift between runs without anyone noticing. A recall delta measured across a silent effort change is
  not a measurement of the process change it claims to measure. Read the effort in Claude Code from
  `/config`, or from `effortLevel` in `~/.claude/settings.json`; record the *exact* model id, not a family
  name, because dated snapshots carry different cutoffs. **`skill=` is the third setting that changes
  what the same process produces** (REF-17): the files under `skill/phases/` can move independently, so a
  ledger that does not name the commit it followed cannot be compared with one that followed another.
  `tooling/new-engagement.sh` stamps it from the toolkit it runs out of, and writes `skill=unknown` if
  that directory is not a git checkout — it is never typed by hand.
- **`CUTOFF`** — a model may have trained on the published findings for a historic contest, which inflates
  apparent recall (the I-21 confound). Where a model's cutoff is not published, a **dated snapshot id is an
  upper bound**: `claude-sonnet-4-20250514` cannot have trained on a report published after May 2025.
  Mark `CONTAMINATED` where the bound post-dates publication — the run stays useful for *relative*
  comparisons and is unusable for *absolute* capability claims.

### Fields `SKILL.md` already requires here

Two Phase -1 decisions have always been specified as living in this header; they are now named fields, so
they cannot be improvised at submission time:

- **`MATERIALITY`** — on a pre-launch or testnet target the "% of TVL / deposit" bar has no live basis, so
  the human rules `intended-mainnet` vs `strict-as-deployed` up front (`skill/phases/phase-m1-triage.md`,
  `docs/target-triage.md`).
- **A running-blind note** — if the prior-art corpus could not be acquired, the header carries an explicit
  *"running blind — accept rediscovery cost"* line (`skill/phases/phase-1-hunt.md`). Absence of the note asserts the
  corpus was parsed, not merely downloaded.

## Status taxonomy (a row only ever moves toward evidence)

| Status | Meaning | How a row earns it |
|--------|---------|--------------------|
| `UNTESTED` | formed, not yet attacked | default at creation (Phase 1/2). Must not vanish. |
| `CONFIRMED` | PoC demonstrates theft/lock, unprivileged, above the materiality bar | a runnable Foundry PoC ending on a quantified assertion |
| `REFUTED` | a real exploit attempt provably fails | a PoC that *should* work but reverts/no-ops, OR invariant fuzz green **with a passing coverage canary**. Never prose. |
| `SCOPE-HELD` | a real break exists, but a literal scope rule may exclude it | PoC shows the break; it's admin-gated / documented-in-README-or-tracker / front-running / materiality-borderline → **escalate to the human** |
| `BLOCKED` | cannot build a PoC | record exactly why (missing infra, fork needed, unclear oracle); a residual blind spot, surfaced not hidden |
| `BLOCKED-OUT-OF-HARNESS` | a real gap that can't be PoC'd because the exploit crosses into an **off-chain relayer or another VM** not in the harness | a **capability** gap, not a judgment call — record the exact boundary the exploit needs ("requires the TSS relayer" / "crosses to the SVM side"); kept distinct from `SCOPE-HELD` |

Hard rule: a row **never** goes `UNTESTED → (gone)`. If you didn't test it, it is `BLOCKED` /
`BLOCKED-OUT-OF-HARNESS` or `SCOPE-HELD` and the human sees it. "I reasoned it's fine" is not a status.

`BLOCKED-OUT-OF-HARNESS` (engagement 7) is deliberately distinct from `SCOPE-HELD`: the latter is a *scope
judgment* for the human; the former is a *capability limit* of our harness — an off-chain relayer or a second
VM the exploit needs but we can't drive. Keeping them separate surfaces a running list of capability gaps that
feeds the tooling roadmap, instead of burying a "we couldn't reach it" behind a scope label.

### Filing is an ATTRIBUTE of a row, never a status (O-9, added 2026-09-09)

**`SUBMITTED` is not a status and must not be used as one.** It meant *"a draft was written"* to
whoever wrote it and *"we filed it"* to whoever read it, and on 2026-09-08 that ambiguity cost a real
misreading: `bench/engagements.md` recorded engagement 2 as *"4 SUBMITTED … plus 5 written reports"* while
the platform's own account page showed **1 Submitted, 0 Valid**. Two filed, one withdrawn, one judged.
**Both documents overstated our filing history four-fold.** `SUBMITTED` was also outside the
taxonomy above, so such a row parsed as *statusless* and was invisible to every guard.

**Why an attribute and not a better status word.** The taxonomy above is **epistemic** — it records
whether we believe the hypothesis. Filing is an **action taken on a row we already believe**. Putting
an action in the status cell is precisely what made `SUBMITTED` ambiguous: one field carrying two
axes. Promoting `FILED` to a status would repeat the mistake with better spelling. A row is
`CONFIRMED` **and** carries `FILED:`; those are independent facts and both are needed.

| key | meaning | proof required |
|---|---|---|
| `FILED: <url>` | submitted on the platform | **the platform issue URL.** Without the link this is a claim about our own past — the exact thing that went wrong |
| `DRAFTED: <path>` | written, not filed | a local path. A draft is a local artifact; only a filing needs external proof |

Neither replaces the status. `| H4 | … | CONFIRMED | EVIDENCE: poc/H4.t.sol::test_H4_exploit · FILED: https://… |`

**Enforced by G13** (`ledger_guard.py`), which refuses `SUBMITTED` in a status cell and a `FILED:`
with no URL. It reads the status **cell**, never the line, so a row may still say "submitted a
courtesy note" in prose. **It never gates row creation** — it checks an assertion a row makes about
itself.

**Why this is worth a guard rather than a note.** On Sherlock the Issues Ratio gates all USDC; on any
reputation-gated bounty an invalid filing is a permanent cost. A word that cannot tell a draft from a
filing cannot answer the question that decides whether we get paid — and prose saying "be careful
with SUBMITTED" is the layer this repo has repeatedly measured failing.

## Row format
```
| id | hypothesis (one line) | entry point + access | invariant it would break | status | evidence (file:test / PoC / fuzz+canary / scope-rule) | $ / materiality |
```

Example:
```
| H1 | SharedPosition multi-currency credit can exceed balance | buy() unprivileged | Σcredits ≤ balanceOf(C) | REFUTED | test/invariant/...t.sol 200k calls, canary passes | n/a |
| H7 | owner inflates claimExit _basePrice → zeroes the manager fee | claimExit() owner-only | fee conservation | SCOPE-HELD | test/redteam/...t.sol PoC works; rule="rogue privileged users not valid" | >1% of the manager fee |
| H9 | Distribution under-funding locks late claimers | claim() unprivileged | no-permanent-lock | REFUTED | PoC: bare transfer unsticks claim (recoverable) | n/a |
```

### The row format is a CONTRACT, not a style preference

Every guard in `docs/guard-register.md` operates on **parsed table rows**. A ledger the parser
cannot read is not partially guarded — it is **completely unguarded, and silent about it**.
So the shape below is required, not suggested:

1. **One markdown table row per hypothesis.** Not a `### R-1 ·` section, not a `- **L-C1**` bullet.
2. **The id is the FIRST cell.** An id anywhere else is invisible.
3. **Id grammar:** a capital letter, optional letters/digits, an optional hyphen, then 1–3 digits,
   with an optional trailing lowercase letter — `H1`, `H12`, `H-01`, `H-01b`, `AB-1`, `**HT-80**`.
   Bold markers are fine. At least one digit is required, which is what stops header cells
   (`id`, `File`, `status`, `contract`) parsing as rows.
4. **Status token in the row**, spelled exactly as the taxonomy above.
5. **Evidence keys inline on the row** — `EVIDENCE:`, `HUMAN:`, `DEDUP:`, `MERGED-INTO:`. G2 reads
   these off the row; prose in a paragraph below it is not visible to any guard.
6. **A Forge citation names the test function: `EVIDENCE: poc/H7.t.sol::test_H7_refuted`.** The
   path resolves as before; the function must be declared in that file. One file holds many rows'
   tests, so a file alone reads as tested when a different row's test ran the line — measured on
   nine rows of one engagement (`bench/yb6-refutation-coverage-2026-09.md`). Every other kind of
   evidence (`.rs`, `_test.go`, `.txt`, `.log`) stays a bare path. Rows closed before this rule
   keep their file citations and are never re-judged.

**Measured cost of ignoring this (2026-08-20).** Three different ledger formats were in use across
7 engagements. Only the table format is machine-readable, and the other two were silently exempt
from every rule:

| engagement | format | rows the guards could see |
|---|---|---|
| engagement 3, engagement 5, engagement 1, engagement 6, engagement 8 | table | 25 / 5 / 13 / 36 / 9 |
| engagement 9 | `### R-1 ·` section headings | **0** |
| engagement 7 | `- **L-C1 …**` bullets | **0** |

engagement 9's `R-6` closes a 403-line custom checkpoint library with *"Refuted on every arm read"* and
four paragraphs of reasoning — **no PoC, no evidence path**. That is exactly the argument-kill G2
blocks, and no guard ever saw it, because the row was a heading rather than a table row.

## Labeling rows for the human (the four gates as a CLASSIFIER, not a killer)
Use `gates-checklist.md` to attach labels — reachable? unprivileged? recoverable? material? — to each row.
These labels do **not** delete anything; they tell the human *why* a row is `SCOPE-HELD` vs `CONFIRMED`:
- fails **Unprivileged** (needs admin) → `SCOPE-HELD` (human decides if the program's "rogue privileged" rule applies)
- fails **Recovery** (a bare transfer / any party unsticks it) → `REFUTED` (prove the recovery path with a PoC)
- fails **Reachability** (no real call sequence) → attempt the sequence; if it truly can't be built, `BLOCKED`
- fails **Materiality** (below the %) → `SCOPE-HELD` borderline, or `REFUTED` if provably dust — human's call when close

## Why this beats argument-gating
The old failure was: form hypothesis → *argue* it's safe/out-of-scope → delete it. Every deletion was a
potential missed bounty, made on fallible reasoning, invisible to the human. The ledger makes every such
decision **evidence-backed (PoC) or human-owned (scope)** — and permanently visible. That is recall.
