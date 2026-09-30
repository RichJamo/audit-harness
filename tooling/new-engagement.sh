#!/usr/bin/env bash
# Scaffold an engagement so the ledger is correctly formatted BY CONSTRUCTION.
#
# Why this exists. Format compliance had three layers and none of them was certain:
#   prose in docs/    - advisory; this repo has measured prose rules being ignored
#   G0b detector      - catches wrong formats we have SEEN (headings, bullets); a novel
#                       shape still parses as zero rows and is still silently exempt
#   G0c declaration   - a new ledger must declare its format; cannot be out-run by a
#                       novel shape, but still relies on someone reacting to a block
# This is the fourth layer and the only one that removes the decision: the ledger is
# copied from the template, so it is right before anyone can get it wrong. The guards
# then catch drift afterwards.
#
# Usage: tooling/new-engagement.sh <name> [parent-dir]
#        parent-dir defaults to ~/engagements
set -euo pipefail

TOOLKIT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-}"
PARENT="${2:-$HOME/engagements}"

if [ -z "$NAME" ]; then
  echo "usage: $(basename "$0") <engagement-name> [parent-dir]" >&2
  exit 1
fi

ROOT="$PARENT/$NAME"
if [ -e "$ROOT" ]; then
  echo "refusing to overwrite an existing path: $ROOT" >&2
  exit 1
fi

# 00-triage/ is not decoration: engagement_root() anchors on it, and without one NO guard
# runs at all, silently (docs/guard-register.md G0).
mkdir -p "$ROOT/00-triage/prior-audits" \
         "$ROOT/00-triage/potential-risks" \
         "$ROOT/00-triage/protocol-docs" \
         "$ROOT/ledger/dedup" \
         "$ROOT/poc" \
         "$ROOT/02-static"
# People and agents reach for "prior-art" (the extractor and the guard docs call it that), and
# on two engagements the reports landed in prior-art/ while G1 reads prior-audits/. A link
# makes both names the same folder, so the mistake has nowhere to put the files.
ln -s prior-audits "$ROOT/00-triage/prior-art"

cp "$TOOLKIT/templates/ledger.template.md" "$ROOT/ledger/ledger.md"

# REF-17: record which version of the skill this engagement ran. Stamped here, never typed by
# the model, and read from the toolkit THIS script lives in -- the runtime every engagement
# resolves by absolute path -- so it names the phase files that were actually in force. Not a
# git checkout => `unknown`; never a guess.
SKILL_COMMIT="$(git -C "$TOOLKIT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

# REF-18: the header skeleton goes in ledger/HEADER.md, NOT in ledger.md. Five engagements
# lost their header because the template carried it and every CLI write redraws ledger.md
# from the event log, so the first `add` deleted it. HEADER.md is the hand-owned file
# render_text() composes back in above the table (REF-23), so it survives every redraw.
# The labels ship with NO values on purpose: header_missing_fields() reports a label with
# nothing after it as absent, so the REF-23 precondition on the first TIER-1 promotion
# still bites. A placeholder would satisfy it vacuously -- which is why RUN, the one line
# this scaffold does write a value into, must also name a `model=` to count as filled.
cat > "$ROOT/ledger/HEADER.md" <<EOF
# Ledger header — fill before the first TIER-1 promotion

Hand-owned. \`render\` composes this file into \`ledger/ledger.md\` above the table, so it is
the one place header text survives a CLI write. What each line should say is in
\`docs/hypothesis-ledger.md\` § "The ledger header". \`not recorded\` is a legal value; a
guessed value is not. \`skill=\` is stamped by this scaffold; the rest is yours to fill.

\`\`\`
TARGET
INTENSITY
IMPACT BAR
MATERIALITY
PRIOR-ART
DEDUP RULE
FEE
RUN         skill=$SKILL_COMMIT · model= · effort= · harness=
CUTOFF
DATES
\`\`\`
EOF

# Drop the template's example row. It is not a real hypothesis and the ledger CLI's event
# log has never heard of it, so the first CLI-triggered redraw (tooling/ledger/cli.py add
# et al. now redraw the board on every write) would silently drop it -- and the NEXT guard
# check would see it gone and fire G3 ("row H1 was present last turn and is gone now") on
# an engagement that never had a real H1 hypothesis at all. The id style it illustrates is
# still documented in the template's own prose above the table.
grep -v '^| H1 ' "$ROOT/ledger/ledger.md" > "$ROOT/ledger/ledger.md.tmp"
mv "$ROOT/ledger/ledger.md.tmp" "$ROOT/ledger/ledger.md"

cat > "$ROOT/00-triage/README.md" <<'EOF'
# 00-triage

Drop every prior-audit artifact here before hunters fan out (skill Phase 1, gate T1):

- `prior-audits/`    — the reports themselves (PDF, md, whatever arrives). `prior-art/` is a
                       link to this same folder, so either name works.
- `potential-risks/` — verbatim extracts, one .txt per section. Produce with
                       `tooling/guards/extract_prior_art.py <engagement>`
- `protocol-docs/`   — what the TARGET's own docs say (REF-20). A primer plus the passages that
                       answer who calls this, how often, how many will exist, is it live. The
                       doctor reports a GAP while this is empty; no guard blocks on it.

Guard G1 blocks any promotion to `TIER-1` until both directories have content, or until
`00-triage/NO-PRIOR-ART.md` asserts there is none. That is deliberate: the dedup obligation
is owed BEFORE the harness hours, not at submission. Engagement 3 lost its only submission by
paying that obligation late.
EOF

echo "scaffolded $ROOT"
printf '  %s\n' \
  "00-triage/prior-audits/    <- save the reports here FIRST (G1 blocks TIER-1 without them; prior-art/ is the same folder)" \
  "00-triage/potential-risks/ <- verbatim extracts (extract_prior_art.py)" \
  "00-triage/protocol-docs/   <- what the TARGET's own docs say (REF-20; doctor reports a GAP while empty)" \
  "ledger/HEADER.md           <- FILL THIS FIRST: impact bar, materiality, RUN/CUTOFF (the first TIER-1 promotion is refused until it is complete)" \
  "ledger/ledger.md           <- from templates/ledger.template.md, format declared; GENERATED once the CLI writes" \
  "ledger/dedup/              <- one DEDUP: sidecar per row entering TIER-1" \
  "poc/                       <- harnesses (G1b blocks these until a row is TIER-1)" \
  "02-static/                 <- Slither / Aderyn / clippy output"

# Prove the scaffold satisfies the guards rather than asserting it.
if command -v python3 >/dev/null 2>&1; then
  python3 - "$TOOLKIT" "$ROOT/ledger/ledger.md" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "tooling/guards"))
from ledger_guard import evaluate
led = Path(sys.argv[2])
errs = evaluate(led, led.read_text())
print("\nguard self-check:", "clean" if not errs else "FAILED")
for e in errs:
    print("  !", e)
raise SystemExit(1 if errs else 0)
PY
fi
