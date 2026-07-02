"""Stage 4 — calibrate the LLM judge against human review (docs/docs/flow.md).

The reviewer's 1–5 ratings and written feedback become few-shot examples in
the judge prompt; the judge then re-scores the same candidate outputs and
we measure agreement. Few-shot examples are drawn from *other* cases than
the one being judged (leave-one-case-out), so the agreement number is not
circular.

Agreement is reported three ways:

- ``exact`` — fraction of outputs where judge == human.
- ``within_one`` — fraction within ±1 point.
- ``kappa`` — linear-weighted Cohen's kappa, the standard chance-corrected
  agreement statistic (≥ 0.6 is the commonly used bar).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from clean_evals.pricing import infer_provider
from clean_evals.protocols import ModelAdapter
from clean_evals.registry import adapters as adapter_registry
from clean_evals.storage.db import (
    CandidateOutputRow,
    CaseRow,
    DatasetRow,
    JudgeConfigRow,
    RatingRow,
)

_log = logging.getLogger(__name__)

BASE_RUBRIC = """\
You are a strict evaluation judge. Score the OUTPUT for the given INPUT on a
1-5 scale, applying the same standard as the calibration examples below.
5 = excellent, exactly what the reviewer wants. 1 = unusable.

Return ONLY a JSON object: {"score": <integer 1-5>, "reason": "<one sentence>"}.
"""

_FEW_SHOT_CAP = 6


@dataclass(frozen=True, slots=True)
class RatedOutput:
    """One human-reviewed candidate output, ready for judging."""

    candidate_id: int
    case_pk: int
    case_id: str
    model: str
    case_input: dict[str, Any]
    expected: dict[str, Any] | None
    output: str
    human_rating: int
    feedback: str | None


@dataclass(frozen=True, slots=True)
class AgreementRow:
    case_id: str
    model: str
    human: int
    judge: int
    reason: str


def load_rated_outputs(session: Session, dataset_id: int) -> list[RatedOutput]:
    """Every rated candidate output for a dataset, with its case context."""
    rows = session.execute(
        select(CandidateOutputRow, RatingRow, CaseRow)
        .join(RatingRow, RatingRow.candidate_output_id == CandidateOutputRow.id)
        .join(CaseRow, CaseRow.id == CandidateOutputRow.case_id)
        .where(CaseRow.dataset_id == dataset_id, CandidateOutputRow.status == "ok")
    ).all()
    return [
        RatedOutput(
            candidate_id=cand.id,
            case_pk=case.id,
            case_id=case.case_id_external,
            model=cand.model,
            case_input=dict(case.input_jsonb or {}),
            expected=case.expected_jsonb,
            output=cand.content,
            human_rating=rating.rating,
            feedback=rating.feedback,
        )
        for cand, rating, case in rows
    ]


def few_shot_examples(pool: list[RatedOutput], *, exclude_case_pk: int) -> list[dict[str, Any]]:
    """Calibration examples from other cases, spread across the rating range."""
    eligible = [r for r in pool if r.case_pk != exclude_case_pk]
    # Prefer examples with written feedback, then spread across ratings.
    eligible.sort(key=lambda r: (r.feedback is None, r.human_rating))
    picked: list[RatedOutput] = []
    seen_ratings: set[int] = set()
    for r in eligible:  # one per rating level first — range beats volume
        if r.human_rating not in seen_ratings:
            picked.append(r)
            seen_ratings.add(r.human_rating)
    for r in eligible:
        if len(picked) >= _FEW_SHOT_CAP:
            break
        if r not in picked:
            picked.append(r)
    return [
        {
            "input": r.case_input,
            "output": r.output,
            "rating": r.human_rating,
            "feedback": r.feedback,
        }
        for r in picked[:_FEW_SHOT_CAP]
    ]


def render_rubric(base: str, examples: list[dict[str, Any]]) -> str:
    """Base rubric plus the calibration examples."""
    if not examples:
        return base
    blocks = []
    for i, ex in enumerate(examples, start=1):
        feedback = f'\nReviewer feedback: "{ex["feedback"]}"' if ex.get("feedback") else ""
        blocks.append(
            f"Example {i}:\n"
            f"INPUT: {json.dumps(ex['input'], ensure_ascii=False)}\n"
            f"OUTPUT: {ex['output']}\n"
            f"Reviewer score: {ex['rating']}/5{feedback}"
        )
    return base + "\nCalibration examples:\n\n" + "\n\n".join(blocks)


def agreement_stats(pairs: list[tuple[int, int]]) -> dict[str, float]:
    """Exact %, within ±1 %, and linear-weighted Cohen's kappa for 1-5 pairs."""
    if not pairs:
        return {"n": 0, "exact": 0.0, "within_one": 0.0, "kappa": 0.0}
    n = len(pairs)
    exact = sum(1 for h, j in pairs if h == j) / n
    within = sum(1 for h, j in pairs if abs(h - j) <= 1) / n

    k = 5
    observed = [[0.0] * k for _ in range(k)]
    for h, j in pairs:
        observed[h - 1][j - 1] += 1.0 / n
    row_marginals = [sum(observed[i]) for i in range(k)]
    col_marginals = [sum(observed[i][j] for i in range(k)) for j in range(k)]

    def weight(i: int, j: int) -> float:
        return abs(i - j) / (k - 1)

    disagreement_observed = sum(weight(i, j) * observed[i][j] for i in range(k) for j in range(k))
    disagreement_expected = sum(
        weight(i, j) * row_marginals[i] * col_marginals[j] for i in range(k) for j in range(k)
    )
    kappa = 1.0 - disagreement_observed / disagreement_expected if disagreement_expected else 1.0
    return {"n": n, "exact": exact, "within_one": within, "kappa": kappa}


