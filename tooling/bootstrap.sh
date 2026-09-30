#!/usr/bin/env bash
# Install the static-analysis baseline for an audit. Idempotent-ish; safe to re-run.
# Usage: bash tooling/bootstrap.sh
set -euo pipefail

echo "== Slither (pip) =="
if ! command -v slither >/dev/null 2>&1 && ! [ -x "$HOME/Library/Python/3.9/bin/slither" ]; then
  pip3 install --user slither-analyzer
fi
echo "slither: $(command -v slither || echo "$HOME/Library/Python/3.9/bin/slither (add to PATH)")"

echo "== Aderyn (Cyfrin) =="
if ! command -v aderyn >/dev/null 2>&1 && ! [ -x "$HOME/.cargo/bin/aderyn" ]; then
  # Prefer cargo if available; the curl|bash installer is often blocked by sandboxes.
  if command -v cargo >/dev/null 2>&1; then
    cargo install aderyn
  else
    echo "Install cargo (rustup) then 'cargo install aderyn', or 'brew install cyfrin/tap/aderyn'"
    echo "(brew formula may need Xcode Command Line Tools to build)."
  fi
fi
echo "aderyn: $(command -v aderyn || echo "$HOME/.cargo/bin/aderyn (add to PATH)")"

echo "== solc-select (standalone compiler, for Slither's --solc fallback) =="
# REF-19: crytic-compile's foundry/hardhat build-info reader tracks a moving forge artifact
# format and breaks silently (KeyError: 'output') on current forge versions -- Slither then
# has NO path to a compiler at all, because forge embeds its own and nothing here installed
# a standalone one. Half the static baseline was missing on engagement 14 and Aderyn alone still
# looked like a complete scan. solc-select gives Slither a --solc that does not depend on
# crytic-compile keeping up with forge's artifact format.
SOLC_VERSION="0.8.26"   # bump when a newer stable release lands; a target on an older/newer
                        # pragma may also need `solc-select install <that version>` by hand.
# `python3 -m site --user-base` (not a hardcoded .../Python/3.9/bin) so this does not
# silently no-op on a machine whose `pip3 --user` targets a different Python minor version
# -- exactly the kind of half-installed, no-error baseline REF-19 itself is about.
USER_BIN="$(python3 -m site --user-base 2>/dev/null)/bin"
if ! command -v solc-select >/dev/null 2>&1 && ! [ -x "$USER_BIN/solc-select" ]; then
  pip3 install --user solc-select
fi
SOLC_SELECT="$(command -v solc-select || echo "$USER_BIN/solc-select")"
if [ -x "$SOLC_SELECT" ] || command -v solc-select >/dev/null 2>&1; then
  "$SOLC_SELECT" install "$SOLC_VERSION"
  "$SOLC_SELECT" use "$SOLC_VERSION"
else
  echo "WARNING: solc-select not found after install (checked PATH and $USER_BIN);" >&2
  echo "Slither will have no --solc fallback until it is on PATH." >&2
fi
echo "solc: $(command -v solc || echo "not on PATH -- add solc-select's shim, see its own install output")"

cat <<'NOTE'

PATH hints (zsh):
  export PATH="$HOME/Library/Python/3.9/bin:$HOME/.cargo/bin:$PATH"

If Slither dies with "Type not found contract Mock..." the repo embeds test contracts inside
src/*.sol files. Use tooling/slither-prod-mirror.sh to build a production-only mirror first.
NOTE

# --- methodology guards (docs/guard-register.md) -----------------------------
# G1 parses per-row dedup sidecars as YAML. The guard fails CLOSED without this,
# so a missing dependency blocks promotions rather than silently passing them.
echo "==> python deps for tooling/guards"
python3 -m pip install --quiet --disable-pip-version-check pyyaml || \
  echo "WARNING: pyyaml install failed; ledger_guard G1 will block until it is present"

# --- lint, at the version CI pins --------------------------------------------
# CI runs `ruff check tooling` (.github/workflows/tests.yml) and a red lint blocks
# the build, so a dev environment that cannot run it finds out on the PR instead of before
# it. The version is PINNED to CI's: a newer ruff can report findings CI does not, which
# trains people to ignore it. Ruleset and the reason it is narrow: ruff.toml.
echo "==> ruff (pinned to CI's version)"
python3 -m pip install --quiet --disable-pip-version-check 'ruff==0.16.7' || \
  echo "WARNING: ruff install failed; 'ruff check tooling' will not run locally"
