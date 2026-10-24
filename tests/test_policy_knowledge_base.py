import json
from pathlib import Path

import pytest

from src.ingestion.build_policy_knowledge_base import (
    build_knowledge_base,
    clause_records,
    split_text,
)

ROOT = Path(__file__).resolve().parents[1]


def test_split_text_respects_size_and_keeps_content():
    text = ("First paragraph. " * 60) + "\n\n" + ("Second paragraph. " * 60)
    chunks = split_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "First paragraph." in " ".join(chunks)
    assert "Second paragraph." in " ".join(chunks)


def test_policy_chunks_keep_provenance_and_exceptions():
    path = ROOT / "data/processed/policy_clauses_structured.jsonl"
    records = clause_records(path, chunk_size=1800, overlap=250)
    assert records
    waiting = next(r for r in records if r["clause_number"] == "6.2.1")
    assert waiting["source"]["document"] == "policy_wording.pdf"
    assert waiting["source"]["page_numbers"]
    assert waiting["verification_status"] == "not_human_verified"
    assert waiting["proposed_interpretation"]["waiting_period"]["duration_text"]
    assert waiting["proposed_interpretation"]["numeric_threshold"] is None
    assert waiting["proposed_interpretation"]["exceptions"]


def test_builder_checks_structured_source_hash(tmp_path):
    structured = tmp_path / "structured.jsonl"
    structured.write_text(json.dumps({
        "record_id": "dummy:1",
        "source_text": "Sample policy clause text.",
        "source": {"document": "policy_wording.pdf", "sha256": "wrong"},
        "proposed_interpretation": {},
        "verification_status": "not_human_verified"
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash does not match"):
        build_knowledge_base(
            ROOT / "data/policies/new_india/policy_wording.pdf",
            ROOT / "data/policies/new_india/excluded_items.pdf",
            structured,
            tmp_path / "kb.jsonl",
            tmp_path / "manifest.json",
        )
