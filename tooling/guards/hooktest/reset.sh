#!/usr/bin/env bash
# Rebuild the live hook-test fixtures. Run before re-running the suite.
# Fixtures are built with shell redirection ON PURPOSE: Write/Edit would be blocked
# by the very guards under test (and case 18 is that bypass, recorded as a finding).
set -e
H="$(cd "$(dirname "$0")" && pwd)"
# Fixtures are built OUTSIDE the toolkit repo on purpose. ledger_guard exempts every
# path under audit-toolkit/ (docs/, templates/ and examples/ hold ledger-shaped
# documentation that must not be gated) -- so fixtures kept beside this script would be
# exempt too, and every case would ALLOW and "pass" without a guard ever running.
# Override with HOOKTEST_CASES to build them somewhere else; never inside the repo.
CASES="${HOOKTEST_CASES:-${TMPDIR:-/tmp}/audit-toolkit-hooktest/cases}"
rm -rf "$CASES"; mkdir -p "$CASES"

hdr() { printf '# %s\n\n| id | hypothesis | status |\n|---|---|---|\n' "$1"; }
corpus() {
  mkdir -p "$CASES/$1/00-triage/prior-audits" "$CASES/$1/00-triage/potential-risks"
  echo "Zellic audit of VaultCore, 2026-03. Findings: 4 Low, 1 Informational." \
    > "$CASES/$1/00-triage/prior-audits/zellic-2026-03.txt"
  cat > "$CASES/$1/00-triage/potential-risks/PR-risks.txt" <<'PR'
Appendix 1 - Potential Risks

R-3. Fee accrual truncation on partial exits. The vault's accrueFees helper computes
the management fee as feeBps * assets / 10_000 and truncates the remainder. Because
partialWithdraw calls accrueFees before it debits the share balance, a depositor who
withdraws in many small increments pays strictly less fee than one who exits in a
single transaction. We consider the residue immaterial at current TVL and accept it.
PR
}

mkdir -p "$CASES/01-g1-waypoint/00-triage" "$CASES/01-g1-waypoint/ledger"
{ hdr "01 - G1 waypoint"; echo '| **HT-1** | fee accrual rounds down on every partial withdrawal | `UNTESTED` |'; } > "$CASES/01-g1-waypoint/ledger/ledger.md"

mkdir -p "$CASES/02-g1-no-corpus/00-triage" "$CASES/02-g1-no-corpus/ledger"
{ hdr "02 - G1 no corpus"; echo '| **HT-2** | share price manipulable by first depositor | `UNTESTED` |'; } > "$CASES/02-g1-no-corpus/ledger/ledger.md"

corpus 03-g1-no-dedup; mkdir -p "$CASES/03-g1-no-dedup/ledger"
{ hdr "03 - G1 no DEDUP pointer"; echo '| **HT-3** | withdrawal queue can be starved by dust requests | `UNTESTED` |'; } > "$CASES/03-g1-no-dedup/ledger/ledger.md"

corpus 04-g1-nomatch-idents; mkdir -p "$CASES/04-g1-nomatch-idents/ledger/dedup"
{ hdr "04 - G1 identifier cross-check"; echo '| **HT-4** | `accrueFees` truncates before `partialWithdraw` debits shares | `UNTESTED` DEDUP: ledger/dedup/HT-4.md |'; } > "$CASES/04-g1-nomatch-idents/ledger/ledger.md"
cat > "$CASES/04-g1-nomatch-idents/ledger/dedup/HT-4.md" <<'Y1'
searched:
  - 00-triage/potential-risks/PR-risks.txt
terms: [accrueFees, partialWithdraw, truncation]
result: NO-MATCH
Y1

corpus 05-g1-paraphrase; mkdir -p "$CASES/05-g1-paraphrase/ledger/dedup"
{ hdr "05 - G1 paraphrase quote"; echo '| **HT-5** | fee truncation favours incremental exits | `UNTESTED` DEDUP: ledger/dedup/HT-5.md |'; } > "$CASES/05-g1-paraphrase/ledger/ledger.md"
cat > "$CASES/05-g1-paraphrase/ledger/dedup/HT-5.md" <<'Y2'
searched:
  - 00-triage/potential-risks/PR-risks.txt
terms: [accrueFees, fee truncation, incremental exit]
result: MATCH
quote: |
  a user who exits in several small steps ends up paying a smaller fee than one who
  exits all at once
Y2

corpus 06-g1-pass; mkdir -p "$CASES/06-g1-pass/ledger/dedup"
{ hdr "06 - G1 verbatim quote"; echo '| **HT-6** | fee truncation favours incremental exits | `UNTESTED` DEDUP: ledger/dedup/HT-6.md |'; } > "$CASES/06-g1-pass/ledger/ledger.md"
cat > "$CASES/06-g1-pass/ledger/dedup/HT-6.md" <<'Y3'
searched:
  - 00-triage/potential-risks/PR-risks.txt
terms: [accrueFees, fee truncation, incremental exit]
result: MATCH
quote: |
  a depositor who
  withdraws in many small increments pays strictly less fee than one who exits in a
  single transaction
Y3

