---
name: audit-contest
description: "Runs a competitive smart-contract audit (HackenProof/Code4rena/Sherlock-style) with a recall-optimized, evidence-driven methodology. Use when the user wants to audit a Solidity/EVM, Solana/Anchor (SVM), or Cosmos-SDK/Go L1 (+ go-ethereum fork) repo/contest for rewardable vulnerabilities (theft / permanent fund lock, or L1-shaped impacts: node crash / DoS / can't-finalize / consensus-halt), triage a scope, build a threat model, or stand up invariant fuzzing / an exploit harness. Detects the target VM and binds the right engine set (Foundry vs LiteSVM vs Go keeper/determinism harness) without forking the methodology. Hunts wide (never kills a hypothesis by argument), proves correctness by PoC, and hands SCOPE calls to the human. Pauses at every human-judgment gate; never auto-decides scope or submits."
hooks:
  PreToolUse:
    - matcher: "Write|Edit"
      hooks:
        - type: command
          command: 'G="$HOME/audit-toolkit/tooling/guards/ledger_guard.py"; [ -f "$G" ] || { echo "ledger guard MISCONFIGURED: cannot find $G. Failing closed, so every Write/Edit is blocked until the hook path in SKILL.md frontmatter is fixed. See docs/guard-register.md." >&2; exit 2; }; python3 "$G"'
          timeout: 15
  Stop:
    - hooks:
        - type: command
          command: 'G="$HOME/audit-toolkit/tooling/guards/ledger_state_guard.py"; [ -f "$G" ] || { echo "ledger STATE guard MISCONFIGURED: cannot find $G. Exiting 0 -- a Stop hook that fails closed cannot be routed around and would trap the session. The PreToolUse guard still fails closed. See docs/guard-register.md." >&2; exit 0; }; python3 "$G"'
          timeout: 20
---

# The hunting workflow is not part of this release

This file exists to declare the two hooks above, and nothing else.

In the private toolkit this file holds the audit workflow itself: the phases a hunter works
through, what to generate, where to look and when to stop. That workflow is deliberately left out
of this release, because the value of knowing where to look falls as more people know it.

What is released is the enforcement harness — the ledger command line tool, the two hooks declared
above, the engagement doctor and the scaffold. They hold two rules whatever the model chooses to do:

1. **A hypothesis is killed only by a failed proof-of-concept, or escalated to a human — never by
   an argument in prose.**
2. **Correctness is decided by a proof-of-concept; scope is decided by the human.**

The hooks resolve their scripts under `$HOME/audit-toolkit/`. Clone this repository to that path,
or edit the two `command:` lines in the frontmatter above to wherever you put it. `README.md`
explains the layout and how to install it; `docs/guard-register.md` states each rule, its pass
criterion and the failure that justifies it.
