"""Which folders hold a project's dependencies rather than its own source.

One rule, shared by every tool that walks a source tree: `ask-model.py` (the model's scope),
`fix-adjacency.py` (the source index) and G18's evidence files in `guards/ledger_guard.py`. Hand-written
copies had drifted: two dropped any path with a part named `lib`, which hid first-party code that
projects keep in `src/**/lib/`. A name-based
fix then let `contracts/lib/` dependencies back in (found in review), so the rule reads the project's own
layout instead: a `lib/` is a dependency folder when the folder containing it has a `foundry.toml`.
"""
from __future__ import annotations

from pathlib import Path


def in_dependency_lib(path: Path, root: Path) -> bool:
    """True when `path` sits under a folder named `lib` that holds dependencies, between `root`
    (exclusive) and `path`: a `lib` whose parent folder has a `foundry.toml`.

    Pre: `path` is under `root`. `root` itself is never judged, so a scope pointed at a folder named
    `lib` keeps its files, and folders above `root` (a home folder named `lib`) say nothing.
    Post, on the four real layouts checked in review: engagement 21's `src/<module>/lib/` and
    engagement 19's `contracts/lib/` (no foundry.toml beside them) are first-party, returning False;
    engagement 18's `packages/contracts/lib/` and engagement 24's `contracts/lib/openzeppelin/` (a
    foundry.toml beside the lib) are dependencies, returning True.
    """
    here = root
    for part in path.relative_to(root).parts[:-1]:
        if part.lower() == "lib" and (here / "foundry.toml").is_file():
            return True
        here = here / part
    return False
