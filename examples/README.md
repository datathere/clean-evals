# Examples

## Input files

Upload these on the **Dataset Builder** page or with `clean-evals build`.

| File | Task | Suggested scorer | System prompt to paste |
| ---- | ---- | ---------------- | ---------------------- |
| [`ticket_triage/inputs.csv`](ticket_triage/inputs.csv) (also [JSONL](ticket_triage/inputs.jsonl)) | Support ticket categorization | `exact_match` | "You are a support agent. Classify the ticket as billing, account, or technical. Reply with the category only." |
| [`email_rewrite/inputs.csv`](email_rewrite/inputs.csv) | Rewrite blunt drafts professionally | `llm_judge` | "Rewrite the draft as a professional, warm customer-facing email. Keep it under 120 words. Preserve all facts." |

Inputs only. Expected answers are chosen during review.

## Complete datasets

Three runnable datasets with golden answers already locked. CI exercises
them on pull requests.

| Dataset                                | Scorer             | Cases | Description                     |
| -------------------------------------- | ------------------ | ----: | ------------------------------- |
| [`sentiment/`](sentiment/)             | `exact_match`      |    12 | Three-class sentiment labels    |
| [`json_extraction/`](json_extraction/) | `json_field_match` |    10 | Pull structured fields from text |
| [`summary_quality/`](summary_quality/) | `llm_judge`        |     6 | Rubric-graded summaries         |

## Run them

```bash
clean-evals run examples/sentiment/dataset.yml \
  --models claude-3-5-sonnet-20241022,gpt-4o-mini-2024-07-18 \
  --max-cost 0.50

clean-evals run examples/json_extraction/dataset.yml \
  --models claude-3-5-sonnet-20241022,gpt-4o-2024-11-20 \
  --max-cost 1.00

clean-evals run examples/summary_quality/dataset.yml \
  --models claude-3-5-sonnet-20241022,gpt-4o-2024-11-20 \
  --max-cost 2.00
```