mkdir -p "$CASES/07-g1b-no-tier1/00-triage" "$CASES/07-g1b-no-tier1/ledger" "$CASES/07-g1b-no-tier1/poc"
{ hdr "07 - G1b no TIER-1 row"; echo '| **HT-7** | fee accrual rounds down | `UNTESTED` |'; } > "$CASES/07-g1b-no-tier1/ledger/ledger.md"

mkdir -p "$CASES/08-g1b-pass/00-triage" "$CASES/08-g1b-pass/ledger" "$CASES/08-g1b-pass/poc"
{ hdr "08 - G1b TIER-1 present"; echo '| **HT-8** | fee accrual rounds down | `TIER-1` DEDUP: ledger/dedup/HT-8.md |'; } > "$CASES/08-g1b-pass/ledger/ledger.md"

mkdir -p "$CASES/09-g2-refuted-prose/00-triage" "$CASES/09-g2-refuted-prose/ledger"
{ hdr "09 - G2 prose kill"; echo '| **HT-9** | rounding residue is claimable by a third party | `TIER-1` |'; } > "$CASES/09-g2-refuted-prose/ledger/ledger.md"

mkdir -p "$CASES/10-g2-evidence-missing/00-triage" "$CASES/10-g2-evidence-missing/ledger"
{ hdr "10 - G2 dangling evidence"; echo '| **HT-10** | rounding residue is claimable by a third party | `TIER-1` |'; } > "$CASES/10-g2-evidence-missing/ledger/ledger.md"

mkdir -p "$CASES/11-g2-refuted-pass/00-triage" "$CASES/11-g2-refuted-pass/ledger" "$CASES/11-g2-refuted-pass/poc"
{ hdr "11 - G2 real evidence"; echo '| **HT-11** | rounding residue is claimable by a third party | `TIER-1` |'; } > "$CASES/11-g2-refuted-pass/ledger/ledger.md"
printf '// exploit-should-work test\ncontract FeeRoundingTest { function test_residueNotClaimable() public {} }\n' > "$CASES/11-g2-refuted-pass/poc/FeeRounding.t.sol"

mkdir -p "$CASES/12-g2-scopeheld-nohuman/00-triage" "$CASES/12-g2-scopeheld-nohuman/ledger"
{ hdr "12 - G2 scope-held, model decided"; echo '| **HT-12** | admin can brick the withdrawal queue | `UNTESTED` |'; } > "$CASES/12-g2-scopeheld-nohuman/ledger/ledger.md"

mkdir -p "$CASES/13-g2-scopeheld-pass/00-triage" "$CASES/13-g2-scopeheld-pass/ledger"
{ hdr "13 - G2 scope-held, human decided"; echo '| **HT-13** | admin can brick the withdrawal queue | `UNTESTED` |'; } > "$CASES/13-g2-scopeheld-pass/ledger/ledger.md"

mkdir -p "$CASES/14-g3-delete/00-triage" "$CASES/14-g3-delete/ledger"
{ hdr "14 - G3 row deletion"; echo '| **HT-40** | share price manipulable by first depositor | `UNTESTED` |'; echo '| **HT-41** | withdrawal queue starvation via dust | `UNTESTED` |'; } > "$CASES/14-g3-delete/ledger/ledger.md"

mkdir -p "$CASES/15-g3-merged/00-triage" "$CASES/15-g3-merged/ledger"
{ hdr "15 - G3 merged rows"; echo '| **HT-50** | fee truncation on partial exit | `UNTESTED` |'; echo '| **HT-51** | fee truncation on full exit (same mechanism) | `UNTESTED` |'; } > "$CASES/15-g3-merged/ledger/ledger.md"

mkdir -p "$CASES/16-noise-control/00-triage" "$CASES/16-noise-control/ledger"
{ hdr "16 - noise control"; echo '| **HT-60** | placeholder | `UNTESTED` |'; } > "$CASES/16-noise-control/ledger/ledger.md"
printf '# Scratch notes\nNothing here should ever trip a guard.\n' > "$CASES/16-noise-control/notes.md"

mkdir -p "$CASES/17-no-00-triage/ledger"
{ hdr "17 - no 00-triage anywhere up the tree"; echo '| **HT-70** | fee accrual rounds down on every partial withdrawal | `UNTESTED` |'; } > "$CASES/17-no-00-triage/ledger/ledger.md"

mkdir -p "$CASES/18-bash-bypass/00-triage" "$CASES/18-bash-bypass/ledger"
{ hdr "18 - Bash bypass"; echo '| **HT-80** | fee accrual rounds down on every partial withdrawal | `UNTESTED` |'; } > "$CASES/18-bash-bypass/ledger/ledger.md"

mkdir -p "$CASES/22-g0b-nontable/00-triage" "$CASES/22-g0b-nontable/ledger"
{ printf '# 22 - non-table ledger (engagement 9 / engagement 7 shape)\n\n## REFUTED\n'; \
  printf '### R-1 - cancelExpiredOrders front-runs settlement\nRefuted on every arm read.\n\n'; \
  printf '### R-2 - grace-period fix is incomplete\nRefuted by inspection.\n'; } > "$CASES/22-g0b-nontable/ledger/ledger.md"

echo "fixtures reset in $CASES: $(ls -d "$CASES"/*/ | wc -l | tr -d ' ') cases"
