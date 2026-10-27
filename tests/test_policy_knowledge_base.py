import json
from pathlib import Path

from src.ingestion.build_policy_knowledge_base import (
    build_knowledge_base,
    clause_records,
    split_text,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PDF = ROOT / "data/policies/new_india/policy_wording.pdf"
EXCLUSIONS_PDF = ROOT / "data/policies/new_india/excluded_items.pdf"


def test_split_text_respects_size_and_keeps_content():
    text = ("First paragraph. " * 60) + "\n\n" + ("Second paragraph. " * 60)
    chunks = split_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "First paragraph." in " ".join(chunks)
    assert "Second paragraph." in " ".join(chunks)


def test_policy_chunks_are_extracted_directly_from_pdf():
    records = clause_records(POLICY_PDF, chunk_size=1800, overlap=250)
    assert records
    waiting = next(r for r in records if r["clause_number"] == "6.2.1")
    assert waiting["source"]["document"] == "policy_wording.pdf"
    assert waiting["source"]["sha256"]
    assert waiting["source"]["page_numbers"]
    assert waiting["verification_status"] == "not_human_verified"
    assert waiting["proposed_interpretation"]["waiting_period"]["duration_text"]
    assert waiting["proposed_interpretation"]["numeric_threshold"] is None
    assert waiting["proposed_interpretation"]["exceptions"]
    assert "waiting-period section context" in waiting["text"].lower()


def test_builder_uses_only_the_two_source_pdfs(tmp_path):
    output = tmp_path / "policy_knowledge_base.jsonl"
    manifest_path = tmp_path / "manifest.json"
    manifest = build_knowledge_base(
        POLICY_PDF,
        EXCLUSIONS_PDF,
        output,
        manifest_path,
        chunk_size=1800,
        overlap=250,
    )

    assert output.is_file()
    assert manifest_path.is_file()
    assert set(manifest["inputs"]) == {"policy_wording", "excluded_items"}
    assert manifest["clause_extraction"]["source"] == "policy_wording.pdf"
    assert manifest["clause_extraction"]["intermediate_jsonl_used_as_input"] is False

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(records) == manifest["outputs"]["record_count"]
    assert len({record["chunk_id"] for record in records}) == len(records)
    assert all(record["verification_status"] == "not_human_verified" for record in records)

    policy = [r for r in records if r["record_type"] == "policy_clause"]
    exclusions = [r for r in records if r["record_type"] == "excluded_items_reference"]
    assert policy and exclusions
    assert {r["source"]["document"] for r in policy} == {"policy_wording.pdf"}
    assert {r["source"]["document"] for r in exclusions} == {"excluded_items.pdf"}
    assert all(r["source"]["page_numbers"] for r in policy + exclusions)

    waiting = [r for r in policy if r["proposed_interpretation"]["topic"] == "waiting_period"]
    assert waiting
    assert all(r["proposed_interpretation"]["numeric_threshold"] is None for r in waiting)
    assert all(isinstance(r["proposed_interpretation"]["applicability_conditions"], list) for r in waiting)
    assert all(isinstance(r["proposed_interpretation"]["exceptions"], list) for r in waiting)


def test_builder_rejects_missing_source_pdf(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    try:
        build_knowledge_base(
            missing,
            EXCLUSIONS_PDF,
            tmp_path / "kb.jsonl",
            tmp_path / "manifest.json",
        )
    except FileNotFoundError as exc:
        assert "Required source PDF not found" in str(exc)
    else:
        raise AssertionError("Expected missing policy PDF to be rejected")
