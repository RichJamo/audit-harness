# Solana exploit-PoC harness templates

The Solana analog of `templates/*.t.sol` — the **PoC-is-the-spine** artifacts for Solana/Anchor targets. A real
bug can be demonstrated by driving the attacker instruction to a quantified assertion; a false positive cannot.
No PoC ⇒ no submission (repo rule, unchanged by the port).

Solana's static/symbolic backstop is thin (no Slither/Halmos equivalent — see `docs/solana-notes.md §4`), so
these harnesses carry *more* of the recall weight than their Foundry counterparts do on EVM. Treat the checklist
(`bench/solana-coverage-checklist.md`) as the systematic net and each of these PoCs as the proof.

## Files

| File | VM | Use it when |
|---|---|---|
| `litesvm_poc.rs.template` | LiteSVM (Rust, in-process) | Rust-native PoC; tightest loop; you have the Rust chain |
| `litesvm_poc.ts.template` | LiteSVM / bankrun (TS, in-process) | Anchor target with TS tests; JS chain already installed |

Both: load the target `.so`, set up accounts/PDAs/mints/token-accounts, send the **attacker instruction**, and end
on a **quantified assertion** + a **coverage canary**. Same shape as the Foundry "focused test → assertion."

## Pick a VM (fast → slow)

1. **LiteSVM** (Rust or TS) — in-process, milliseconds, no validator. **Default.** Write the PoC here first.
2. **bankrun** (`solana-bankrun` / `anchor-bankrun`, TS) — in-process, Anchor-friendly; swap-in shown at the bottom
   of the TS template. Reach for it to reuse an Anchor project's existing TS suite.
3. **solana-program-test / BanksClient** (Rust) — in-process but heavier, closer to full-runtime semantics. Use
   when LiteSVM's lighter runtime diverges from the behavior you must prove.
4. **`anchor test` / `solana-test-validator`** (local validator) — slowest; real RPC, multiple programs. Only for
   genuine multi-program / full-RPC integration repro the in-process VMs can't model.

**Escalate only on a runtime-semantics wall, and record why in the ledger row.** Most theft/lock PoCs never leave
LiteSVM.

## The coverage canary (mandatory — and load-bearing here)

On EVM a symbolic prover can sometimes tell you a state is unreachable. On Solana it can't. So the **only**
trustworthy "invariant held / REFUTED" is one where a PoC provably *reached* the attack state and the invariant
still held. Every template therefore asserts the attack state was reached before trusting any held/REFUTED result:

- The attacker tx **must succeed** (or fail exactly where the exploit predicts) — a tx that reverted before the
  vulnerable instruction ran proves nothing. The templates raise a loud error instead of silently passing.
- Prefer asserting a **program log emitted only inside the vulnerable branch**, or a concrete post-state read
  (attacker balance up / vault down), over a counter the harness itself wrote.
- A green PoC that never drove the vulnerable instruction is a lie — exactly the EVM rule, ported.

For a multi-instruction / multi-tx attack chain (deposit → warp → settle → attacker-withdraw), hand-drive the
exact sequence deterministically and assert the deep state was reached, mirroring
`templates/DeterministicReach.t.sol.template` (T7). Don't rely on a happy-path setup accidentally reaching it.

## Obtaining the `.so` and matching pins

See `docs/solana-notes.md` §2–§3. In short: `avm use <target's anchor version>` → `anchor build` (Anchor) or
`cargo build-sbf` (raw) → `target/deploy/<program>.so`; load it at the **program id it was built for** (PDAs derive
from that id). Verify `overflow-checks = true` in the profile that actually compiles the on-chain program before
assuming arithmetic panics on overflow — don't inherit that assumption.

## Time / slots

For time-dependent bugs (oracle staleness, vesting, cooldowns) advance the clock in-process rather than sleeping:
LiteSVM exposes clock/sysvar setters (`set_sysvar` / `warp_to_slot`-style calls — check your pinned version's API);
bankrun exposes `context.warpToSlot(...)` / clock manipulation. Drive the clock to the exact edge the bug needs.