async def _judge_one(
    adapter: ModelAdapter,
    judge_model: str,
    rubric: str,
    rated: RatedOutput,
    *,
    timeout_s: float,
) -> AgreementRow:
    prompt = (
        f"INPUT:\n{json.dumps(rated.case_input, ensure_ascii=False, indent=2)}\n\n"
        f"OUTPUT:\n{rated.output}\n\n"
        "Return only the JSON object."
    )
    response = await adapter.complete(
        prompt=prompt,
        model=judge_model,
        temperature=0.0,
        seed=0,
        timeout_s=timeout_s,
        response_format="json",
        system=rubric,
    )
    parsed = response.parsed or {}
    try:
        score = int(parsed.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(1, min(5, score)) if score else 1
    return AgreementRow(
        case_id=rated.case_id,
        model=rated.model,
        human=rated.human_rating,
        judge=score,
        reason=str(parsed.get("reason", "")),
    )


async def calibrate(
    session_factory: sessionmaker[Session],
    dataset_id: int,
    *,
    judge_model: str,
    timeout_s: float = 30.0,
    concurrency: int = 4,
    adapters: dict[str, ModelAdapter] | None = None,
) -> JudgeConfigRow:
    """Run one calibration pass and store it as a new judge-config version.

    The stored rubric embeds the full few-shot pool; agreement was measured
    leave-one-case-out so it is not inflated by self-reference.

    Raises:
        ValueError: When the dataset has no rated candidate outputs.
    """
    with session_factory() as session:
        ds = session.get(DatasetRow, dataset_id)
        if ds is None:
            raise ValueError(f"Dataset id={dataset_id} not found")
        pool = load_rated_outputs(session, dataset_id)
    if not pool:
        raise ValueError(
            f"Dataset id={dataset_id} has no rated candidate outputs; rate outputs first"
        )

    provider = infer_provider(judge_model)
    adapter = (adapters or {}).get(provider) or adapter_registry.get(provider)()

    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(rated: RatedOutput) -> AgreementRow:
        rubric = render_rubric(BASE_RUBRIC, few_shot_examples(pool, exclude_case_pk=rated.case_pk))
        async with sem:
            return await _judge_one(adapter, judge_model, rubric, rated, timeout_s=timeout_s)

    rows = await asyncio.gather(*[one(r) for r in pool])
    stats = agreement_stats([(r.human, r.judge) for r in rows])

    full_examples = few_shot_examples(pool, exclude_case_pk=-1)
    stored_rubric = render_rubric(BASE_RUBRIC, full_examples)

    with session_factory() as session:
        version = (
            max(
                (
                    jc.version
                    for jc in session.execute(
                        select(JudgeConfigRow).where(JudgeConfigRow.dataset_id == dataset_id)
                    ).scalars()
                ),
                default=0,
            )
            + 1
        )
        config = JudgeConfigRow(
            dataset_id=dataset_id,
            version=version,
            judge_model=judge_model,
            rubric=stored_rubric,
            few_shot_jsonb=full_examples,
            agreement_jsonb={
                "summary": stats,
                "rows": [
                    {
                        "case_id": r.case_id,
                        "model": r.model,
                        "human": r.human,
                        "judge": r.judge,
                        "reason": r.reason,
                    }
                    for r in rows
                ],
            },
        )
        session.add(config)
        # The calibrated standard becomes the dataset's scorer config, so
        # stage 5 runs are scored by what the reviewer signed off on.
        ds = session.get(DatasetRow, dataset_id)
        if ds is not None and ds.scorer == "llm_judge":
            ds.scorer_config = {
                **(ds.scorer_config or {}),
                "judge_model": judge_model,
                "rubric": stored_rubric,
                # The calibrated rubric scores 1-5 to match human ratings.
                "judge_scale": 5,
                "judge_scale_min": 1,
            }
        session.commit()
        session.refresh(config)
        # Detach with attributes loaded so callers can read them post-session.
        session.expunge(config)
        return config
