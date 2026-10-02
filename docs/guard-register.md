# The Guard Register

This file cites files this repository does not contain — `CLAUDE.md`, `docs/gates-checklist.md`
and others. `docs/not-included.md` lists every one of them, with one line on what each is.

**What this is.** The set of methodology rules that are enforced by machinery rather than by prose, the
pass/fail criteria for each, and the measured failure that justifies it. Design principle and layer
taxonomy live in `CLAUDE.md` §"Where a rule lives"; this file is the register itself.

**Why it exists.** Prose rules in this repo have a measured violation rate. "No argument-kills" is bold,
immovable, in two files — and **7 of 11 parked rows on the engagement 1 run broke it**. "Read the full prior-audit
text, not a digest" was learned on engagement 2, written into `docs/gates-checklist.md`, ignored on engagement 3,
and **cost the engagement its only submission**. The rules that hold are the ones something outside the
model checks.

**This register is expected to grow.** A rule earns a place here when it is (a) **state-decidable** and
(b) **silently violated**. Both must hold. A rule the tooling already errors on does not need a guard.

---

## One home per fact

**A guard's reasoning lives in its docstring, not here.** The evidence, the thresholds, the fire rate and
the cost belong four lines from the code they explain, where they get corrected as a matter of course
when the code changes. This register holds what no single docstring can: the row, and how guards relate
to each other and to `SKILL.md`. **Never restate anything that changes when the code does** — a
threshold, a test count, the list of callers — point at the docstring instead. A dated measurement, such
as a fire rate taken before a guard shipped, cannot drift; the backlog is its home.

The measured reason: G14's first entry here restated how the guard tells a finding body from a title
index — the code's job — and its row listed "8 tests + 3 CLI wiring tests + 5 doctor tests". By the
time PR #48 merged, the real counts were 9, 3 and 7, and the row still omitted one of G14's three
callers. It went stale inside the PR that wrote it.

---

## What is enforced today

**This table is the authority on what exists in code.** Until 2026-08-28 this register and
`tooling/guards/` disagreed in both directions: six ids (G4–G9) had rows here and **no
implementation**, while **G0, G0d and G10** ran in production with no row or an unnamed one. Reading
either artifact alone misstated what was enforced. The `state` column uses the same vocabulary as
`bench/improvement-backlog.md` §"SHIPPING STATUS" — `SHIPPED` means enforced in code and covered by
tests, `DESIGNED` means specified here and nowhere else, and `RETIRED` means decided not to build as
a guard. **A guard's row and its code belong in the same commit.**

| id | rule, in one line | state | where |
|---|---|---|---|
| **G0** | a ledger with no engagement root fails closed | `SHIPPED` | `ledger_guard.py` · `check_g0` |
| **G0b** | a ledger that is not a table is invisible to every guard | `SHIPPED` | `ledger_guard.py` · `check_format` |
| **G0c** | a NEW ledger must declare its format | `SHIPPED` | `ledger_guard.py` · `check_new_ledger` |
| **G0d** | status is read from the status **cell**; a status token in the prose is ambiguous | `SHIPPED` | `ledger_guard.py` · `status_token_outside_cell` |
| **G1** | dedup vs verbatim prior-art text before `TIER-1` | `SHIPPED` | `ledger_guard.py` · `check_g1` |
| **G1b** | no file under `poc/` before some row is `TIER-1` | `SHIPPED` | `ledger_guard.py` · `check_g1b` |
| **G2** | `REFUTED` cites evidence that resolves · `SCOPE-HELD` cites a human | `SHIPPED` | `ledger_guard.py` · `check_g2` |
| **G3** | a row may never go from `UNTESTED` to gone | `SHIPPED` | `ledger_guard.py` · `check_g3` |
| **G10** | `CONFIRMED` cites a PoC that exists | `SHIPPED` | `ledger_guard.py` · `check_g2`, same predicate |
| **G11** | a **CLI-managed** ledger may not be edited as a document | `SHIPPED` | `ledger_guard.py` · `check_g11`; bootstrap half reported by `engagement-doctor.py` |
| **G12** | a Known-Issue `MATCH` retiring a row must record what it does **not** cover | `SHIPPED` | `ledger_guard.py` · `check_g12`, called by `cli.py promote` and the state guard *(the state-guard call **crashed the whole hook** from the day it shipped until 2026-09-10 — see below)* |
| **G13** | `SUBMITTED` is not a status; a `FILED:` row cites the platform issue URL | `SHIPPED` | `ledger_guard.py` · `check_g13`, called by the row driver before the transition `continue`; 8 tests |
| **G14** | a `NO-MATCH` dedup is cleared against finding **bodies**, not section extracts alone | `SHIPPED` | `ledger_guard.py` · `check_g14`, charged with G1 at `TIER-1` by `cli.py promote`, the row driver and the state guard; mirrored as a doctor `WARN` |
| **G15** | a **new** `REFUTED`/`CONFIRMED` promotion citing a Forge test names the test **function**, and it exists | `SHIPPED` 2026-09-29 | `ledger_guard.py` · `check_evidence_function` (logged as REF-1 in `bench/improvement-backlog.md`), called by `cli.py promote` and by the row driver for a ledger file that **already existed**. Never by the state guard: 225 rows on disk are closed citing a bare file and must keep passing (`bench/yb6-refutation-coverage-2026-09.md`) |
| **G8** | opposite tail named on every `REFUTED` row | `DESIGNED` · kept | no gate code. Both halves run as generators, wired into `SKILL.md` by #61: G8a `opposite-tail.py`, G8b `refutation-critic.py` |
| **G5** | confidentiality egress: no contest code leaves the engagement | `DESIGNED` · deferred | no code — highest false-positive risk of the set |
| **G4** | coverage canary in the PoC cited by a `REFUTED` row | `RETIRED` 2026-09-24 | never built — no agreed spelling for a canary to check |
| **G6** | supply feasibility on a `CONFIRMED` row (`deal()` ≤ free float) | `RETIRED` 2026-09-24 | never built — needs live chain data at PoC time, so not a ledger hook |
| **G7** | composition pass run before concluding | `RETIRED` 2026-09-24 | never built — omission class |
| **G9** | doc-concession sweep in the repo's own languages | `RETIRED` 2026-09-24 | never built — omission class |

**`RETIRED`** means decided not to build as a guard. It retires the *mechanism*, not the lesson: each
retired row names where its lesson now lives (§"Retired 2026-09-24"). The row stays so the id is never
reused. G6, G7 and G9 were the three rows marked `reframe` (the rule was right and the mechanism named
was wrong), and none of the four had code a month after it was specified.

**Three layers run these rules now, not two.** Added 2026-08-31 (HR-C):

| layer | what it is | binding? |
|---|---|---|
| **`tooling/ledger/`** — the CLI | the predicates as **preconditions of the mutation**. State lives in append-only `ledger/events.jsonl`; `ledger.md` is a generated read-only render | **Yes, and unbypassable** — validation and mutation are one operation, so there is no gap for a write path |
| `ledger_guard.py` | `PreToolUse` on `Write\|Edit`, fails closed | Yes, for the paths it matches — **not** Bash |
| `ledger_state_guard.py` | `Stop`, re-checks from state, fails open | Partly — bounded to 3 blocks/session |

