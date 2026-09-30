"""The event log: the ledger's state, and the only thing that is authoritative.

WHY A LOG AND NOT A TABLE. The markdown ledger was simultaneously the state, the
deliverable and the audit record. That made every guard an interception of a document
edit, and the write paths into a file are an open set: `sed` is not matched by
`Write|Edit`, a non-table ledger parses as zero rows and is silently unguarded, and a
guard that fails open at Stop cannot be the backstop. engagement 4 proved it live -- its
guards never fired because ledger writes went through Bash.

Here the state is an append-only JSONL file and `ledger.md` is a render of it. The
default flips: skipping the machinery produces NO state change rather than an
unguarded one.

See bench/hr-c-executable-ledger-design.md.
"""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path

EVENTS = "ledger/events.jsonl"
RENDER = "ledger/ledger.md"
# A human-owned file the CLI composes into the render but never generates (REF-23): the
# impact bar, materiality basis, scope exclusions and RUN/CUTOFF provenance that
# render_text() has no way to know. Without this, `render` replaced rather than composed,
# silently deleting whatever header a human had written into ledger.md.
HEADER = "ledger/HEADER.md"

# A row's status is never stored. It is the last status-bearing event for that id.
CREATE = "created"


def _digest(payload: dict) -> str:
    """Hash of the event's content plus its predecessor -- a chain, so that rewriting
    history is detectable. It is NOT prevention: `>` still truncates the file. Detection
    only helps because `verify` looks, which is why CI runs it."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()[:32]


def events_path(eng: Path) -> Path:
    return eng / EVENTS


def read_events(eng: Path) -> list[dict]:
    p = events_path(eng)
    if not p.exists():
        return []
    out = []
    for n, line in enumerate(p.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{p}:{n} is not valid JSON ({e}). "
                             f"The log is append-only; do not hand-edit it.") from e
    return out


def append(eng: Path, event: dict) -> dict:
    """Append one event, chained to its predecessor. Callers MUST have run the
    preconditions first -- this function enforces nothing about content by design, so
    that the precondition logic lives in exactly one place (cli.py) and is testable
    without a filesystem."""
    prior = read_events(eng)
    event = dict(event)
    event["seq"] = len(prior) + 1
    event["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event["prev"] = prior[-1]["hash"] if prior else None
    event["hash"] = _digest(event)
    p = events_path(eng)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def replay(eng: Path) -> dict[str, dict]:
    """Fold the log into current per-row state.

    `satisfied` is the STATE LOCKING set: preconditions this row has already
    discharged. It only ever grows. G1 already worked this way by convention -- dedup
    paid at TIER-1 is not re-charged downstream -- and CAAF (arXiv 2604.17025) reports
    that a deterministic validator WITHOUT monotonic locking scored 0% at commodity
    reasoning, because the model repaired one constraint while re-breaking another.
    Their own implementation is a sentence in a prompt; this is the enforced version.
    """
    rows: dict[str, dict] = {}
    for e in read_events(eng):
        rid = e["id"]
        row = rows.setdefault(rid, {
            "id": rid, "status": None, "satisfied": [], "history": [], "fields": {},
        })
        if e["event"] == CREATE:
            row["status"] = e.get("status", "UNTESTED")
        elif "to" in e:
            row["status"] = e["to"]
        # `reason` belongs here for the same purpose as `human`: check_below_bar() parses
        # REASON: out of the rendered row, so omitting it made BELOW-BAR unusable through the
        # CLI -- the guard would reject the CLI's own render. (engagement 16, 2026-09-04.)
        for k in ("hypothesis", "entry", "invariant", "dedup", "evidence", "human", "reason"):
            if e.get(k):
                row["fields"][k] = e[k]
        for g in e.get("satisfied", []):
            if g not in row["satisfied"]:
                row["satisfied"].append(g)
        row["history"].append(e)
    return rows


def status_path(row: dict) -> list[str]:
    """The statuses this row has held, in order, collapsing repeats."""
    path = []
    for e in row["history"]:
        new = e.get("status") or e.get("to")
        if new and (not path or new != path[-1]):
            path.append(new)
    return path


def status_changes(row: dict) -> int:
    """Transitions AFTER creation. A healthy row that reaches a verdict has 2:
    UNTESTED -> TIER-1 -> REFUTED. Creation is not a change."""
    return max(0, len(status_path(row)) - 1)


def revisits(row: dict) -> int:
    """OSCILLATION COUNTER -- the number of times a row RE-ENTERS a status it already
    left.

    First cut counted every status change, which scored a healthy UNTESTED -> TIER-1 ->
    REFUTED row as 3 and would have flagged every properly-processed row as oscillating.
    That is the wrong signal: forward progress is not oscillation. What CAAF's Finding 8
    describes is a system repairing one constraint while re-breaking another -- returning
    to a state it had already left (their 55 <-> 84 km/h seesaw). So this counts revisits.

    Our preconditions are independent per row, so we EXPECT zero. Expecting is not
    measuring, and the count is free.
    """
    seen, back = set(), 0
    for st in status_path(row):
        if st in seen:
            back += 1
        seen.add(st)
    return back
