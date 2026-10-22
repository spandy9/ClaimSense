import csv, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
def test_claim_counts():
    assert len(read_jsonl(ROOT/'data/claims/development/claims.jsonl')) == 20
    assert len(read_jsonl(ROOT/'data/claims/heldout/claims.jsonl')) == 60
def test_tariff_grid():
    with (ROOT/'data/tariffs/synthetic_tariffs.csv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 90
    assert len({r['procedure_code'] for r in rows}) == 30
    assert {r['city_tier'] for r in rows} == {'tier_1','tier_2','tier_3'}