**The CLI is the authority; the two hooks stay as defence in depth.** The guardrails
literature is explicit that layering beats choosing, and an engagement that has not migrated
still needs the hooks. But **new rules belong in the CLI**, not in the parser: the parser is the
trust boundary that made a non-table ledger silently unguarded, and a rule added there inherits
that. Note `G3` needs no CLI implementation — an append-only log has no delete verb, so "a row
may never go from `UNTESTED` to gone" holds by construction rather than by check.

**Two layers ran these rules before that.** `ledger_guard.py` is the `PreToolUse` gate on `Write|Edit`;
`ledger_state_guard.py` re-checks G1, G1b, G2 — and G3 from a snapshot — against the ledger's current
state at `Stop`, so they hold whatever wrote the file. See §"The state guard".

---

## Structure: one guard per ledger transition

The ledger is the chokepoint because every candidate has a row and every decision is a status change.
Guards sit on **transitions**, never on creation.

| Transition | Guard | Question it answers | Status |
|---|---|---|---|
| → `TIER-1` (**mandatory waypoint**) | **G1** dedup vs full prior-art text · **G14** a `NO-MATCH` searched a finding BODY · **G1b** no harness before any `TIER-1` | is this worth spending on? | **`SHIPPED`** |
| → `CONFIRMED` | **G10** cites a PoC that exists · ~~**G6** supply feasibility~~ | is the positive real, and backed? | G10 **`SHIPPED`**, G6 `RETIRED` |
| → `REFUTED` | **G2** evidence cited · ~~**G4** coverage canary~~ | is the negative real? | G2 **`SHIPPED`**, G4 `RETIRED` |
| *(not a gate — Phase 3 generator)* | **G8b** red-team critic over `REFUTED` rows | which direction did the PoC not exercise? | `TOOL`, wired (#61) — `tooling/refutation-critic.py`, `skill/phases/phase-3-evidence.md`; **never a filter**, it fired on 5/5 rows |
| *(not a transition — Phase 1)* | **G8a** opposite tail, as a detector over `hunters/*.md` | was a quantity resolved in one direction only? | `TOOL`, wired (#61) — `tooling/opposite-tail.py`, `skill/phases/phase-1-hunt.md` |
| → `SCOPE-HELD` | **G2** human decision recorded | did a human actually make the call? | **`SHIPPED`** |
| → gone | **G3** rows never vanish | did something disappear silently? | **`SHIPPED`** |
| end of turn | ~~**G7** composition pass run~~ | did we skip the value-adding step? | `RETIRED` |
| *(row creation)* | **none, by design** | — | n/a |

### G12 — a Known-Issue match retires the CLAIM, not the row (REF-2)

**Rule.** A row promoted to `SCOPE-HELD` whose dedup sidecar says `result: MATCH` must have a
non-empty `unmatched:` field.

**Evidence.** *(Cut from this release: the measured evidence for this rule comes from an engagement under a confidentiality agreement.)* What survives the cut is the shape:
a large published Known Issues list retired most of a ledger as `SCOPE-HELD`, every sidecar matched
on the **root cause alone**, and the findings that actually paid were living in the unmatched part.

A contest's duplicate test is a three-way AND — same root cause, **and** in-scope, **and**
same underlying vulnerability. Sharing a root cause is necessary, not sufficient. We treated it as
sufficient and the row died there.

**The model.** A row asserts a **grid** of claims; a claim is one cell — *(cause × clause ×
consequence)*. A Known Issue is a finding and occupies exactly one cell, so a match retires that
cell, not the grid. The three questions map to the three axes, and each is the one a real instance
turned on.

**What it does NOT do.** It never judges whether a residue is real — that needs judgement, is not
state-decidable, and belongs to the human or a prompt hook. `unmatched: none` is a legal answer.
**Requiring the question to be answered is not the same as ruling on the answer**, which is what lets
this ship while the behavioural claim (a residue should be kept live *and funded*) stays unvalidated
and pre-registered.

**Scope, measured before building.** Fires only when a sidecar
exists **and** says `MATCH`. A `SCOPE-HELD` row with no sidecar is a scope judgement — admin-gated,
out-of-scope contract, front-running exclusion — where dedup was never the reason.

Dry run over the ledgers on disk that this release can quote:

| | SCOPE-HELD | fires | no sidecar |
|---|---:|---:|---:|
| engagement 4 | 5 | **2** (H12, H13) | 2 |
| engagement 3 · engagement 5 · engagement 1 · engagement 6 · engagement 7 | 17 | 0 | 17 |
| **total** | **22** | **2** | **19** |

One further engagement's row is cut from this table under a confidentiality agreement, and it held
most of the matching rows. Engagement 4's `H4` is the worked example of `unmatched:` done properly,
with a 382-character residue.

**The first count of that dry run was wrong, and the error is worth recording.** It read the `DEDUP:`
value with `field()`, which returns everything to the next key — and on a row where `DEDUP:` is the
last key that is the whole rest of the cell, so `<eng>/<value>` never resolved and two real sidecars
were scored as absent. Extracting the `.md` path from the value fixes it. A dry run is only as good
as its parse, and this one was checked against the sidecars directly rather than trusted.

**Taxonomy is on probation.** Three axes over three instances, one each, is the shape of a post-hoc
fit, and this repo records two rules that died that way. The defence is that the axes are the
Guidelines' own conjuncts rather than read off the data. **If a fourth instance fits none of the
three, replace the taxonomy — do not extend it.**

**G11 sits ABOVE the table, not in it.** G0–G10 all police the *content* of a markdown row.
G11 polices the **channel**: once an engagement has `ledger/events.jsonl`, its markdown is a generated
render and hand-editing it forks the state — the log says one thing, the file another, and both look
authoritative. It fires before any content check, because if the channel is wrong the content is moot.

**Why it exists.** `skill/SKILL.md` was wired to the CLI in the same PR, and a wiring instruction is
prose — the category this repo has measured decaying. Without G11 the guarantee that the CLI gets used
was "the model read the workflow and chose to," which is precisely what the guard layer exists to
replace. State-decidable (does the log exist?) and silently violated (nothing errored) — both criteria.

**It is deliberately narrow.** It fires only on engagements that have migrated, so it is silent on every
other path; a gate that fires on the common case gets disabled (constraint 3). The bootstrap gap — an
engagement that never creates a log, which G11 cannot see because there is nothing to compare against —
is reported by `engagement-doctor.py` as a `GAP`, not blocked, because no guard refuses on it.

**The G0 family sits underneath this table, not in it.** G0/G0b/G0c/G0d guard whether the ledger is *readable at all* — a root exists, the rows are a table, the format is declared, the status is in the status cell. None is a transition, and every transition check above is worthless without them, because a ledger the parser cannot read is silently unguarded.

**Row creation is deliberately ungated.** Phases 1–2 generate wide and suppress nothing; every row lands
`UNTESTED`. A guard demanding justification before a row can exist would throttle the sweep and damage
recall — trading a rare priced failure for a constant invisible one.

---

## G1 — Dedup against full prior-art text, before PoC spend

**Rule.** Before a candidate is promoted to PoC work, it must be diffed against the **full text** of prior
art — finding bodies, Potential Risks, Observations, accepted and mitigated items — **not** a digest, and
**not** at submission time.

**Evidence (four independent measured failures).**
- **engagement 3 EX-01** (2026-08-19): PoC-backed 7/7, closed **out of scope**; the mechanism was documented
  verbatim in the report's Potential Risks section. Our digest had compressed it to one phrase.
- **REF-3** `[validated-live]`, 3rd project instance: a hunter's "highest-confidence Critical" was Hacken
  F-2026-1000 — covered by the finding *body*, invisible from its *title*.
- **REF-4** `[validated-live]`: dedup owed when a blind lead is *received*, not when a submission is drafted.
- Memory `dedup-by-mechanism-not-keyword`: grepping the corpus for a candidate's own words produced a
  false "uncovered".

**Fires on.** A ledger row leaving `UNTESTED`.

**The `TIER-1` waypoint.** `UNTESTED` → `CONFIRMED`/`REFUTED` is **blocked**: reaching either implies
harness work, and the dedup obligation is owed before that spend. Rows must pass through `TIER-1`, which
is where G1 fires. `BLOCKED`, `BLOCKED-OUT-OF-HARNESS`, `SCOPE-HELD` and `BELOW-BAR` need no waypoint — no spend
happened. Once paid at `TIER-1`, G1 is not re-charged downstream.

**`BELOW-BAR` (added 2026-09-02).** A row that is *real* but cannot clear **this** program's reward bar —
a valid Low on a Critical-only contest, say (engagement 4 H16/H17/H18). Before it, such rows sat `UNTESTED`,
which reads as "not yet looked at" when the truth is "looked at, cannot pay here". It is terminal and
needs no waypoint, but `promote --to BELOW-BAR` requires a `--reason` (or a `below_bar_reason:`/`reason:`
key in the dedup sidecar) that **names the bar it fails**; a bare "too small" is refused by a length
floor, because an uncited below-bar IS the silent drop the immovable rules forbid. It is **not** the
human's call the way `SCOPE-HELD` is: scope (in/out of the literal brief) stays the human's; severity-
vs-bar is a judgement the model may make *with* the citation. The row is labelled, never deleted, so a
courtesy disclosure or a re-file on a lower-bar platform stays open — it means "not rewardable *here*",
never "not a bug". Predicate: `check_below_bar` in `tooling/guards/ledger_guard.py`.

**G1b (the pre-spend trigger).** Creating a file under the engagement's `poc/` is blocked while **no**
row is at `TIER-1` — i.e. nothing has been deduped anywhere. Deliberately coarse: it does not map a
harness file to a row (that would need a naming convention we do not have), and it goes quiet as soon as
one row is promoted. It catches the case that actually cost us — building a harness with zero dedup done.

**PASS requires all of:**
1. **Corpus on disk.** ≥1 file under `<engagement>/00-triage/prior-audits/`, or a `NO-PRIOR-ART.md`
   marker asserting none exists.
2. **Verbatim extracts on disk.** ≥1 file under `<engagement>/00-triage/potential-risks/`, or the marker.
3. **A `DEDUP:` pointer on the row**, e.g. `DEDUP: ledger/dedup/EX-3.md`, resolving to a YAML
   sidecar that contains:
   - `searched:` — file paths, **all of which must exist**, and **at least one under
     `potential-risks/`** (a digest alone never satisfies this);
   - `terms:` — ≥3 search terms;
   - `result:` — `MATCH`, `PARTIAL` or `NO-MATCH`;
   - `quote:` — **required for `MATCH` and `PARTIAL`**, ≥40 chars, and an **exact substring** of
     one of the searched files after whitespace normalisation. Exact matching is the point: it is
     what a paraphrase or a digest cannot satisfy.
   - `unmatched:` — **required iff `PARTIAL`**, ≥40 chars: what was searched for and **not** found.

#### `PARTIAL` — dedup has two kinds of MATCH (added 2026-08-25)

**`PARTIAL` = the ROOT CAUSE matched, the IMPACT or the CONSUMER did not.** It is a factual test,
never a confidence grade — a confidence-graded verdict would repeat the tier-selection and
Critical-only failures, both read off a feeling and both refuted on held-out data.

It exists because the two verdicts owe the human **different reviews**. A `MATCH` needs a
spot-check that the matcher worked — seconds per row, and worth doing: a real spot-check has
caught rows cited against the **wrong** known issue, where the verdict was right and the citation
was not. A `PARTIAL` needs a judgement about whether to spend a
submission on a **grading** argument (the severity is understated, or the listed finding does not
reproduce) rather than a **distinctness** one.

**Status rule:** `MATCH` → `SCOPE-HELD`; **`PARTIAL` stays `UNTESTED` until the human rules**;
`NO-MATCH` unchanged. A `PARTIAL` row is still live and still owes someone a decision — the defect
being fixed is that all three read as done.

**`SCOPE-HELD` means "not submittable". It does NOT mean "do not assert."** A matched invariant is
still the cheapest check on our own model of the code; keep the harness assertion set as a separate
list, not as a status. (`NO_SPEND_STATUSES` in `ledger_guard.py` is **dead code** — defined, read by
nothing. Do not reason from it, as was done once already.)

**Origin.** *(Cut from this release: the measured evidence for this rule comes from an engagement under a confidentiality agreement.)* The shape: dozens of rows matched
the platform's exclusion list, a few were a different animal, and one blanket `HUMAN:` ruling
applied to all of them silently overrode the sidecars that had themselves recorded *"this is a
Phase-4 call and it belongs to the human"*. Nothing errored. **Still owed:** G2 should reject an identical `HUMAN:` string across two `PARTIAL`
rows — state-decidable, silently violated, and not yet built (needs cross-row state that `check_g2`
does not currently have).

4. **Identifier cross-check (content, not form).** The guard extracts identifiers from the row —
   `foo(` calls and `` `backticked` `` symbols, filtered to code-shaped tokens — and requires **≥2
   co-occurring in the same risk section** before it fires. If they do and the row declares
   `NO-MATCH`, **block** and name the section. *This is the check that would have caught engagement 3.*
   **`NO-MATCH` only.** On a `PARTIAL` the identifiers co-occur *by definition* — that is what
   `PARTIAL` asserts — so running it there would fire on every one and get the guard disabled,
   which is constraint 3 in `CLAUDE.md`.

   **Answering it (added 2026-08-26).** The check re-derives identifiers from the ROW on every
   evaluation, so once it fires it fires forever, and the only way to silence it was to delete
   function names from the row — degrading the ledger for a green light. On one engagement, cut
   from this release, that left **four fully-evidenced rows** stuck. It also rewarded vagueness: two
   of its rows concerned the same two functions in the same corpus, and the one that *named* them
   was blocked while the one that described them in prose passed.

   So a sidecar may now record that the check has been answered:

   ```yaml
   cross_check_answered:
     - identifier: updateBoostPeriod
       section: codehawks-2025-02-ALL-findings.txt:181781
     - identifier: updateUserBalance
       section: codehawks-2025-02-ALL-findings.txt:49660
   ```

   It passes only when **every flagged identifier** is listed and **every `section:` names a file
   that exists under `potential-risks/`**. This demands MORE work rather than less — you cannot
   satisfy it by shortening the row, because it asks what you READ, not what you WROTE. Listing
   identifiers the check did not flag buys nothing.

   **Still owed** (deliberately NOT shipped with this, because it makes the check fire *less* and
   that is the wrong direction to move during a live engagement): `IDENT_STOPWORDS` covers six
   names and misses the ERC20 surface — `INV-06` was flagged on `balanceOf` — and matching is by
   substring, so `getVotingPowerAtTime` matches inside `getVotingPowerAtTimestamp`. Both are in
   `bench/improvement-backlog.md` under REF-5.

### Why a sidecar and not an inline block

Ledger rows on a real engagement average **694 characters** and the engagement 3 EX-3 row is **2,638**.
Appending evidence inline made the least readable artifact worse, and — decisively — a single table
row **cannot hold a multi-line quote at all**. `pdftotext` hard-wraps, so an honest copy-paste of a
real passage arrives with line breaks in it. The sidecar makes verbatim quoting possible; inline it
was not expressible.

```yaml
# ledger/dedup/EX-3.md
searched:
  - 00-triage/potential-risks/EX-potential-risks.txt
terms: [setAttributeMetadata, new-attribute waiver, consent]
result: MATCH
quote: |
  Cross-hierarchy accreditation of any DID via the new-attribute waiver: checkEligibility skips
  the trust-chain membership check whenever the target attribute does not yet exist
```

**FAIL →** exit 2, naming precisely which condition failed.

**Known limit.** Verifies that a real search happened against real source text. Cannot verify the
*relevant* paragraph was read. Mitigated by (4) and by G14, fully addressed only by a later prompt hook.

---

## G14 — a `NO-MATCH` is cleared against finding BODIES, not section extracts (REF-3)

**Rule.** A row promoted to `TIER-1` on `result: NO-MATCH` must have searched at least one file holding
prior-audit finding **bodies**, whenever the engagement holds one.

**Relation to G1.** G1 asks whether a real search happened against verbatim text. G14 asks whether the
corpus searched *could have held the match at all*: `potential-risks/` holds section extracts, and a
finding is not a section.

**Why it exists, how a body is told from a title index, what it costs, and its measured fire rate:** the
`check_g14`, `is_finding_body` and `finding_body_files` docstrings in `ledger_guard.py`, and
`check_finding_bodies` in `engagement-doctor.py`. Not restated here — see §"One home per fact".

**Deliberately out of scope: the hunter brief.** `skill/phases/phase-1-hunt.md` step 3 still briefs hunters from a digest.
Requiring bodies there would gate row creation, which constraint 1 forbids; the obligation is charged
where the spend is committed instead.
---

## G2 — Evidence-cited disposition (no prose-kills)

**Rule.** A hypothesis is killed by a failed PoC or escalated to a human — never by prose.

**Evidence.** REF-6: **7 of 11 parked rows** on the engagement 1 run were argument-kills; all three sharing one
wrong premise were refuted on re-test, and one turned out not to be a finding at all rather than "real but
out of scope". Second live violation logged at `bench/cosmos-baseline.md:131`. This rule has been
*immovable in prose* for the entire life of the repo and has the worst measured compliance of any rule here.

**Fires on.** A row transitioning to `REFUTED` or `SCOPE-HELD`.

**PASS requires:**
- `REFUTED` → an `EVIDENCE:` key naming **a path that exists on disk**, and that path must look like a
  test/PoC artifact (`.t.sol`, `.spec.ts`, `_test.go`, `.rs`, or a captured run output).
- `SCOPE-HELD` → a `HUMAN:` key recording that a person made the call, with the date. Scope is the
  human's decision; a model recording its own reasoning here is the failure mode, not the rule.

**FAIL →** exit 2. A disposition with justification prose but no citation is exactly the target.

**Known limit.** Checks that evidence is cited and exists — not that it tests the right property.
That is REF-7's failure mode and needs the prompt hook (planned).

---

## G10 — A `CONFIRMED` row must cite a PoC that exists

**Rule.** G2 protects *kills*; G10 protects *claims*. Same predicate, opposite failure: a `REFUTED`
row with no evidence is an argument-kill, a `CONFIRMED` row with no evidence is an unbacked finding.
Nothing was required of `CONFIRMED` until 2026-08-20.

**Evidence.** REF-8: an invite-only review platform's submission form marks Proof of Concept
**`(optional)`**. "No PoC ⇒ no submission" has never broken in this repo — because *HackenProof
returns an error*. It was enforced by one platform, not intrinsically. On a platform that accepts a
PoC-less report the rule reverts to prose, the class that has failed three times (REF-6,
engagement 3, `cosmos-baseline.md:131`). One engagement, cut from this release, was on such a
platform.

**Fires on.** A row transitioning to `CONFIRMED` (and on `CONFIRMED` state, in the Stop-hook guard).

**PASS requires** a PoC/run artifact named on the row that resolves to a file. `EVIDENCE: <path>` is the
documented form, but the check reads **content, not form** — see below.

### The resolver, and why judging on form was wrong

Two fixes landed with G10, both from measuring before building rather than after:

1. **Bare basenames resolve.** Real ledgers cite `PoC_H01_FeeBypass.t.sol` with no path while the file
   sits in `test/`. Measured across every row at `CONFIRMED`/`REFUTED` on disk, a literal-path-only
   rule resolved **1 of 16**; resolving by basename inside the engagement (pruning build/vendor trees)
   takes that to **4 of 4** of the rows that name an artifact at all.
2. **No `EVIDENCE:` key required.** Three of engagement 6's five `CONFIRMED` rows carry the artifact in a
   plain evidence *column*. Demanding the key would have blocked three properly-evidenced rows — the
   same form-over-content mistake the G1 identifier cross-check was rebuilt to avoid. The check now
   scans the whole row and falls back to naming what it found but could not resolve.

**Measured after both fixes:** `CONFIRMED` **5/5** rows pass. `REFUTED` **1/11** — and that is the
right answer, not a bug: the other ten name no artifact anywhere. They are the historical
argument-kills (engagement 3 ×4, engagement 1 ×5, engagement 6 ×1), and G2 has simply never seen them because it
fires on transitions. **REF-6's failure mode, measured across the whole corpus at 10 of 11.**

**Known limit, inherited:** this proves an artifact of that name exists, not that it tests the right
property; a bare basename could match the target's own test. Citing a repo-relative path removes the
ambiguity and is what the template asks for.

---

## G3 — A row may never go from `UNTESTED` to gone

**Rule.** Rows are never deleted. If it can't be tested it is `BLOCKED` / `BLOCKED-OUT-OF-HARNESS`,
surfaced as a residual blind spot.

**Evidence.** Already stated at `skill/phases/phase-3-evidence.md`. No measured violation — this guard is *preventive*,
and it is here because it is the cheapest check in the set and its violation is perfectly silent: nobody
notices an absence. It also protects recall directly, which is the north star.

**Fires on.** Any `Write`/`Edit` to a ledger file.

**PASS requires:** every row ID present in the on-disk file is still present in the proposed content.

**Escape hatches (explicit, in-content — never by disabling the hook):**
- `MERGED-INTO: <row-id>` — the surviving row must be present in the same file.
- `LEDGER-DELETE-APPROVED: <reason>` — a deliberate, recorded human override.

**FAIL →** exit 2, naming the vanished row IDs.

---

## G0 — A ledger with no engagement root fails closed

**Rule.** If `engagement_root()` cannot find a `00-triage/` directory, no guard can run.
Say so and refuse; never return "no errors".

**Evidence.** Live hooktest case 17 (2026-08-20): the exact `UNTESTED` → `CONFIRMED`
promotion that case 01 blocks went through **untouched**, purely because the directory had
no `00-triage/`. Previously listed on this page as "Caveat, unguarded by design so far" —
`evaluate()` returned no errors rather than complaining it could not find the root. Same
shape as the frontmatter path bug: **an absent guard reads exactly like a satisfied one.**

**Fires on.** A `Write`/`Edit` to a file that `is_ledger()` matches and that parses ≥1 row,
when no engagement root exists.

**PASS requires:** a `00-triage/` directory in some parent. The message names the `mkdir`.

**Deliberately narrow**, so it cannot become the gate everyone disables:
- files inside the toolkit repo are exempt (`docs/hypothesis-ledger.md`, `templates/`,
  `examples/` are documentation, not engagements);
- a file with no parsed rows is exempt — nothing ledger-shaped to protect, and firing on
  any `.md` with "ledger" in its name would be pure noise.

**Known blast radius at introduction.** Two engagements on disk have ledger rows and no
root: `engagement 8` (9 rows) and `engagement 6` (36 rows). Both are closed; editing
either now blocks until a `00-triage/` is created. `engagement 7` also
lacks a root but parses 0 rows, so it stays silent.

---

## G0b — A ledger that is not a table is invisible to every guard

**Rule.** Hypotheses are markdown table rows. A ledger kept as section headings or bullets
parses as zero rows, and a guard that parses zero rows enforces nothing *and says nothing*.

**Evidence (measured 2026-08-20).** Three ledger formats were in use across 7 engagements,
and only one is machine-readable:

| engagement | format | rows the guards could see |
|---|---|---|
| engagement 3 · engagement 5 · engagement 1 · engagement 6 · engagement 8 | table | 25 · 5 · 13 · 36 · 9 |
| `engagement 9` | `### R-1 ·` section headings | **0** |
| `engagement 7` | `- **L-C1 …**` bullets | **0** |

engagement 9's **R-6** closes a 403-line custom checkpoint library with *"Refuted on every arm
read"* and four paragraphs of reasoning — **no PoC, no evidence path**. That is precisely the
argument-kill G2 blocks, and no guard ever saw it, because the row was a heading.

**Why not teach the parser all three formats.** Evidence keys (`EVIDENCE:`, `HUMAN:`,
`DEDUP:`) live *inline on a row* and have no agreed position in a heading or a bullet, so a
wider parser would find the id and still have nothing for G1/G2 to read. One format, stated
in `docs/hypothesis-ledger.md` §"The row format is a CONTRACT", with deviation made loud.

**Fires on.** A ledger write where zero table rows parse **and** ≥2 hypothesis-shaped ids
appear in headings or bullets. The ≥2 threshold keeps a freshly-created ledger — header block,
no hypotheses yet — silent, because **row creation is never gated**.

**Blast radius at introduction:** `engagement 9` and `engagement 7` block on edit
until converted. Zero false positives across the other 8 ledger-shaped files on disk.

---

## A row needs a status — and why that was suppressing G0b

**Rule.** A line is a ledger row only if it has an id in the first cell **and** a status token.

**Why.** Ledgers carry other tables — a hunter roster, a status summary, a dedup matrix — whose
first cell also looks like an id. `engagement 8`'s roster (`| H1 | territory: rewards.rs | 9 |`)
parsed as 8 ledger rows.

**The miscount was not the damage.** G0b originally fired only when a file parsed **zero** rows, so
an incidental side table gave `engagement 8` (9) and `engagement 5` (5) a healthy-looking row count
and **suppressed the wrong-format detector** — while the real hypotheses in both sat in `## C1` /
`### R-6` headings that no guard could read. `engagement 9` escaped the same fate only because its side
table happened to be keyed on contract names rather than ids. **Any ledger with a roster or summary
table was silently exempt from the format check.**

**So G0b now compares, rather than testing for zero.** It fires when off-table hypothesis ids
**outnumber** readable table rows. That is what catches a file holding one real row and fourteen
heading hypotheses. Measured across all nine ledger-shaped files: fires on exactly `engagement 8`
(1 row vs 14 heading ids) and `engagement 5` (0 vs 11); silent on the six well-formed ledgers,
including `engagement 7` (15 rows vs 8 bullet ids in a verbatim appendix) and `engagement 6` (34 vs 13).

A second trigger covers the other shape: a table of id-keyed rows where **none** carries a status,
so every transition check skips every row.

**Rows recovered rather than lost.** Requiring a status would have dropped four real hypothesis rows
whose disposition was written in vocabulary outside the taxonomy. Three were given a taxonomy status
instead of being discarded:
- `engagement 3` **EX-3** — `SUBMITTED-REJECTED (out of scope)` → **`SCOPE-HELD`** plus the `HUMAN:`
  record. This is the row the whole G1 guard exists because of, and it was invisible.
- `engagement 8` **H8-04** — status cell was a bare em-dash → **`UNTESTED`** (never PoC'd).
- `engagement 6` **H-05** (`SOLVED`) → **`REFUTED`** as an ongoing leak, citing
  `poc/H-05-onchain-verification.txt` — the on-chain verification (balanceOf @47870188 equals
  the shortfall @49873088 on all four tokens) extracted into a file so G2 has a path to check.
  It is a verification record, not a Foundry PoC, because the defect is historical state with
  no exploit to run forward; recorded on that basis.
- `engagement 6` **H-29** (`PARTIAL`) → **`SCOPE-HELD`** with a `HUMAN:` record (RJ 2026-08-20):
  a build-configuration risk rather than a contract defect.

**Net: no row was lost.** All four kept their evidence and gained a taxonomy status; every
well-formed ledger now parses every one of its rows (engagement 3 25/25, engagement 6 36/36, engagement 9
10/10, engagement 7 15/15, engagement 1 13/13).

**Taxonomy gap this exposed.** Real engagements reached for words the taxonomy does not have:
`SUBMITTED-REJECTED`, `DEDUP-DEAD`, `SOLVED`, `PARTIAL`. Two of those map cleanly (`SCOPE-HELD`,
`SCOPE-HELD`); `SOLVED` and `PARTIAL` do not, and `SOLVED`'s evidence on engagement 6 is **on-chain
verification rather than a PoC file**, which G2 has no slot for. Whether the taxonomy should grow or
those rows should be mapped is a human call, not a parser change.

---

## G0d — Status is read from the status CELL, never the whole line

**Rule.** A row's status is whatever its status **cell** contains. A status token appearing in the
row's prose while the cell says something else makes the row ambiguous, and the guard says so.

**Evidence (REF-9; the engagement is cut from this release).** `row_status()` scanned the entire
line and returned the first token in `STATUSES` order, and `UNTESTED` is first. A row whose status
cell read `` `REFUTED` `` but whose prose said "… is still UNTESTED" was **reported as
`UNTESTED`**. The miscount was the
smaller half: `evaluate()` computed `old_st == new_st == UNTESTED`, hit `continue`, and reported PASS
— so a real `UNTESTED → TIER-1 → REFUTED` promotion went through with **no G1 and no G2**. Found by
accident, from an honest cross-reference in a note. Nothing errored.

**Fires on.** A row whose prose contains a status token that its status cell does not.
Reported even when nothing transitioned — the row that found this looked unchanged, which was the point.

**Deliberately narrow.** A row restating **its own** status in prose ("kept UNTESTED because the
precondition is unproven") is silent; firing there would be noise, and a noisy gate gets disabled.

**Fix (`67d7a08`).** Status comes from the cell; the whole-line read survives only as the fallback for
non-table text, so heading-style ledgers still yield a status. Re-reading every ledger on disk after
the change: 109 rows, 0 ambiguous.

---

## Ledger discovery — one function, both layouts

**The bug.** `check_g1b` globbed `<engagement>/ledger/*.md`. Two engagements keep the ledger flat
at `<engagement>/ledger.md` (`engagement 6`, `engagement 8`), so it found **no ledger at all**,
concluded no row had ever reached `TIER-1`, and blocked **every** `poc/` file — permanently, on a
condition no edit could satisfy. That is the noisy-gate failure this register warns about, and it
contradicted `is_ledger()`, which accepts both layouts. Found by hitting it while adding a real
evidence file to engagement 6.

**The fix.** One `engagement_ledgers()` walks the engagement and returns everything `is_ledger()`
matches, in any layout; both the PreToolUse guard and the state guard use it. Heavy trees
(`out/`, `cache/`, `lib/`, `node_modules/`, `target/`, `repo/`, dotdirs) are pruned — they never
hold a ledger and walking them on a real checkout is pure cost. Pinned by `TestLedgerDiscovery`,
including the engagement 6 regression and the prune case.

---

## G0c — A new ledger must declare its format (and why detection alone is not enough)

**The question this answers.** Is the row format a suggestion the model may ignore, or something
that holds every time? Four layers, and only the last two are binding:

| layer | mechanism | binding? | what it misses |
|---|---|---|---|
| `docs/` + template prose | advisory | **No** — this repo has measured prose rules being ignored | everything, if the model does not read it |
| **G0b** detector | blocks a ledger with 0 rows and ≥2 off-table ids | **Yes**, for shapes we have seen | a **novel** shape whose ids it does not recognise still parses as 0 rows and stays silently exempt |
| **G0c** declaration | a NEW ledger must carry `<!-- ledger-format: table-v1 -->` | **Yes**, for any shape | nothing about format — but relies on someone reacting to the block |
| **`tooling/new-engagement.sh`** | copies the template | **Structural** — right before anyone can get it wrong | only applies if the scaffold is used; G0c is the backstop when it is not |

The order matters. Detection can always be out-run by a format nobody anticipated; a **declaration
cannot**, which is why G0c is a positive assertion rather than another detector. And a scaffold beats
both, because it removes the decision instead of policing it — the same reason "no PoC ⇒ no submission"
holds: the platform *errors*, so there is nothing to remember.

**Fires on.** Creating a ledger file with no format marker. **Existing ledgers are grandfathered** —
requiring the marker everywhere would block five engagements on disk for no gain, and a gate that fires
on everything gets disabled.

**This gates FILE creation, never ROW creation.** The cost is one line, it demands no justification for
any hypothesis, and it cannot throttle the Phase-1 sweep — a test pins that adding 19 rows to a declared
ledger stays silent. If that reading of the row-creation rule is ever judged too liberal, G0c is the
piece to drop, not G0b.

---

## The state guard — same rules, checked on the artifact instead of the tool call

**A crashed Stop hook and a clean one look identical. Fixed 2026-09-10, found by review.** The G12
backstop inside `state_violations()` read `msgs.append(m)`, and `msgs` is bound in `main()`, not there.
So the function raised `NameError` on **any** engagement holding a `SCOPE-HELD` row whose dedup sidecar
says `result: MATCH` with an empty `unmatched:` — and one engagement, cut from this release, held
dozens of them. `main()`
catches only `OSError`, so the hook died with a traceback and **G1, G2, G12 and G14 all went unenforced
for that engagement**, silently, for the life of the defect. Two regression tests now pin it, one
calling `state_violations()` directly so a future `try/except` in the caller cannot re-hide it.

This is the register's own lesson turned on the register: a guard's ROW said `SHIPPED`, its CODE existed,
its tests passed — and one of its two call sites had never once run to completion.


**The hole it closes.** `ledger_guard.py` is a `PreToolUse` hook matching `Write|Edit`, so
it only ever sees a transition proposed through those two tools. Everything else writes to
a ledger unguarded: `sed -i`, a heredoc, `tee`, `python -c`, or a subagent that picked Bash.
Measured live (hooktest case 18, 2026-08-20): `sed -i` performed the exact
`UNTESTED` → `CONFIRMED` promotion the PreToolUse guard blocks, with no block and no
message. **This is the default path, not an evasion** — Claude Code's auto-mode instructs
the model to prefer `sed`/heredocs over the Write and Edit tools.

**Why not just add `Bash` to the matcher.** Deciding whether an arbitrary shell command
writes to a ledger is undecidable in general — the path can sit in a variable, behind a
script, or on the far side of a pipe. A Bash matcher catches the obvious shapes and misses
the rest, still silently; tightening it means firing more often, and a noisy gate gets
disabled. **Restricting the model to `Write|Edit` fails for a different reason:** the shell's
write surface is unbounded (`sed`, `tee`, `cat >`, `python -c`, `perl -pi`, `awk`, `cp`), an
audit run genuinely needs Bash for `forge`/Slither/Aderyn/`git`, and a permission denial
says "not allowed" where a guard says which rule is unmet — throwing away the information
that makes a block useful.

**So it changes what is checked, not which tool.** Every rule here except G3 restates
cleanly as an invariant over the ledger's *current state*, which is write-path agnostic:

| register rule | as a state invariant |
|---|---|
| G1 | a row at `TIER-1`/`CONFIRMED`/`REFUTED` **carries** a valid `DEDUP:` sidecar |
| G1b | a file under `poc/` implies ≥1 row at `TIER-1` or beyond |
| G2 | a `REFUTED` row has an `EVIDENCE:` path that exists; `SCOPE-HELD` has a `HUMAN:` record |
| G3 | needs history — supplied by a row-set snapshot in `<engagement>/.guard/` |

**Detective, not preventive — and that is why it supplements rather than replaces.** When
this fires the bad write has already landed. G1 exists to make the dedup happen *before* the
harness hours, and only an intent-time gate can do that. The `PreToolUse` guard stays as the
preventive fast path with the actionable message; this one guarantees the violation cannot
pass unnoticed, whatever wrote it.

**Two anti-noise controls, both load-bearing:**
- **Grandfathering.** The first run in an engagement records a baseline and reports nothing.
  Without it the guard would open by dumping every pre-existing violation in a mature ledger
  — exactly how a gate earns a reputation for noise and gets switched off. Enforcement starts
  from the state it inherited. A violation is reported once, not every turn.
- **Bounded blocking.** A `Stop` hook that blocks forever is worse than the violation it is
  chasing: the model cannot route around it, so an unfixable state burns the budget. After
  3 blocks in one session the guard yields and writes the unresolved items to
  `<engagement>/.guard/UNRESOLVED.md`, so the failure becomes durable rather than merely
  repeated.

**Fail-open on a missing script, deliberately — the opposite of the `PreToolUse` choice.**
A missing `PreToolUse` guard fails closed because the model can always escape by not
writing. A `Stop` hook cannot be escaped at all, so failing closed there traps the session.
The compensating control is that the `PreToolUse` guard still fails closed, so a missing
guards directory is caught on the first ledger write.

**Scope.** Validates the engagement containing the session `cwd`; if `cwd` is a container of
engagements it scans one level down, restricted to ledgers modified in the last 24h so
closed engagements stay quiet. `AUDIT_ENGAGEMENT_ROOT` targets one explicitly.

**That scope reaches live engagements from anywhere, which is the point and was also a hole in the
TESTS.** Because `engagement_roots()` scans `~/engagements` regardless of `cwd`, running
`hooktest/verify.py` rewrote `.guard/ledger-state.json` for three live engagements on 2026-08-28 and
**grandfathered the violations they held at that moment** — and grandfathered violations are never
reported again, so the real session would never have heard about them. The suite now pins
`AUDIT_ENGAGEMENTS_ROOT` to its fixtures for every subprocess, its canary refuses to run without
that, and `TestHooktestSandbox` pins both. Same family as the fixtures-inside-the-toolkit failure:
**a test that reaches production does not just risk damage, it can silence the thing under test.**

| file | what |
|---|---|
| `tooling/guards/ledger_state_guard.py` | the guard; reads Stop-hook JSON on stdin, exit 0 silent / exit 2 blocks the turn |
| `tooling/guards/test_ledger_state_guard.py` | 14 tests incl. the sed-bypass regression, grandfathering, and the loop-safety bound |
| `skill/SKILL.md` frontmatter | the wiring: `Stop` → the command that runs it |

---

## Planned — specified here, no gate code exists

Both rows below are `DESIGNED`: a specification in this file and nothing in `tooling/guards/`. Until
2026-09-24 this table held six rows; four were retired (§"Retired 2026-09-24", below).

| id | rule | state | why it qualifies | evidence |
|---|---|---|---|---|
| **G8** | Opposite-tail named and tested on every `REFUTED` row | `DESIGNED` · kept · **wrong phase — see below** | presence decidable; correctness is judgement → hybrid | REF-10 `[validated-live]`, generalises the engagement 2 M-1 failure. Kept 2026-09-24 because both halves already run as tools (G8a, G8b) with live evidence |
| **G5** | Confidentiality egress: no contest code leaves the engagement | `DESIGNED` · deferred | outbound guardrail; harms a third party, not us | **deliberately deferred** — highest false-positive risk of the set. Re-affirmed 2026-09-24 |

## Retired 2026-09-24 — decided not to build as guards

Rich decided this on 2026-09-24 (`bench/improvement-backlog.md`, the guard-decision lines under the DM
table, in REF-11 and under the TV table). None of the four had any code a month after it was specified
(rows added 2026-08-19), and the build order below already recommended against three of them as
framed. **Retiring the guard does not retire the lesson.** The evidence each row cites is still
valid; the last column says where the lesson lives now.

| id | rule it would have enforced | why retired | evidence (unchanged) | where the lesson lives now |
|---|---|---|---|---|
| **G4** | Coverage canary present on the PoC cited by any `REFUTED` row | no agreed spelling for a canary, so a check would be a grep for nothing in particular | REF-12 `[validated-live]` — an oscillator "refuted" against a structurally-immune victim | partly `SKILL.md` prose: the general coverage-canary rule (Phases 2–3). REF-12's specific point, that a refutation must show its *victim* reached the vulnerable state, is not written there; it is in backlog REF-12 and REF-13 only |
| **G6** | Supply feasibility on every `CONFIRMED` row — each `deal()` ≤ on-chain free float | needs live chain data when the PoC runs; a `PreToolUse` hook cannot judge a `deal()` amount | REF-14 `[validated-live]` — caught a fabricated +$16k using **5× the entire token supply** | **backlog REF-14 only** (`LOGGED`). Nothing in `SKILL.md` checks `deal()` against free float; the `deal()` line in Phase 3's opposite-tail pass checks a different thing (proceeds counted, cost never debited). The intended home, not yet built, is a Foundry helper or template assertion |
| **G7** | Composition pass run before concluding (`Stop` hook) | omission class: a marker the model writes itself would satisfy it | REF-15 prio 1; engagement 10's largest miss (0.518 ETH, 46% of forgone value) was one finding split across two rows | `STATUS.md` conversion priority (1), currently blocked on data; backlog REF-15, REF-11 |
| **G9** | Doc-concession sweep run in the repo's own languages | omission class, as G7 | REF-16 — an English-only grep missed a French NatSpec that most strengthened a submission | backlog REF-16 only (`LOGGED`, no `SKILL.md` text) |

**G10 is distinct from G4 and G6, which also touch these rows.** G4 asks whether a `REFUTED`
row's cited PoC had a coverage canary — it presumes a PoC is cited. G6 asks whether a `CONFIRMED`
row's PoC used a physically possible amount — it also presumes one exists. **G10 is the prior
question nobody is asking: is there a PoC at all?** Deferred to after PR #24 by decision, not
oversight.

## Build order for the remaining guards (measured 2026-08-20)

**Do not build G10 first — the evidence resolver has to be fixed before any guard that reads a cited
artifact.** Measured across all 16 rows at `CONFIRMED` or `REFUTED` on disk:

| | count |
|---|---|
| resolve under the **current** rule (`<engagement>/<literal token>`) | **1 / 16** |
| resolve if the resolver **searches by basename** inside the engagement | **4 / 16** |
| name no artifact at all — historical argument-kills | **9 / 16** |
| say *"same file"* — a back-reference to the previous row, no filename | 2 |

Three of `engagement 6`'s five `CONFIRMED` rows cite a **real, existing PoC** —
`PoC_H01_FeeBypass.t.sol`, `PoC_L2_SyncOvercount.t.sol`, `PoC_H08_LoopGas.t.sol` — and every one would
be **wrongly blocked** by G10 as specified, because they cite a bare basename and the files live in
`test/`, not at the engagement root. A gate that fires on three of five correctly-evidenced rows is the
noisy-gate failure this register keeps warning about.

**So the order is:**

1. ✅ **DONE (PR #26).** **Fix the evidence resolver** (`check_g2`'s artifact lookup). Resolve a cited token by (a) the literal
   path, then (b) a basename search inside the engagement reusing `engagement_ledgers()`' prune list.
   Decide what to do with *"same file"* back-references — most likely require an explicit path and let
   G2 say so. **This improves G2 today** and is a prerequisite for both guards below.
2. ✅ **DONE (PR #26).** **G10** — `CONFIRMED` must cite an artifact that resolves. Building it
   surfaced a second false-positive source the measurement above had not predicted: requiring the
   `EVIDENCE:` key would have blocked three more properly-evidenced rows that carry the artifact in a
   plain evidence column. The check reads content, not form.
3. **G8 — NEXT, but not as written. It is aimed at the wrong phase and would have caught nothing.**
   Scoring engagement 2 on 2026-09-08 found four instances of the failure G8 exists to prevent, and
   **G8 catches 0 of 4**: M-3 sat in an `UNTESTED` row, M-8 and M-9 never became rows at all, and
   M-1's row captured only the overflow lead. None was ever `REFUTED`. All four died in **Phase 1**,
   inside `hunters/*.md`, in a paragraph ending "verified safe" — and a clearance is not a kill, so
   nothing in the ledger could see it. `bench/w6-conversion-result.md`.

   **So G8 splits in two, and the Phase-1 half comes first:**
   - **Phase 1 (new, and additive).** A hunter that clears a quantity in one direction emits an
     `UNTESTED` row for the other. This is not a gate — it widens row creation, which `CLAUDE.md`
     requires — and it lives in `conduct.py`'s `OUTPUT_CONTRACT`, the one artifact the conductor
     actually imports. Under test now: `bench/PREREG-clearance-rows.md`, treatment arm
     `bench/contract-clearance-clause.md`, run via `--contract-extra`. **Do not build the hook
     until that reports**; if the clause buys no recall it must be deleted rather than reworded.
   - **Phase 3 (G8 as written).** Still worth having for kills, but it is the *second* half now, not
     the first, and its evidence base no longer supports "next to build" on its own.
4. ~~**G4** — coverage canary present in the PoC cited by a `REFUTED` row. Needs step 1 *and* a written
   convention for what a canary looks like, otherwise it is a grep for a thing with no agreed spelling.~~
   **Retired 2026-09-24** — the convention was never written (§"Retired 2026-09-24").

**Recommended NOT to build as currently framed** — G6, G7 and G9 **retired 2026-09-24** on these
reasons; G5 stays deferred:

- **G6** (supply feasibility, each `deal()` ≤ on-chain free float) — this needs live chain data at the
  moment the PoC runs. It is a **Foundry helper or template assertion**, not a ledger hook; a
  `PreToolUse` guard cannot see a `deal()` amount's plausibility. Reframe it before building it.
- **G7** (composition pass run) and **G9** (doc-concession sweep) — both are omission-class, and both
  would be satisfied by a marker the model writes itself. That checks that a **claim was made**, not
  that the work happened, which is weaker than it looks. Worth doing only as prompt hooks with the
  verdict model-made and visible.
- **G5** (confidentiality egress) — unchanged: deliberately deferred, highest false-positive risk of
  the set.

**The standing rule this episode illustrates:** before building any guard, run it in read-only mode over
every ledger on disk and count what it would fire on. Every guard in this register that turned out to be
wrong was wrong about *real data*, not about its own logic.

---

## Deliberately left as prose

Archetype detection, hunt-wide guidance, severity calls, composition *reasoning* (as opposed to whether
the pass ran), and the Phase −1 EV model. None are state-decidable; gating them would be theatre.

---

## Implementation

| file | what |
|---|---|
| `tooling/guards/extract_prior_art.py` | verbatim section extractor (handles the `\f` heading prefix and the duplicate Appendix-1 heading, both of which silently defeat a naive grep) |
| `tooling/guards/ledger_guard.py` | G1–G3; reads PreToolUse JSON on stdin, exit 0 silent / exit 2 blocks |
| `tooling/guards/test_ledger_guard.py` | 31 tests, including the engagement 3 regression, a noise-control case, and the hook-wiring regression below |
| `skill/SKILL.md` frontmatter | the wiring: `PreToolUse` on `Write\|Edit` → the command that runs the guard |

**Validated against the real failure.** Replaying engagement 3's actual EX-3 promotion
(`UNTESTED` → `CONFIRMED`, the real row text) through the hook interface:

- with no `DEDUP:` block → blocked, exit 2.
- with a sidecar declaring `NO-MATCH` (the realistic bad case — going through the motions) →
  blocked, exit 2, citing **7 identifiers co-occurring in `EX-potential-risks.txt`**, which is the
  exact section the triager quoted to close the submission.
- with a sidecar declaring `MATCH` and a **paraphrased** quote → blocked, exit 2.
- with a sidecar declaring `MATCH` and the **real 4-line wrapped passage** → passes, exit 0. This is
  the outcome we should have reached: the dup identified before any PoC spend.

**The wiring is part of the guard, and it failed silently once.** The frontmatter originally invoked
the script as `${CLAUDE_SKILL_DIR}/../tooling/guards/ledger_guard.py`. Claude Code substitutes that
variable into SKILL.md **content**, not into a hook **command**, so it expanded to empty and the script
was never executed. The hook still fired and every `Write`/`Edit` still failed — on a file-not-found,
not on a verdict. **Blocked-by-crash reads exactly like enforcement and is not**: no guard ran, the
message named no rule, and the blast radius was every file write in the session, which is precisely how
a gate gets disabled. Two consequences, both now pinned by tests in `TestHookWiring`:

- The command resolves via `$HOME/audit-toolkit/...`, not a skill-relative variable. `$CLAUDE_PROJECT_DIR`
  is the documented hook variable but resolves to wherever the session started — during a real run that is
  usually `~/engagements/<target>`, which would reintroduce the same failure.
- A missing script **fails closed and says so**, naming itself as misconfigured rather than surfacing a
  bare interpreter error.

**Caveat, unguarded by design so far.** `engagement_root()` anchors on a `00-triage/` directory. An
engagement folder without one gets **no guard at all**, silently — `evaluate()` returns no errors rather
than complaining that it could not find the root.

### Row id grammar (and why it was a silent hole)

Every guard here operates on parsed ledger rows, so **an id style the parser does not
recognise disables all of them at once — silently.** Until 2026-08-20 `ROW_RE` required a
hyphen (`H-01`, `AB-1`) and rejected the hyphenless style that this repo's own
`templates/ledger.template.md` emits (`H1`). A fresh engagement started from the template
therefore parsed **zero rows and was completely unguarded**, with no error to notice.

Measured across every ledger on disk, counting only rows that carry a status token — the
rows a guard can actually act on: **70 before the fix, 92 after.** Of the 22 gained, **20 are
the the worked example worked example** (corpus, not a live engagement) and **1 is `engagement 6`'s
`H-01b`** split row. **On live engagement ledgers the recovery is one row.** The decisive gain
is the template itself, 0 → 1, which is what makes every *future* engagement guardable.

**Correction (2026-08-20).** An earlier version of this section claimed the fix "recovered
`H1..H8` on `engagement 8` (1 → 9)". That was wrong: those eight rows are the **hunter
roster** table (`| hunter | frame | rows |`), not hypotheses, and none carries a status. The
raw parsed-row count did rise 79 → 109, but counting raw rows overstated the result by
including a table that is not a ledger. Recorded here rather than quietly edited, per the
repo's own rule that an inferred number is a hypothesis until measured.

**Residual this exposed, not yet fixed.** `engagement 8` (9 parsed rows) and `engagement 5` (5)
have **zero rows carrying a status token**, so `evaluate()` skips every one of them — both
ledgers remain effectively unguarded. A row without a status is invisible to every transition
check. Fixing it means either requiring a status to count as a row (which would interact with
G0b) or converting those two ledgers. Logged, not built.

Accepted: an optional-hyphen id in the row's **first cell**, with at least one digit —
`H1`, `H12`, `H-01`, `H-01b`, `AB-1`, `**HT-80**`. The digit requirement is what keeps
header cells (`id`, `ID`, `File`, `status`, `contract`) from parsing as rows; the first-cell
anchor stops ids buried in prose from matching (an unanchored search found a spurious
`H8-04` on `engagement 8`). Pinned by `TestRowParsing`.

**Still unparsed, and deliberately not fixed here.** `engagement 9` and
`engagement 7` use a table whose first column is not an id at all
(`contract`, `subsystem`). Those ledgers get no guard, silently — the same shape of hole,
one layer up. Widening the parser to cover them risks matching arbitrary tables, so the
fix is a **format convention plus a detector** ("this file looks like a ledger but no rows
parsed"), not a looser regex. Logged, not built.

**Design note on the identifier cross-check.** First implementation fired on any single shared
identifier and matched `checkController` — a function in every report on this codebase. That would have
been noise, and noisy gates get disabled. It now requires **≥2 co-occurring identifiers in one section**,
filters to code-shaped tokens (camelCase / snake_case / dotted, so `control` and `policy` no longer
match), and reports the **strongest** section rather than the first. A unit test pins the noise case:
one shared identifier must stay silent.
