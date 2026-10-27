import json
from pathlib import Path

from src.ingestion.extract_policy_clauses import (
    extract_clauses,
    structure_clause,
    write_jsonl,
)


ROOT = Path(__file__).resolve().parents[1]


def test_extracts_numbered_clauses_with_hierarchy_and_source_pages():
    records, metadata = extract_clauses(ROOT / "data/policies/new_india/policy_wording.pdf")
    assert records
    assert metadata["page_count"] == 33
    assert records[0]["clause_number"] == "1"
    assert records[0]["page_number"] == 1
    assert any(record["clause_number"] == "6.2" for record in records)
    assert any(record["clause_number"].startswith("6.2.") for record in records)
    by_number = {record["clause_number"]: record for record in records}
    assert by_number["6.2.1"]["section_context"]["text"].endswith("24 Months waiting period")
    assert by_number["6.2.21"]["section_context"]["text"].endswith("36 Months waiting period")
    assert all(record["source_text"].strip() for record in records)
    assert all(record["source_sha256"] == metadata["source_sha256"] for record in records)


def test_waiting_period_structuring_keeps_conditions_and_exceptions_explicit():
    records, metadata = extract_clauses(ROOT / "data/policies/new_india/policy_wording.pdf")
    by_number = {record["clause_number"]: record for record in records}
    waiting = [structure_clause(r, metadata, by_number) for r in records if r["clause_number"].startswith("6.")]
    assert waiting
    serialized = json.dumps(waiting, ensure_ascii=False).lower()
    assert "duration_text" in serialized
    assert "applies_to_text" in serialized
    assert "section_context_text" in serialized
    assert "numeric_threshold\": null" in serialized
    assert all(item["verification_status"] == "not_human_verified" for item in waiting)
    first_item = next(item for item in waiting if item["clause_number"] == "6.2.1")
    assert first_item["proposed_interpretation"]["waiting_period"]["duration_text"] == ["24 Months"]
    assert any("accident" in value.lower() for value in first_item["proposed_interpretation"]["exceptions"])


def test_jsonl_writer_emits_one_json_object_per_line(tmp_path):
    output = tmp_path / "nested" / "records.jsonl"
    write_jsonl(output, [{"a": 1}, {"b": "हिंदी"}])
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"a": 1}, {"b": "हिंदी"}]
