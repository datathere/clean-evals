"""Model suggestions: two cheap, two medium, two expensive.

Tiers come from arithmetic — the priced, connected, non-excluded models
are split into thirds by input price. A cheap connected model then picks
two per tier for task fit, given the dataset's system prompt and a sample
case. Reasons are returned with the picks. When no model can be called,
or its answer is unusable, deterministic picks (cheapest, median,
priciest per tier) fill in — the feature always returns a slate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from clean_evals import model_metadata as metadata_source
from clean_evals.connectivity import probe_all
from clean_evals.exclusions import excluded_models
from clean_evals.pricing import PROVIDER_ENV_VARS, infer_provider, known_models, lookup
from clean_evals.protocols import ModelAdapter
from clean_evals.registry import adapters as adapter_registry
from clean_evals.storage.db import CaseRow, DatasetRow

_log = logging.getLogger(__name__)

TIERS = ("cheap", "medium", "expensive")
_PICKS_PER_TIER = 2

_PICKER_SYSTEM = """\
You select evaluation candidates. Given a task and three price tiers of
models, pick the {n} models per tier best suited to the task. Prefer a mix
of providers. Return ONLY a JSON object:
{{"cheap": ["<model id>", ...], "medium": [...], "expensive": [...],
"reasons": {{"<model id>": "<one short sentence>"}}}}
Use only model ids from the lists given."""


@dataclass(frozen=True, slots=True)
class ModelPick:
    model: str
    tier: str
    reason: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    picks: list[ModelPick]
    picked_by: str | None  # model that made the picks; None = deterministic


async def _eligible(provider_names: list[str]) -> list[tuple[str, float]]:
    """(model, input price) for connected, priced, non-excluded models."""
    probes = await probe_all(provider_names)
    excluded = excluded_models()
    out: list[tuple[str, float]] = []
    for provider, probe in probes.items():
        if probe.status != "connected":
            continue
        listed = set(probe.models)
        table = {m for p, m in known_models() if p == provider}
        ids = (listed | {m for m in table if m in listed}) if listed else table
        # Match the picker: when the provider reports a list, offer listed
        # models; otherwise fall back to the table.
        for model in sorted(ids if listed else table):
            if (provider, model) in excluded:
                continue
            price = lookup(provider, model)
            if price is None:
                continue
            out.append((model, price.input_per_mtok))
    return out


def _tiers(models: list[tuple[str, float]]) -> dict[str, list[tuple[str, float]]]:
    ranked = sorted(models, key=lambda m: (m[1], m[0]))
    n = len(ranked)
    third = max(1, n // 3)
    return {
        "cheap": ranked[:third],
        "medium": ranked[third : 2 * third],
        "expensive": ranked[2 * third :],
    }


def _is_variant(a: str, b: str) -> bool:
    """True when one id is a dated or suffixed variant of the other."""
    shorter, longer = sorted((a, b), key=len)
    return longer.startswith(shorter + "-") or shorter == longer


def _price_reason(tier: str, price: float) -> str:
    return f"{tier} tier, ${price:g} per Mtok input"


def _deterministic_picks(tiers: dict[str, list[tuple[str, float]]]) -> list[ModelPick]:
    """Price-ranked picks: no near-duplicate ids, providers varied per tier."""
    picks: list[ModelPick] = []
    for tier in TIERS:
        chosen: list[str] = []
        prices = dict(tiers[tier])
        ranked = [m for m, _ in tiers[tier]]
        for prefer_new_provider in (True, False):
            for model in ranked:
                if len(chosen) >= _PICKS_PER_TIER:
                    break
                if any(_is_variant(model, c) for c in chosen):
                    continue
                if prefer_new_provider and chosen:
                    try:
                        if infer_provider(model) == infer_provider(chosen[0]):
                            continue
                    except ValueError:
                        pass
                chosen.append(model)
        picks.extend(
            ModelPick(model=m, tier=tier, reason=_price_reason(tier, prices[m])) for m in chosen
        )
    return picks


def _task_description(session: Session, dataset_id: int) -> str:
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise ValueError(f"Dataset id={dataset_id} not found")
    case = session.execute(
        select(CaseRow).where(CaseRow.dataset_id == dataset_id).order_by(CaseRow.id).limit(1)
    ).scalar_one_or_none()
    parts = [f"Scorer: {ds.scorer}."]
    if ds.system_prompt:
        parts.append(f"System prompt: {ds.system_prompt}")
    if case is not None:
        parts.append(f"Sample case: {json.dumps(case.input_jsonb, ensure_ascii=False)[:500]}")
    return "\n".join(parts)


async def suggest_models(
    session_factory: sessionmaker[Session],
    dataset_id: int,
    *,
    adapters: dict[str, ModelAdapter] | None = None,
) -> Suggestion:
    """Suggest two models per price tier for a dataset's task.

    Raises:
        ValueError: When the dataset does not exist or no connected
            provider offers priced models.
    """
    with session_factory() as session:
        task = _task_description(session, dataset_id)

    eligible = await _eligible(list(PROVIDER_ENV_VARS))
    if not eligible:
        raise ValueError("no connected provider offers priced models; connect one first")
    tiers = _tiers(eligible)
    fallback = _deterministic_picks(tiers)

    picker_model = min(eligible, key=lambda m: m[1])[0]
    try:
        provider = infer_provider(picker_model)
        adapter = (adapters or {}).get(provider) or adapter_registry.get(provider)()
        metadata = await metadata_source.model_metadata()

        def provider_of(model: str) -> str:
            try:
                return infer_provider(model)
            except ValueError:
                return ""

        def line(model: str, price: float) -> str:
            meta = metadata_source.lookup(metadata, provider_of(model), model)
            summary = f" — {meta.description[:120]}" if meta and meta.description else ""
            return f"{model} (${price}/Mtok input){summary}"

        tier_lines = {
            tier: [line(model, price) for model, price in models] for tier, models in tiers.items()
        }
        response = await adapter.complete(
            prompt=f"TASK:\n{task}\n\nTIERS:\n{json.dumps(tier_lines, indent=2)}",
            model=picker_model,
            temperature=0.0,
            seed=0,
            timeout_s=30.0,
            response_format="json",
            system=_PICKER_SYSTEM.format(n=_PICKS_PER_TIER),
        )
        parsed = response.parsed or {}
        reasons = parsed.get("reasons") or {}
        picks: list[ModelPick] = []
        for tier in TIERS:
            valid_ids = {model for model, _ in tiers[tier]}
            chosen = [m for m in (parsed.get(tier) or []) if isinstance(m, str) and m in valid_ids][
                :_PICKS_PER_TIER
            ]
            for model, _price in tiers[tier]:
                if len(chosen) >= _PICKS_PER_TIER:
                    break
                if model not in chosen:
                    chosen.append(model)
            prices = dict(tiers[tier])
            picks.extend(
                ModelPick(
                    model=m,
                    tier=tier,
                    reason=str(reasons.get(m) or _price_reason(tier, prices[m])),
                )
                for m in chosen
            )
        return Suggestion(picks=picks, picked_by=picker_model)
    except Exception as exc:
        _log.warning("model suggestion call failed (%s); using price-based picks", exc)
        return Suggestion(picks=fallback, picked_by=None)
