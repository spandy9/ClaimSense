#!/usr/bin/env python3
"""Build the retrieval knowledge base directly from the two source PDFs.

The numbered-clause parser runs in memory against policy_wording.pdf. The
excluded-items PDF is extracted independently. The structured JSONL produced by
the separate clause-review pipeline is not an input to this builder.

This script does not make coverage decisions or verify heuristic interpretations.
It produces provenance-preserving JSONL chunks suitable for later embedding and
indexing into Chroma, FAISS, or another vector store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

# Resolve the shared extractor whether this file is run as a script or imported.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ingestion.extract_policy_clauses import (
    PARSER_VERSION as CLAUSE_PARSER_VERSION,
    extract_clauses,
    structure_clause,
)

PARSER_VERSION = "1.0.0"
DEFAULT_POLICY = "data/policies/new_india/policy_wording.pdf"
DEFAULT_EXCLUSIONS = "data/policies/new_india/excluded_items.pdf"
DEFAULT_OUTPUT = "data/knowledge_base/policy_knowledge_base.jsonl"
DEFAULT_MANIFEST = "data/knowledge_base/manifest.json"
DEFAULT_CHUNK_SIZE = 1800
DEFAULT_OVERLAP = 250


def portable_path(path: Path) -> str:
    """Return a repository-relative path when the input lives inside the repo."""
    resolved = Path(path).resolve()
    project_root = Path(__file__).resolve().parents[2]
    try:
        return resolved.relative_to(project_root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def clean_pdf_text(text: str) -> str:
    # Normalize extraction artifacts lightly; preserve original wording and
    # punctuation as returned by pypdf rather than rewriting legal language.
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split at paragraph/sentence/space boundaries while enforcing a hard cap."""
    if max_chars < 200:
        raise ValueError("--chunk-size must be at least 200 characters")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("--overlap must be >= 0 and smaller than --chunk-size")
    text = clean_pdf_text(text)
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            # Prefer nearby semantic boundaries in the latter half of the window.
            floor = start + max_chars // 2
            candidates = [text.rfind("\n\n", floor, end), text.rfind("\n", floor, end),
                          text.rfind(". ", floor, end), text.rfind("; ", floor, end),
                          text.rfind(" ", floor, end)]
            boundary = max(candidates)
            if boundary > start:
                end = min(end, boundary + (1 if text[boundary:boundary + 1] in "\n " else 2))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def clause_records(policy_pdf: Path, chunk_size: int, overlap: int) -> list[dict[str, Any]]:
    """Extract and structure clauses directly from the source policy PDF.

    Raw and structured records are built in memory. The separate structured
    JSONL remains available for review, but is not an input to this builder.
    """
    raw_records, source_metadata = extract_clauses(policy_pdf)
    raw_by_number = {record["clause_number"]: record for record in raw_records}
    records = [structure_clause(record, source_metadata, raw_by_number) for record in raw_records]
    kb: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for record in records:
        rid = str(record.get("record_id") or record.get("clause_id") or "").strip()
        if not rid:
            raise ValueError("Structured clause record missing record_id/clause_id")
        if rid in seen_ids:
            raise ValueError(f"Duplicate clause identifier in structured file: {rid}")
        seen_ids.add(rid)

        source = record.get("source") or {}
        interpretation = record.get("proposed_interpretation") or {}
        raw_text = str(record.get("source_text") or "").strip()
        if not raw_text:
            raise ValueError(f"Clause {rid} has empty source_text")
        pieces = split_text(raw_text, chunk_size, overlap)
        parent = interpretation.get("parent_context") or {}
        waiting = interpretation.get("waiting_period")
        for idx, piece in enumerate(pieces, start=1):
            chunk_id = f"clause::{rid}::part-{idx:03d}"
            parent_source_text = str(parent.get("source_text") or "").strip()
            parent_heading = parent_source_text.splitlines()[0].strip() if parent_source_text else ""
            # Repeating a compact section context makes terse list items
            # retrievable (e.g., a disease name under a waiting-period section).
            # The exact chunk text remains separately available as source_text.
            context_lines = [
                f"Policy wording clause {record.get('clause_number')}: {record.get('title') or ''}".strip(),
            ]
            if parent_heading:
                context_lines.append(f"Parent section {parent.get('clause_number') or record.get('parent_clause_number')}: {parent_heading}")
            if parent_source_text and str(interpretation.get("topic") or "") == "waiting_period":
                context_lines.append("Waiting-period section context: " + parent_source_text[:1400])
            retrieval_text = "\n".join(context_lines) + "\nClause source text:\n" + piece
            kb.append({
                "chunk_id": chunk_id,
                "record_type": "policy_clause",
                "text": retrieval_text,
                "source_text": piece,
                "title": record.get("title"),
                "clause_id": rid,
                "clause_number": record.get("clause_number"),
                "displayed_number": record.get("displayed_number"),
                "parent_clause_number": record.get("parent_clause_number"),
                "hierarchy": record.get("hierarchy") or [],
                "chunk_index": idx,
                "chunk_count": len(pieces),
                "source": {
                    "document": source.get("document") or "policy_wording.pdf",
                    "sha256": source.get("sha256"),
                    "page_number": source.get("page_number"),
                    "page_numbers": source.get("page_numbers") or [],
                    "insurer": source.get("insurer"),
                    "product": source.get("product"),
                    "uin_observed_in_policy_pdf": source.get("uin_observed_in_policy_pdf"),
                },
                "proposed_interpretation": {
                    "topic": interpretation.get("topic"),
                    "rule_type": interpretation.get("rule_type"),
                    "applicability_conditions": interpretation.get("applicability_conditions") or [],
                    "exceptions": interpretation.get("exceptions") or [],
                    "numeric_threshold": interpretation.get("numeric_threshold"),
                    "waiting_period": waiting,
                    "interpretation_method": interpretation.get("interpretation_method"),
                    "parent_context": {
                        "clause_number": parent.get("clause_number") or record.get("parent_clause_number"),
                        "source_text": parent.get("source_text"),
                        "page_numbers": parent.get("page_numbers") or [],
                    } if parent else None,
                },
                "verification_status": record.get("verification_status", "not_human_verified"),
                "authority_level": "primary_policy_wording",
                "retrieval_warning": (
                    "Retrieve as source evidence only. Proposed interpretation is heuristic; "
                    "do not treat it as verified or sufficient for an automated coverage decision."
                ),
            })
    return kb


