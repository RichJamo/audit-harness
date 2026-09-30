#!/usr/bin/env bash
# Install (or repair) the global Claude Code hooks this toolkit owns.
#
# Why this exists. PreToolUse and Stop are declared in skill/SKILL.md, so they are
# version-controlled and travel with the skill. SessionStart cannot be: a skill loads
# mid-session, so a SessionStart hook declared there would never fire. It has to live in
# ~/.claude/settings.json, which is not a git repo and is backed up by nothing.
#
# That matters more than it sounds. The SessionStart hook's job is to stay SILENT unless
# something is wrong -- so "quiet because all is well" and "quiet because it no longer
# exists" look identical. An absent guard reading exactly like a satisfied one is the
# failure this whole register exists to remove.
#
# So: config/claude-settings-hooks.json is the written-down record, and this merges it in.
#
#   tooling/install-hooks.sh            install or repair
#   tooling/install-hooks.sh --check    report drift, change nothing (exit 1 if drifted)
#
# MERGES, never overwrites: your permissions, theme and everything else are left alone.
# Only the hook events named in the reference file are touched. Idempotent.
set -euo pipefail

TOOLKIT="$(cd "$(dirname "$0")/.." && pwd)"
REF="$TOOLKIT/config/claude-settings-hooks.json"
LIVE="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
MODE="${1:-install}"

[ -f "$REF" ] || { echo "error: reference file missing: $REF" >&2; exit 1; }

python3 - "$REF" "$LIVE" "$MODE" <<'PY'
import json, shutil, sys, time
from pathlib import Path

ref_p, live_p, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
ref = json.loads(ref_p.read_text())
want = ref.get("hooks", {})

if live_p.exists():
    try:
        live = json.loads(live_p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"error: {live_p} is not valid JSON ({e}). Fix it by hand; refusing to overwrite.")
else:
    live = {}

have = live.get("hooks", {})
drift = {k: v for k, v in want.items() if have.get(k) != v}

if mode == "--check":
    if not drift:
        print(f"ok: {live_p} matches the reference for: {', '.join(want) or '(nothing)'}")
        raise SystemExit(0)
    print(f"DRIFT: {live_p} does not match {ref_p.name}", file=sys.stderr)
    for k in drift:
        state = "MISSING" if k not in have else "differs"
        print(f"  {k}: {state}", file=sys.stderr)
    print("  run tooling/install-hooks.sh to repair", file=sys.stderr)
    raise SystemExit(1)

if not drift:
    print(f"ok: nothing to do — {live_p} already matches for: {', '.join(want)}")
    raise SystemExit(0)

if live_p.exists():
    # Timestamped, so repeated runs never clobber the one backup that mattered.
    bak = live_p.with_suffix(f".json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(live_p, bak)
    print(f"backed up  {bak.name}")

live.setdefault("hooks", {})
for k, v in drift.items():
    print(f"{'added' if k not in have else 'updated'}      hooks.{k}")
    live["hooks"][k] = v

live_p.parent.mkdir(parents=True, exist_ok=True)
live_p.write_text(json.dumps(live, indent=2) + "\n")
json.loads(live_p.read_text())          # prove we did not write something unparseable
kept = [k for k in live if k != "hooks"]
print(f"wrote      {live_p}")
print(f"untouched  {', '.join(kept) if kept else '(no other keys)'}")
PY
