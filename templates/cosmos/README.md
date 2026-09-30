# Cosmos-SDK / L1 exploit-PoC harness templates

The L1 analog of `templates/*.t.sol` (EVM) and `templates/solana/` (SVM) — the **PoC-is-the-spine** artifacts for a
Cosmos-SDK app-chain (+ its go-ethereum fork). A real L1 bug can be demonstrated by driving the exact path to a
quantified assertion; a false positive cannot. No PoC ⇒ no submission (repo rule, unchanged by the port).

The L1 static/symbolic backstop for the money classes (nondeterminism, consensus-halt, invariant breaks) is
**near-nil** (no Slither/Halmos equivalent, and no linter catches map-iteration nondeterminism — see
`docs/cosmos-notes.md §4`). So these harnesses carry **more** of the recall weight than their Foundry counterparts do
on EVM. Treat the checklist (`bench/cosmos-coverage-checklist.md`) as the systematic net and each of these PoCs as the
proof.

> **Validation status (2026-07-24): `keeper_test.go.template` is validated end-to-end** — a tracer-bullet reproduced a
> real awarded Cosmos keeper bug (engagement 13 H-01, ERC20 `BurnCoins` per-coin over-move) in a compiling, running `go test`
> that PASSES on the buggy code and FAILS on the one-line-fixed code (assertion confirmed discriminating, then
> reverted). The "SETUP REALITY" notes at the top of that template (in-package fixtures, mocked collaborators, building
> preconditions via the module's own tx/EVM helpers, amplifying loop bugs with ≥2 items) are the concrete learnings
> from that run. The `app_determinism_test` (halt/nondeterminism) and `localnet_repro` paths are NOT yet
> tracer-validated — do that before leaning on them.

## Files — pick by what you must prove

| File | What it proves | Use it when |
|---|---|---|
| `keeper_test.go.template` | a msg-handler / keeper bug: theft, invariant break, authority bypass, ante gap | the bug lives in a single module's logic — the fast, default loop (analog of a focused Foundry test) |
| `app_determinism_test.go.template` | **nondeterminism → halt** (two runs diverge) OR **BeginBlock/EndBlock panic → halt** | the bug is a consensus-halt / fork class (§1, §4.2, §6) — the highest-value L1 shape |
| `localnet_repro.sh.template` | an end-to-end halt/DoS on a real running node | escalation: the in-process harness can't model it, or you want a validator-observable halt for the report |

**Pick the cheapest that proves it.** Most theft/invariant/authority bugs never leave `keeper_test`. The halt/
nondeterminism classes usually need `app_determinism_test` (in-process, still fast). Escalate to `localnet_repro` only
for a runtime-semantics wall or a validator-observable halt, and record why in the ledger row.

## The coverage canary (mandatory — and load-bearing here)

On EVM a symbolic prover can sometimes tell you a state is unreachable. On an L1 it can't, and for the halt class the
failure is silent until production. So the **only** trustworthy "invariant held / no-halt / REFUTED" is a PoC that
provably *reached* the suspect state and the property still held. Every template asserts the state was reached before
trusting any held/REFUTED result:

- **Theft / invariant PoC (keeper):** the attacker msg **must succeed** (or fail exactly where predicted) and the
  assertion reads a **concrete post-state** (attacker balance up / module account down / a legit user's funds now
  unwithdrawable / a registered invariant now returning `broken=true`) — not a counter the harness itself wrote.
- **Nondeterminism PoC:** the harness must **actually execute the suspect path on BOTH runs** and compare the two real
  AppHashes/state bytes. A test that ran the path once, or compared a value the harness set, proves nothing. Divergence
  = the halt.
- **Halt/panic PoC:** the harness must **actually invoke BeginBlock/EndBlock (or the ante/keeper) and reach the panic**
  — asserted via `require.Panics` around the real call. A `require.Panics(func(){ panic("x") })` that doesn't call the
  target is a lie. Assert the panic originates in the target path (message/stack), not the harness.

A green PoC that never drove the vulnerable path is a lie — exactly the EVM/Solana rule, ported. For a multi-tx attack
chain (plant state → next block panics; or deposit → attest → execute → replay), hand-drive the exact sequence
deterministically and assert the deep state was reached, mirroring `templates/DeterministicReach.t.sol.template` (T7).

## Building the chain-under-test and matching versions

See `docs/cosmos-notes.md §1–§3`. In short: read the target's `go.mod` for the exact `cosmos-sdk` / `cometbft` /
`cosmossdk.io/math` versions (the SDK API differs across v0.47/v0.50/v0.53 — a PoC against the wrong minor may not
compile), `go build ./...` the node and the geth fork, and run the module keeper tests. Diff the geth fork against
upstream before auditing it. Confirm whether the app ships `TestAppStateDeterminism` — if so, run it first
(`make test-sim-nondeterminism`); it's the L1 analog of the ≥500k Foundry fuzz mirror.

## Time / height / block context

Consensus time is `ctx.BlockTime()` and height is `ctx.BlockHeight()` — never host time. To drive a time/height-
dependent bug, advance the context deterministically (`ctx.WithBlockTime(...)`, `ctx.WithBlockHeight(...)`) and, for
multi-block flows, call the module's BeginBlock/EndBlock between heights. Drive the clock/height to the exact edge the
bug needs; do not sleep.
