# Source layout
Implement modules in this order:
1. `calculators/`: deterministic money math and unit tests.
2. `ingestion/`: extract documents and preserve page/source spans.
3. `retrieval/`: clause indexing and retrieval.
4. `tools/`: policy, calculator, tariff, claims DB tool contracts.
5. `agents/`: extraction, coverage, fraud, critic, settlement draft.
6. `graph.py`: LangGraph orchestration, approval interrupt and resume.
