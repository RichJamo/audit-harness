#!/usr/bin/env python3
"""Extract prior-audit risk sections VERBATIM. No summarisation, by design.

Why this is a script and not an instruction: summarising is the default behaviour when a
model reads a 40-page PDF, and the compression is where meaning inverts. On engagement 3 a
digest reduced a two-paragraph Potential Risks entry to one phrase plus the editorial
"they filed it nowhere" -- which read as an opening when it was a scope exclusion.

Usage:
    extract_prior_art.py <engagement-dir> [--pdf-dir DIR] [--out DIR]

Reads   <engagement>/00-triage/prior-audits/*.pdf
Writes  <engagement>/00-triage/potential-risks/<name>-<section>.txt
        <engagement>/00-triage/prior-audits-text/<name>.txt   (full text, for dedup grep)
"""
from __future__ import annotations
import argparse, re, shutil, subprocess, sys
from pathlib import Path

# Section headings that carry documented-but-unfiled risk. Auditors name this differently;
# missing one means missing an exclusion list, so cast wide.
SECTION_HEADINGS = [
    "Potential Risks", "Observations", "Systemic Risks", "Centralization Risks",
    "Centralisation Risks", "Accepted Risks", "Notes", "Additional Notes",
    "General Recommendations", "Out of Scope", "Known Issues",
    # ChainSecurity's own names for the same two things (one 2026 report).
    "Excluded from scope", "Trust Model", "Trust Model and Roles",
]
# Headings that terminate a section.
STOP_HEADINGS = [
    "Findings", "Vulnerability Details", "Disclaimers", "Executive Summary",
    "Appendix 1", "Appendix 2", "Appendix 3", "Severities", "Scope",
    "System Overview", "Risks", "Documentation Quality", "Test Coverage",
    # ChainSecurity's sections between "Trust Model" and the findings. Without these a
    # Trust Model / Excluded-from-scope extract runs to EOF and swallows the whole report.
    "Limitations and use of report", "Terminology", "Open Findings", "Resolved Findings",
]


def _norm(line: str) -> str:
    """Strip form-feeds and surrounding whitespace.

    pdftotext prefixes a page-break heading with \\f, so a naive '^Potential Risks$'
    match silently misses the real section. Learned by missing it twice on engagement 3.
    """
    return line.replace("\f", "").strip()


def pdf_to_text(pdf: Path) -> str:
    if not shutil.which("pdftotext"):
        sys.exit("error: pdftotext not found (brew install poppler)")
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"error: pdftotext failed on {pdf.name}: {out.stderr.strip()}")
    return out.stdout


_SECTION_NUMBER = re.compile(r"^\d+(?:\.\d+)*\s+")


def _heading_key(line: str) -> str:
    """Drop a leading section number, so "8 Notes" matches the heading "Notes".

    ChainSecurity and Cantina both number every heading ("2.1.1 Excluded from scope",
    "3.2 Informational"). Exact matching never fired on either: 12 reports across the
    engagement 16 yielded 0 sections while the risk text sat there in plain sight.

    This does NOT reopen the table-of-contents hole the exact match was protecting
    against, because a ToC line keeps its trailing page number -- "8 Notes    19"
    reduces to "Notes    19", which still fails to equal "Notes".
    """
    return _SECTION_NUMBER.sub("", line, count=1).strip()


def find_sections(text: str) -> dict[str, str]:
    """Return {heading: verbatim body}. Takes the FIRST occurrence of each heading.

    Hacken reports carry the heading twice: the real section early, and a boilerplate
    definition under Appendix 1. Reading the appendix one shows an empty section.
    """
    lines = text.splitlines()
    norm = [_heading_key(_norm(l)) for l in lines]
    found: dict[str, str] = {}
    for heading in SECTION_HEADINGS:
        start = None
        for i, l in enumerate(norm):
            # exact match only: the table-of-contents line is "Potential Risks   7"
            if l == heading:
                start = i
                break
        if start is None:
            continue
        end = len(lines)
        for j in range(start + 1, len(norm)):
            if norm[j] in STOP_HEADINGS or (norm[j] in SECTION_HEADINGS and norm[j] != heading):
                end = j
                break
        body = "\n".join(lines[start:end]).rstrip()
        if len(body.splitlines()) > 1:
            found[heading] = body
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("engagement", type=Path)
    ap.add_argument("--pdf-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)

    eng = a.engagement.expanduser().resolve()
    pdf_dir = a.pdf_dir or eng / "00-triage" / "prior-audits"
    out_dir = a.out or eng / "00-triage" / "potential-risks"
    full_dir = eng / "00-triage" / "prior-audits-text"

    if not pdf_dir.is_dir():
        sys.exit(f"error: no prior-audits dir at {pdf_dir}")
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        # REF-24: this reads PDFs only. A census of ~/engagements/*/00-triage/prior-audits/
        # (2026-09) found no engagement holding a CodeHawks-shaped CSV/JSON corpus THERE --
        # the one that motivated this entry lives in a differently-named directory
        # (00-triage/prior-art/) on a different engagement -- so a parser for that shape
        # has no confirmed target yet and is not worth maintaining speculatively. Name the
        # fallback G1 actually accepts instead of a bare "no PDFs".
        other = sorted(f for f in pdf_dir.iterdir() if f.is_file())
        shape = (f" ({len(other)} non-PDF file(s) present: "
                 f"{', '.join(sorted({f.suffix or '(no ext)' for f in other}))} -- this "
                 f"extractor reads .pdf only)" if other else "")
        sys.exit(f"error: no PDFs in {pdf_dir}{shape}. Fall back to the hand-written path "
                 f"G1 actually checks: write verbatim risk-section extracts yourself as "
                 f"00-triage/potential-risks/<name>.txt (any non-empty .txt file satisfies "
                 f"it), or, if no prior audit exists at all, create "
                 f"00-triage/NO-PRIOR-ART.md.")

    out_dir.mkdir(parents=True, exist_ok=True)
    full_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for pdf in pdfs:
        name = pdf.stem
        text = pdf_to_text(pdf)
        (full_dir / f"{name}.txt").write_text(text)
        sections = find_sections(text)
        if not sections:
            print(f"  {name}: NO risk sections found -- check headings by hand", file=sys.stderr)
        for heading, body in sections.items():
            slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            dest = out_dir / f"{name}-{slug}.txt"
            dest.write_text(body + "\n")
            print(f"  {name}: {heading} -> {dest.name} ({len(body.splitlines())} lines)")
            total += 1
    print(f"\n{len(pdfs)} PDFs, {total} sections extracted verbatim -> {out_dir}")
    print(f"full text for dedup grep -> {full_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
