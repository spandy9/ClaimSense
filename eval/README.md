# Evaluation notes
- Use development claims for prompt/tool iteration.
- Keep `data/claims/heldout/gold_worksheets.jsonl` inaccessible to agent runtime.
- Compare line-level amount, claim-level settlement, clause grounding, arithmetic, duplicate detection, and human-review routing.
- Freeze code, model, prompt, policy version, and playbook before held-out runs.
- Report rupee absolute error, exact settlement match rate, line-item match rate, false-negative safety flags, latency, and cost.
