# Privileged actors — <TARGET> @ <COMMIT>

Copy to `<engagement>/01-scope/privileged-actors.md` and fill it in from THIS target's code.
G18 reads it (`tooling/privileged_actors.py`) to find the ledger rows that name a privileged
action, so that each one is judged by the privileged-action test instead of being set aside
because "an admin acts first" (REF-33, `docs/guard-register.md`).

## How to fill it in (from the code, not from memory of other protocols)

1. Find the role definitions: the role constants or enum, the access-control base the
   contracts inherit (an `AccessControl`, `AccessManager`, `Ownable`, a hand-rolled
   `onlyX` modifier), and any role-description NatSpec.
2. Find the role wiring: the code that grants each role a function selector or a modifier
   (an `initialize`, a registry, a deploy script in scope, a `setTargetFunctionRole` loop).
   A role with no wired function is still listed, with "none wired" in the functions cell.
3. For each role, list every external function it alone can call, by its exact name in the
   code. Cite `file:line` for the role's definition and for where each function is gated.
4. Put a party in **Semi-trusted parties** when the scope documents (scope exclusions, the
   README's trust model, the contest page) trust it only partly: a market owner, a curator,
   a whitelisted creator, an operator chosen by users. Use the scope documents' own words
   for who counts, and cite them.
5. Write role names exactly as the code and documents spell them. The screen matches role
   names as whole words, ignoring case, and function names as exact identifiers. Do not add
   generic words such as "role", "owner" or "user" as a role name unless the code really
   has a role of that name: they match far more rows than they mean (on engagement 22, 26 of the 45
   rows the screen judged NO-ACTION had matched only on the word "role"). A role name may be a
   phrase ("vault owner"), matched as a whole phrase.
6. When a privileged function shares its name with a user-facing one elsewhere (`deposit`,
   `withdraw`, `execute`, `borrow`), qualify it by **the contract that declares it**, e.g.
   `Market.withdraw`. It then selects only rows naming that contract's function. Do not qualify by a
   base contract that declares nothing: no row names it, so the function silently stops selecting.
   On engagement 21, qualifying the operator's functions by their declaring contracts and naming the
   role by its full phrase instead of the bare "operator" cut the rows selected from 305 to about
   226 of 896 open rows.

Rows whose first cell starts with `<` are placeholders and are ignored.

## Trusted roles

| role | privileged functions | source (file:line) |
|---|---|---|
| <ROLE_NAME> | `<functionName>`, `<otherFunction>` | <path/Roles.sol:12>; gated at <path/Vault.sol:88> |

## Semi-trusted parties

| party | privileged functions | source (file:line) |
|---|---|---|
| <PARTY_NAME> | `<functionName>` | <scope-exclusions.md:40> |
