# ClaimSense synthetic-data starter

This is a starter data pack for the ClaimSense capstone. All people, policy IDs,
claim IDs, hospitals, bills, and tariff ranges in the claims/tariff dataset are
synthetic. They are for software development and evaluation only, not real
insurance decisions or medical pricing.

## Layout
- `data/policies/new_india/`: includes the six PDFs uploaded by the user: policy wording, Customer Information Sheet (CIS), prospectus, proposal form, excluded-items list, and claim form. See `manifest.json` for filenames, hashes, and version notes.
- `data/processed/policy_clauses.jsonl`: placeholder schema/example; replace with clauses extracted and reviewed from the exact policy version.
- `data/tariffs/synthetic_tariffs.csv`: 30 procedures × 3 city tiers = 90 synthetic reference ranges.
- `data/claims/development/claims.jsonl`: 20 development claims.
- `data/claims/development/gold_worksheets.jsonl`: reference outcomes for development claims.
- `data/claims/heldout/claims.jsonl`: 60 held-out claims.
- `data/claims/heldout/gold_worksheets.jsonl`: reference outcomes; keep this outside the agent runtime.
- `data/redteam/attacks.jsonl`: example adversarial test cases.
- `src/`, `tests/`, `eval/`: starter project directories.

## Important caveats
1. The claims are synthetic test fixtures, not actual policy interpretations.
2. Gold outcomes use a simplified, explicitly declared demo ruleset. Before testing against a real insurer policy, replace/review the rule configuration and gold labels against the exact official policy wording, policy schedule, and applicable endorsements.
3. Room-rent proportional deductions, waiting periods, sub-limits, co-pay, admissibility, and non-payable item treatment vary by policy/version. Do not assume the example rules are universally valid.
4. Tariff ranges are Option A: synthetic reference ranges, not official hospital tariffs, insurer-negotiated rates, or reimbursement limits. Use only to flag unusual prices for human review; do not use them to decide coverage.
5. The held-out gold file should be access-controlled and never passed to the ClaimSense agent as context.
6. Money is represented in integer INR rupees in this starter dataset. In production, use integer paise or `Decimal` and document rounding rules.
7. Do not use real patient records or personal health information in the capstone dataset.

## Demo ruleset used to generate gold labels
- Policy period: 2026-01-01 through 2026-12-31.
- Initial waiting period: 30 days from policy start; claims admitted before the 30-day period has elapsed are marked `needs_review`/not admissible in the demo fixtures.
- Pre-existing disease waiting period: 36 months; fixtures that explicitly identify a pre-existing condition inside this period are not payable under the simplified demo rules.
- Room cap: min(2% of sum insured, ₹5,000/day).
- ICU cap: min(5% of sum insured, ₹10,000/day).
- Cataract sub-limit: min(25% of sum insured, ₹40,000 per eye).
- Co-pay: 5% of otherwise payable amount.
- `non_payable` line items are excluded from payable amount.
- When room charges exceed the daily room cap, eligible linked room-linked charges are reduced by the same ratio in this simplified demo. The gold worksheet records a proportional-cut factor where relevant.
- These are illustrative rules based on the starter project brief and must be verified against the exact policy document before real use.

## Files
- `manifest.json` records the synthetic dataset version and generation date.
- `data/processed/policy_clauses.jsonl` is a schema example only, not an authoritative clause extract.


## Uploaded New India Assurance documents
The following uploaded PDFs are included under `data/policies/new_india/`:
- `policy_wording.pdf` — POLICY CLAUSES Arogya Sanjeevani
- `customer_information_sheet.pdf` — Customer Information Sheet
- `prospectus.pdf` — Prospectus
- `proposal_form.pdf` — Proposal form
- `excluded_items.pdf` — List of excluded items
- `claim_form.pdf` — Claim Form

The uploaded proposal form shows UIN `NIAHLIP25044V022425`. Treat this as an observed identifier, not proof that every document is the same version. Before encoding rules, cross-check the UIN, effective/version dates and exact wording across the policy wording, CIS, prospectus and excluded-items list. Proposal and claim forms are workflow templates, not coverage contracts.

The workflow diagram:

![ClaimSense workflow diagram](./mermaid-diagram.png)

## Extract and structure policy clauses

Use Python 3.9 or newer. Install the PDF reader dependency and run the pipeline
from the repository root:

```bash
python3 -m pip install -r requirements-dev.txt
python3 src/ingestion/extract_policy_clauses.py
```

The defaults read `data/policies/new_india/policy_wording.pdf` and write
`data/processed/extracted_clauses_raw.jsonl` and
`data/processed/policy_clauses_structured.jsonl`. Alternate paths can be supplied
with `--pdf`, `--raw-output`, and `--structured-output`. Run the unit tests with:

```bash
python3 -m pytest
```

### Output fields

Both outputs are JSONL files: each line is one clause record. The raw file
preserves extracted text and clause structure; the structured file adds
heuristic labels and source-linked interpretation fields.

#### `extracted_clauses_raw.jsonl`

- `clause_id`: stable record identifier formed from the product name and clause
  number.
- `clause_number`: normalized clause number, including generated hierarchy for
  numbered list items (for example, `6.2.1`).
- `displayed_number`: number printed beside the item in the PDF. This can differ
  from the normalized clause number for items whose hierarchy was inferred.
- `parent_clause_number`: normalized parent clause number, or `null` for a
  top-level clause.