def exclusion_page_records(pdf_path: Path, chunk_size: int, overlap: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Excluded-items PDF not found: {pdf_path}")
    digest = sha256_file(pdf_path)
    reader = PdfReader(str(pdf_path))
    records: list[dict[str, Any]] = []
    for page_no, page in enumerate(reader.pages, start=1):
        page_text = clean_pdf_text(page.extract_text() or "")
        if not page_text:
            records.append({
                "chunk_id": f"excluded-items::page-{page_no:03d}::part-001",
                "record_type": "excluded_items_reference",
                "text": "",
                "source": {"document": pdf_path.name, "sha256": digest, "page_number": page_no,
                           "page_numbers": [page_no]},
                "verification_status": "not_human_verified",
                "authority_level": "supporting_exclusions_reference",
                "review_flags": ["page_text_empty_or_needs_ocr_review"],
                "retrieval_warning": (
                    "Supporting excluded-items reference, not a substitute for policy wording. "
                    "Cross-check item definition, applicability, exceptions and policy version."
                ),
            })
            continue
        pieces = split_text(page_text, chunk_size, overlap)
        for idx, piece in enumerate(pieces, start=1):
            records.append({
                "chunk_id": f"excluded-items::page-{page_no:03d}::part-{idx:03d}",
                "record_type": "excluded_items_reference",
                "text": piece,
                "source": {"document": pdf_path.name, "sha256": digest, "page_number": page_no,
                           "page_numbers": [page_no]},
                "verification_status": "not_human_verified",
                "authority_level": "supporting_exclusions_reference",
                "review_flags": ["cross_check_against_policy_wording", "check_policy_version_and_schedule"],
                "retrieval_warning": (
                    "Supporting excluded-items reference, not a substitute for policy wording. "
                    "Cross-check item definition, applicability, exceptions and policy version."
                ),
            })
    extracted_characters = sum(len((page.extract_text() or "").strip()) for page in reader.pages)
    if extracted_characters < 80:
        raise ValueError(
            f"Very little text could be extracted from {pdf_path.name} "
            f"({extracted_characters} characters); OCR or layout-specific extraction is likely needed."
        )
    metadata = {
        "extracted_characters": extracted_characters,
        "document": pdf_path.name,
        "sha256": digest,
        "page_count": len(reader.pages),
        "record_type": "excluded_items_reference",
        "authority_level": "supporting_exclusions_reference",
    }
    return records, metadata


def build_knowledge_base(
    policy_pdf: Path,
    exclusions_pdf: Path,
    output_jsonl: Path,
    manifest_path: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> dict[str, Any]:
    for path in (policy_pdf, exclusions_pdf):
        if not path.is_file():
            raise FileNotFoundError(f"Required source PDF not found: {path}")

    policy_records = clause_records(policy_pdf, chunk_size, overlap)
    exclusion_records, exclusion_meta = exclusion_page_records(exclusions_pdf, chunk_size, overlap)

    # Confirm the in-memory extractor is tied to the exact source PDF.
    expected_policy_hash = sha256_file(policy_pdf)
    mismatches = [
        record.get("clause_id")
        for record in policy_records
        if (record.get("source") or {}).get("sha256") != expected_policy_hash
    ]
    if mismatches:
        raise ValueError(
            f"In-memory clause extraction hash differs from policy_wording.pdf "
            f"for {len(mismatches)} chunks."
        )

    combined = policy_records + exclusion_records
    # Deterministic order and unique stable IDs are useful for reproducible embedding runs.
    ids = [r["chunk_id"] for r in combined]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate chunk_id generated; refusing to write KB")
    written = write_jsonl(output_jsonl, combined)

    policy_reader = PdfReader(str(policy_pdf))
    manifest = {
        "knowledge_base_version": "1.0.0",
        "built_by": "src/ingestion/build_policy_knowledge_base.py",
        "inputs": {
            "policy_wording": {
                "path": portable_path(policy_pdf),
                "sha256": expected_policy_hash,
                "page_count": len(policy_reader.pages),
                "authority_level": "primary_policy_wording",
            },
            "excluded_items": {
                "path": portable_path(exclusions_pdf),
                **exclusion_meta,
                "authority_note": (
                    "Supporting reference; verify consistency with the policy wording and "
                    "applicable policy version before using an item as a rule."
                ),
            },
        },
        "clause_extraction": {
            "source": "policy_wording.pdf",
            "method": "pypdf extraction and in-memory numbered-clause heuristics",
            "parser": "src/ingestion/extract_policy_clauses.py",
            "parser_version": CLAUSE_PARSER_VERSION,
            "derived_record_count": len({record.get("clause_id") for record in policy_records}),
            "verification_status": "heuristic_draft_not_human_verified",
            "intermediate_jsonl_used_as_input": False,
        },
        "outputs": {
            "jsonl_path": portable_path(output_jsonl),
            "record_count": written,
            "policy_clause_chunks": len(policy_records),
            "excluded_items_chunks": len(exclusion_records),
            "unique_chunk_ids": len(set(ids)),
        },
        "chunking": {"max_chars": chunk_size, "overlap_chars": overlap,
                     "split_strategy": "paragraph_sentence_whitespace_boundaries"},
        "safety_and_provenance": [
            "Source text is retained separately from proposed interpretation.",
            "All chunks require human verification before use as authoritative adjudication rules.",
            "Waiting-period applicability, conditions and exceptions are retained as source-linked text.",
            "No numeric threshold is inferred by this builder.",
            "The excluded-items PDF is not treated as overriding policy wording.",
            "For final decisions, check the policy schedule, endorsements, coverage dates and version.",
        ],
        "limitations": [
            "PDF text extraction may omit text embedded in images or complex layouts; inspect empty pages.",
            "Clause-level heuristics may mislabel topics/conditions/exceptions and are not proof of meaning.",
            "This output is a retrieval corpus, not an embedding index; embeddings and vector-store schema are downstream steps.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-pdf", type=Path, default=root / DEFAULT_POLICY)
    parser.add_argument("--excluded-items-pdf", type=Path, default=root / DEFAULT_EXCLUSIONS)
    parser.add_argument("--output", type=Path, default=root / DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=root / DEFAULT_MANIFEST)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    args = parser.parse_args()
    manifest = build_knowledge_base(args.policy_pdf, args.excluded_items_pdf,
                                    args.output, args.manifest, args.chunk_size, args.overlap)
    print(json.dumps(manifest["outputs"], indent=2))
    print("WARNING: this is a retrieval corpus, not verified policy logic or a settlement authority.")


if __name__ == "__main__":
    main()
