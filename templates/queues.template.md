Copy to `03-evidence/queues.md`. List every UNTESTED ledger row exactly once, with the queue that will move it (a hunt pass, a PoC batch, a ruling for the human).
`tooling/engagement-doctor.py` reports rows missing or listed twice, and rows no longer UNTESTED; without this file it says nothing.
"Queue" here is the work list a row waits in. It is not a match verdict (KNOWN, PARTIAL, ATTACKS-FIX, NEW), which Phase 3 sets.

| row | queue |
|---|---|