- `hierarchy`: the clause number split into its levels, as an array of strings.
- `title`: extracted clause heading or item text following its number.
- `page_number`: page where the clause starts (page numbering starts at 1).
- `page_numbers`: ordered list of pages containing text assigned to the clause.
- `source_document`: source PDF filename.
- `source_sha256`: SHA-256 digest of the source PDF, to identify the exact file
  used for extraction.
- `section_context`: nearby heading context retained for numbered list items,
  such as a waiting-period heading; it contains `text` and `page_number`, or is
  `null` when no such context was captured.
- `source_text`: combined extracted text assigned to this clause.
- `source_spans`: ordered text fragments with their `page_number`, preserving
  the page associated with each extracted line.

#### `policy_clauses_structured.jsonl`

- `record_id`: same clause identifier as the raw record's `clause_id`.
- `clause_number`, `displayed_number`, `parent_clause_number`, `hierarchy`, and
  `title`: the corresponding clause identification and hierarchy fields from
  the raw record.
- `source`: source metadata grouped together: `document` (PDF filename),
  `sha256` (source PDF digest), `page_number` (start page), `page_numbers`
  (pages containing the clause), `insurer`, `product`, and
  `uin_observed_in_policy_pdf` (the UIN observed in that PDF, not proof that
  other documents share the same version).
- `source_text`: extracted clause text, retained so the structured record can
  be checked against its source.
- `proposed_interpretation`: heuristic draft fields:
  - `topic`: broad subject label, such as `waiting_period`, `exclusion`, or
    `room_rent_limit`.
  - `rule_type`: broad category for the topic, such as
    `eligibility_or_timing` or `benefit_limit`.
  - `applicability_conditions`: source-text matches that may describe when a
    clause applies.
  - `exceptions`: source-text matches that may describe exceptions.
  - `parent_context`: parent clause number, its source text, and page numbers,
    or `null` if no parent record is available.
  - `waiting_period`: present for clauses classified as waiting periods. It
    includes `duration_text` found in the clause or section heading,
    `parent_duration_mentions` found in the parent clause,
    `period_start_text` (currently `null`), `applies_to_text` and
    `raw_waiting_period_spans` (matched waiting-period text),
    `section_context_text` and `section_context_page_number` (captured nearby
    heading, when available), and an `interpretation_note` describing the
    limits of the extraction.
  - `numeric_threshold`: currently `null`; the pipeline deliberately does not
    infer a single numeric threshold from the extracted phrases.
  - `interpretation_method`: identifies the approach as
    `keyword_and_span_heuristics`.
  - `review_flags`: reminders to verify the wording and policy version/schedule.
- `verification_status`: currently `not_human_verified`; the structured output
  is a draft for review, not an authoritative coverage determination.

The structured records are proposed interpretations produced by keyword and
source-span heuristics. Waiting-period duration, applicability, start point and
exceptions remain separate text fields; the pipeline does not turn them into a
single threshold. Every record is marked `not_human_verified`. A qualified
reviewer must compare the extracted text, page references, policy version,
schedule and endorsements before any clause is used for claim decisions.


## Build the policy knowledge base

The retrieval knowledge base is built directly from the two source PDFs:
- `data/policies/new_india/policy_wording.pdf` — primary policy wording.
- `data/policies/new_india/excluded_items.pdf` — supporting excluded-items reference; it must be checked against the primary policy wording.

`data/processed/policy_clauses_structured.jsonl` is a separate review/audit artifact generated by the clause-extraction workflow. It is **not** an input to knowledge-base creation. The builder imports the numbered-clause extraction functions and runs them in memory against the policy PDF, avoiding a file-level dependency on a derived copy of the same source.

Build from the repository root:

```bash
python3 -m pip install -r requirements-dev.txt
python3 src/ingestion/build_policy_knowledge_base.py
python3 -m pytest
```

Optional CLI arguments include `--policy-pdf`, `--excluded-items-pdf`, `--output`, `--manifest`, `--chunk-size`, and `--overlap`. There is intentionally no structured-JSONL input argument.

Outputs:
- `data/knowledge_base/policy_knowledge_base.jsonl`: one retrieval chunk per line, with stable `chunk_id`, embedding-facing `text`, chunk `source_text`, source document/hash/page metadata, clause hierarchy and parent context, proposed heuristic labels, explicit conditions/exceptions/waiting-period fields, and verification/authority warnings.
- `data/knowledge_base/manifest.json`: input PDF hashes and page counts, in-memory parser/version, chunk counts, chunking settings, and known limitations.

Default chunking is 1,800 characters with 250 characters of overlap, using paragraph/sentence/whitespace boundaries. Numbered clause items include their section/parent context in the embedding-facing text where available, so concise list items do not lose context. The source chunk is stored separately.

The builder verifies the source PDF hashes used by the in-memory extraction, preserves page references, and indexes the excluded-items PDF as the separate `excluded_items_reference` record type. Pages with no extractable text are flagged; if overall extracted text is extremely low, the build stops and calls for OCR/layout review.

**Important:** This is a retrieval corpus, not an embedding index or verified policy rules engine. All records remain `not_human_verified`; topic, rule-type, condition, and exception labels are heuristic suggestions. Waiting-period interactions, portability, accident exceptions, sum-insured enhancement, and other qualifications must be checked against the actual wording, policy schedule, endorsements, coverage dates, and applicable version. Do not approve or deny a claim from retrieval output alone.

For the next step, embed the `text` field into Chroma or FAISS and store the remaining fields as metadata. Return chunk IDs and page references with retrieval results so a reviewer can inspect source evidence. Do not pass held-out gold worksheets into the retrieval corpus.
