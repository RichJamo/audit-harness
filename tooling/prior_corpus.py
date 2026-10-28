"""Is every prior-audit report read? One answer, shared by the ledger CLI and the engagement doctor.

REF-31 (engagement 22): the client's internal audit had two rounds in one folder, and only round 1 was
extracted and keyed. A finding in round 2 duplicated one we filed. Nothing checked that every
report under `00-triage/prior-audits/` had been turned into text and a key.

EVERY REPORT FILE IS ITS OWN UNIT: each `.pdf`, `.html`, `.htm`, `.md` or `.txt` under prior-audits/, at
any depth. (A first version counted a folder as one report; review found a folder on disk holding
several separate reviews, which one extract would then have marked read.) A file is
covered when
- `prior-audits-text/<stem>.txt` and `prior-audit-keys/<stem>.json` both exist, or
- `00-triage/prior-audit-index.md` has a line for the file, or
- the index has a line for a FOLDER above it, and the file is `.md` or `.txt` (the pieces of a report
  delivered as a folder: findings, verification notes, model outputs), and no folder between them
  looks like another round (a name holding `v2`, `r2`, `round`, `second`, ...). A PDF or HTML file is a
  whole report and is never covered by a folder line.
Index lines name files that must exist, as plain file names inside their folders:
    - <path under prior-audits/> | text: <file in prior-audits-text/> | key: <file in prior-audit-keys/>
    - <path under prior-audits/> | not a report: <why>
The index lives beside prior-audits/, not in it: any file in prior-audits/ satisfies G1's "corpus on
disk", so an index there would let an engagement with no reports pass G1.

ENFORCED ONLY WHERE `00-triage/prior-audit-index.md` EXISTS (`enforced()`). `new-engagement.sh` writes
one, so engagements created from 2026-10-19 are checked from the start; older ones are silent until
someone adds the file. Measured on 2026-10-19: nearly every
engagement on disk would fire, because per-report keys only became the standard step on 2026-10-14;
checking them all would refuse every promotion on every live engagement and get the check disabled
(constraint 3 in CLAUDE.md). Silent also where `00-triage/NO-PRIOR-ART.md` declares no prior art,
the same marker G1 and the doctor read.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

REPORT_SUFFIXES = (".pdf", ".html", ".htm", ".md", ".txt")
FOLDER_PIECE_SUFFIXES = (".md", ".txt")
INDEX = "prior-audit-index.md"   # in 00-triage/, NOT in prior-audits/: a file there satisfies G1's "corpus on disk"
# A folder name that may hold another round of the same audit: never covered by a line for its parent.
ROUND_LIKE = re.compile(r"(?i)(?:^|[^a-z0-9])(?:v\d+|r\d+|round|second|2nd|third|3rd)|round\d")
LINE = re.compile(r"^\s*[-*]\s*(?P<path>[^|]+?)\s*\|\s*(?P<rest>.+?)\s*$")
FIELD = r"(?i)(?<![a-z]){name}:\s*([^|]+?)\s*(?:\||$)"


def _dirs(eng: Path) -> tuple[Path, Path, Path]:
    t = eng / "00-triage"
    return t / "prior-audits", t / "prior-audits-text", t / "prior-audit-keys"


def reports(eng: Path) -> list[str]:
    """Every report file under prior-audits/ (paths relative to it), sorted."""
    src, _, _ = _dirs(eng)
    if not src.is_dir():
        return []
    return sorted(p.relative_to(src).as_posix() for p in src.rglob("*")
                  if p.is_file() and p.suffix.lower() in REPORT_SUFFIXES
                  and not any(part.startswith(".") for part in p.relative_to(src).parts))


def index_path(eng: Path) -> Path:
    return eng / "00-triage" / INDEX


def enforced(eng: Path) -> bool:
    """The check applies only where the engagement keeps an index (see the module docstring)."""
    return index_path(eng).is_file()


def index_entries(eng: Path) -> dict[str, str]:
    """{path under prior-audits/: the rest of its index line}."""
    f = index_path(eng)
    if not f.is_file():
        return {}
    out = {}
    for line in f.read_text(errors="ignore").splitlines():
        m = LINE.match(line)
        if m:
            out[m.group("path").strip().strip("`").rstrip("/")] = m.group("rest")
    return out


def _named_file(rest: str, name: str, folder: Path) -> Path | None:
    """The file an index line names for `name:`, if it is a plain file name inside `folder`."""
    m = re.search(FIELD.format(name=name), rest)
    if not m:
        return None
    value = m.group(1).strip("` ")
    if not value or "/" in value or "\\" in value or value.startswith("."):
        return None                     # a path that could leave the folder names nothing
    return folder / value


def _line_problem(rest: str, text_dir: Path, key_dir: Path) -> str | None:
    """None when an index line covers its target; otherwise what is wrong with it."""
    if re.match(r"(?i)not a report\s*:\s*\S", rest):
        return None
    problems = []
    text = _named_file(rest, "text", text_dir)
    if not (text and text.is_file()):
        problems.append("its `text:` is not a file in prior-audits-text/")
    key = _named_file(rest, "key", key_dir)
    if not (key and key.is_file()):
        problems.append("its `key:` is not a file in prior-audit-keys/")
    else:
        try:
            json.loads(key.read_text(errors="ignore"))
        except ValueError:
            problems.append("its `key:` is not valid JSON")
    return "; ".join(problems) or None


def _covering_folder_line(rel: str, entries: dict[str, str]) -> str | None:
    """The nearest folder above `rel` with an index line, unless a round-like folder lies between."""
    parts = PurePosixPath(rel).parts
    for depth in range(len(parts) - 1, 0, -1):
        folder = "/".join(parts[:depth])
        if folder in entries:
            between = parts[depth:-1]
            if any(ROUND_LIKE.search(p) for p in between):
                return None
            return folder
    return None


def uncovered(eng: Path) -> list[tuple[str, str]]:
    """[(report file, what is missing)] for every report not yet read into an extract and a key."""
    src, text_dir, key_dir = _dirs(eng)
    if not enforced(eng) or (eng / "00-triage" / "NO-PRIOR-ART.md").is_file():
        return []
    entries = index_entries(eng)
    out = []
    for rel in reports(eng):
        if rel in entries:
            problem = _line_problem(entries[rel], text_dir, key_dir)
            if problem:
                out.append((rel, f"its line in {INDEX} is incomplete: {problem}"))
            continue
        if PurePosixPath(rel).suffix.lower() in FOLDER_PIECE_SUFFIXES:
            folder = _covering_folder_line(rel, entries)
            if folder is not None:
                problem = _line_problem(entries[folder], text_dir, key_dir)
                if problem:
                    out.append((rel, f"the line for {folder}/ in {INDEX} is incomplete: {problem}"))
                continue
        stem = PurePosixPath(rel).stem
        if (text_dir / f"{stem}.txt").is_file() and (key_dir / f"{stem}.json").is_file():
            continue
        out.append((rel, f"no extract and key named {stem}, and no line in {INDEX}"))
    return out


def summary(missing: list[tuple[str, str]], limit: int = 3) -> str:
    """The unread reports, grouped by folder, short enough for one refusal message."""
    by_folder: dict[str, list[str]] = {}
    for rel, _ in missing:
        by_folder.setdefault(str(PurePosixPath(rel).parent), []).append(rel)
    parts = []
    for folder, files in by_folder.items():
        parts.append(files[0] if len(files) == 1 else f"{folder}/ ({len(files)} files)")
    shown = "; ".join(parts[:limit])
    return shown + (f"; +{len(parts) - limit} more folder(s)" if len(parts) > limit else "")
