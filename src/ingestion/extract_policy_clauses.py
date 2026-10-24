#!/usr/bin/env python3
"""Extract numbered clauses and produce draft structured records from policy PDFs.

The structured fields are heuristic suggestions. They are not policy advice or
human-verified coverage determinations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

PARSER_VERSION = "1.0.0"
UIN = "NIAHLIP25044V022425"
INSURER = "The New India Assurance Co. Ltd."
PRODUCT = "Arogya Sanjeevani Policy"

_HEADER_RE = re.compile(r"^(?:Page\s+\d+\s+of\s+\d+\s+UIN:.*|AROGYA SANJEEVANI POLICY.*)$", re.I)
_FULL_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+){1,4})\s*[.)]?\s+(.+?)\s*$")
_TOP_LEVEL_RE = re.compile(r"^\s*(\d{1,2})\s*[.)]?\s+(.+?)\s*$")
_BARE_ITEM_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]?\s+(.+?)\s*$")
_WAITING_RE = re.compile(
    r"\b(?:waiting\s+period|wait(?:ing)?\s+of)\b[^.;\n]{0,180}", re.I
)
_DURATION_RE = re.compile(
    r"\b(?:\d+\s*(?:days?|months?|years?)|one\s+year|two\s+years|"
    r"three\s+years|four\s+years|thirty\s+days|sixty\s+months)\b", re.I
)
_CONDITION_RE = re.compile(r"\b(?:if|when|where|provided\s+that|subject\s+to)\b[^.;\n]*", re.I)
_EXCEPTION_RE = re.compile(
    r"\b(?:unless|except(?:\s+for)?|other\s+than|notwithstanding|"
    r"(?:shall|will)?\s+not(?:\s+be)?\s+applicable(?:\s+for|\s+to)?|"
    r"(?:shall|will)?\s+not\s+apply(?:\s+to)?)\b[^.;\n]*",
    re.I,
)

# These numbered lists are subordinate to a numbered policy clause. Other bare
# numbers in prose are not treated as clause boundaries.
_NUMBERED_LIST_ROOTS = {"6", "7", "9", "10", "12"}
_MAIN_HEADINGS = {
    1: "preamble",
    2: "operative clause",
    3: "definitions",
    4: "coverage",
    5: "cumulative bonus",
    6: "waiting period",
    7: "exclusions",
    8: "moratorium period",
    9: "claim procedure",
    10: "general terms",
    11: "redressal of grievance",
    12: "table of benefits",
}


@dataclass
class Clause:
    clause_number: str
    displayed_number: str
    title: str
    page_start: int
    section_context: dict[str, Any] | None = None
    source_lines: list[tuple[int, str]] = field(default_factory=list)

    def add(self, page: int, text: str) -> None:
        self.source_lines.append((page, text))

    def as_raw_record(self, source_document: str, sha256: str) -> dict[str, Any]:
        pages = list(dict.fromkeys(page for page, _ in self.source_lines))
        return {
            "clause_id": f"new_india_arogya_sanjeevani:{self.clause_number}",
            "clause_number": self.clause_number,
            "displayed_number": self.displayed_number,
            "parent_clause_number": self.clause_number.rsplit(".", 1)[0]
            if "." in self.clause_number else None,
            "hierarchy": self.clause_number.split("."),
            "title": self.title,
            "page_number": self.page_start,
            "page_numbers": pages,
            "source_document": source_document,
            "source_sha256": sha256,
            "section_context": self.section_context,
            "source_text": "\n".join(line for _, line in self.source_lines).strip(),
            "source_spans": [
                {"page_number": page, "text": line}
                for page, line in self.source_lines
            ],
        }


def _clean_line(line: str) -> str:
    return re.sub(r"[\t\u00a0 ]+", " ", line).strip()


def _is_annexure(line: str) -> bool:
    return bool(re.match(r"^\s*Annexure\s*[-–:]?\s*[A-Z0-9]*\s*$", line, re.I))


def _is_top_level_heading(match: re.Match[str]) -> bool:
    """Recognize numbered main clauses while avoiding numbered prose."""
    number, title = match.groups()
    if int(number) not in range(1, 13):
        return False
    # Require a known section title. This prevents the many bare numbered
    # subitems under waiting periods and exclusions from resetting hierarchy.
    expected = _MAIN_HEADINGS[int(number)]
    return len(title) < 100 and expected in title.lower()


def extract_clauses(pdf_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Policy PDF not found: {pdf_path}")
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    reader = PdfReader(str(pdf_path))
    clauses: list[Clause] = []
    current: Clause | None = None
    current_parent: str | None = None
    list_ordinals: dict[str, int] = {}
    list_context: dict[str, Any] | None = None
    in_annexure = False

    def start_clause(number: str, displayed: str, title: str, page: int, source_line: str) -> None:
        nonlocal current, current_parent
        current = Clause(number, displayed, title.strip(), page)
        current.add(page, source_line)
        clauses.append(current)
        current_parent = number

    for page_number, page in enumerate(reader.pages, start=1):
        for raw_line in (page.extract_text() or "").splitlines():
            line = _clean_line(raw_line)
            if not line or _HEADER_RE.match(line):
                continue
            if _is_annexure(line):
                in_annexure = True
                current = None
                continue
            if in_annexure:
                continue

            context_heading = re.match(
                r"^\(?\s*(?:[ivx]+[.)]?\s*)?(\d+)\s+Months?\s+waiting\s+period\s*\)?$",
                line,
                re.I,
            )
            if context_heading:
                list_context = {"text": line, "page_number": page_number}
                if current is not None:
                    current.add(page_number, line)
                continue

            full = _FULL_NUMBER_RE.match(line)
            if full:
                number, title = full.groups()
                # Avoid treating dates/decimal references as clause boundaries.
                start_clause(number, number, title, page_number, line)
                if number.split(".", 1)[0] not in _NUMBERED_LIST_ROOTS:
                    list_context = None
                continue

            top = _TOP_LEVEL_RE.match(line)
            if top and _is_top_level_heading(top):
                number, title = top.groups()
                start_clause(number, number, title, page_number, line)
                list_context = None
                continue

            # The policy uses simple numbered lists for the specific waiting
            # periods, exclusions, claim procedure, general conditions and
            # benefits. Preserve those items as descendants of the section.
            item = _BARE_ITEM_RE.match(line)
            if current_parent and current_parent.split(".", 1)[0] in _NUMBERED_LIST_ROOTS and item:
                ordinal = list_ordinals.get(current_parent, 0) + 1
                list_ordinals[current_parent] = ordinal
                shown, title = item.groups()
                parent = current_parent
                number = f"{parent}.{ordinal}"
                current = Clause(number, shown, title.strip(), page_number, list_context)
                current.add(page_number, line)
                clauses.append(current)
                # Keep consecutive list items under the same section or
                # subsection, even after one becomes the current clause.
                current_parent = parent
                continue

            if current is not None:
                current.add(page_number, line)

    raw_records = [c.as_raw_record(pdf_path.name, digest) for c in clauses]
    source_metadata = {
        "source_document": pdf_path.name,
        "source_sha256": digest,
        "page_count": len(reader.pages),
        "insurer": INSURER,
        "product": PRODUCT,
        "uin_observed_in_policy_pdf": UIN,
        "parser_version": PARSER_VERSION,
    }
    return raw_records, source_metadata


def _unique_matches(pattern: re.Pattern[str], text: str) -> list[str]:
    found: list[str] = []
    for match in pattern.finditer(text):
        value = re.sub(r"\s+", " ", match.group(0)).strip(" .;\n")
        if value and value not in found:
            found.append(value)
    return found


def _topic(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if "waiting period" in lowered or "waiting periods" in lowered or "waiting of" in lowered:
        return "waiting_period", "eligibility_or_timing"
    if "room rent" in lowered or "boarding" in lowered:
        return "room_rent_limit", "benefit_limit"
    if "co-payment" in lowered or "co payment" in lowered:
        return "co_payment", "cost_sharing"
    if "cataract" in lowered:
        return "cataract_limit", "benefit_limit"
    if "pre-existing" in lowered or "pre existing" in lowered:
        return "pre_existing_condition", "eligibility_or_timing"
    if "exclusion" in lowered or "not covered" in lowered or "excluded" in lowered:
        return "exclusion", "exclusion"
    if "hospitalisation" in lowered or "hospitalization" in lowered:
        return "hospitalisation_coverage", "coverage"
    return "general_policy_term", "definition_or_condition"


def structure_clause(
    raw: dict[str, Any],
    source_metadata: dict[str, Any],
    raw_by_number: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = raw["source_text"]
    parent_number = raw.get("parent_clause_number")
    parent_raw = (raw_by_number or {}).get(parent_number) if parent_number else None
    parent_text = parent_raw["source_text"] if parent_raw else ""
    topic, rule_type = _topic(text)
    # Carry section context into numbered waiting-period subitems.
    if raw["clause_number"].startswith("6."):
        topic, rule_type = "waiting_period", "eligibility_or_timing"
    list_context_text = (raw.get("section_context") or {}).get("text", "")
    context_text = "\n".join(part for part in (parent_text, list_context_text) if part)
    # Keep the local list duration scoped to that item; durations mentioned in
    # a parent clause remain visible in a separate field rather than being
    # silently applied to every child.
    duration_matches = _unique_matches(_DURATION_RE, text + "\n" + list_context_text)
    parent_duration_matches = _unique_matches(_DURATION_RE, parent_text)
    waiting_spans = _unique_matches(_WAITING_RE, text + "\n" + context_text)
    waiting_period = None
    if topic == "waiting_period":
        waiting_period = {
            "duration_text": duration_matches,
            "parent_duration_mentions": parent_duration_matches,
            "period_start_text": None,
            "applies_to_text": waiting_spans,
            "section_context_text": list_context_text or None,
            "section_context_page_number": (raw.get("section_context") or {}).get("page_number"),
            "raw_waiting_period_spans": waiting_spans,
            "interpretation_note": (
                "Durations and applicability are retained as source-linked text; "
                "no single numeric threshold is inferred."
            ),
        }

    return {
        "record_id": raw["clause_id"],
        "clause_number": raw["clause_number"],
        "displayed_number": raw["displayed_number"],
        "parent_clause_number": raw["parent_clause_number"],
        "hierarchy": raw["hierarchy"],
        "title": raw["title"],
        "source": {
            "document": raw["source_document"],
            "sha256": raw["source_sha256"],
            "page_number": raw["page_number"],
            "page_numbers": raw["page_numbers"],
            "insurer": source_metadata["insurer"],
            "product": source_metadata["product"],
            "uin_observed_in_policy_pdf": source_metadata["uin_observed_in_policy_pdf"],
        },
        "source_text": text,
        "proposed_interpretation": {
            "topic": topic,
            "rule_type": rule_type,
            "applicability_conditions": _unique_matches(_CONDITION_RE, text + "\n" + parent_text),
            "exceptions": _unique_matches(_EXCEPTION_RE, text + "\n" + parent_text),
            "parent_context": ({
                "clause_number": parent_number,
                "source_text": parent_text,
                "page_numbers": parent_raw["page_numbers"],
            } if parent_raw else None),
            "waiting_period": waiting_period,
            "numeric_threshold": None,
            "interpretation_method": "keyword_and_span_heuristics",
            "review_flags": ["verify_against_policy_wording", "check_policy_version_and_schedule"],
        },
        "verification_status": "not_human_verified",
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_pipeline(pdf_path: Path, raw_output: Path, structured_output: Path) -> tuple[int, int]:
    raw_records, metadata = extract_clauses(pdf_path)
    raw_by_number = {record["clause_number"]: record for record in raw_records}
    structured_records = [structure_clause(record, metadata, raw_by_number) for record in raw_records]
    write_jsonl(raw_output, raw_records)
    write_jsonl(structured_output, structured_records)
    return len(raw_records), sum(r["proposed_interpretation"]["topic"] == "waiting_period" for r in structured_records)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=root / "data/policies/new_india/policy_wording.pdf")
    parser.add_argument("--raw-output", type=Path, default=root / "data/processed/extracted_clauses_raw.jsonl")
    parser.add_argument("--structured-output", type=Path, default=root / "data/processed/policy_clauses_structured.jsonl")
    args = parser.parse_args()
    count, waiting = run_pipeline(args.pdf, args.raw_output, args.structured_output)
    print(f"Wrote {count} raw clauses and {count} structured draft records ({waiting} tagged as waiting-period related).")
    print("Structured records are heuristic drafts and have not been human-verified.")


if __name__ == "__main__":
    main()
