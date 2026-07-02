"""Model catalog and pricing endpoints.

The catalog merges three sources per provider:

- the built-in pricing table,
- local pricing overrides (``clean-evals-data/pricing.yml``),
- the provider's live model list, fetched by the connectivity probe.

Live-listed models without a known price are selectable; their runs record
zero cost until a price is set. Prices are edited through the override
endpoints; the refresh endpoint proposes updates from machine-readable
feeds and applies nothing on its own.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from clean_evals import model_metadata as metadata_source
from clean_evals import pricing
from clean_evals.capabilities import capabilities
from clean_evals.connectivity import probe_all
from clean_evals.exclusions import excluded_models, set_excluded
from clean_evals.pricing import PROVIDER_ENV_VARS, Price, known_models, lookup, overrides
from clean_evals.pricing_feeds import build_proposals, fetch_feed_prices
from clean_evals.web.schemas import (
    CatalogModelOut,
    ExclusionIn,
    ModelCapabilitiesOut,
    PriceProposalOut,
    PricingApplyIn,
    PricingOverrideIn,
    ProviderOut,
)

router = APIRouter(prefix="/models", tags=["models"])


async def _catalog() -> list[ProviderOut]:
    probes = await probe_all(list(PROVIDER_ENV_VARS))
    override_table = overrides()
    excluded = excluded_models()
    metadata = await metadata_source.model_metadata()
    out: list[ProviderOut] = []
    for provider, env_var in PROVIDER_ENV_VARS.items():
        probe = probes[provider]
        listed = set(probe.models)
        ids = sorted({m for p, m in known_models() if p == provider} | listed)
        models = []
        for model_id in ids:
            price = lookup(provider, model_id)
            meta = metadata_source.lookup(metadata, provider, model_id)
            caps = (meta.capabilities(provider) if meta else None) or capabilities(
                provider, model_id
            )
            models.append(
                CatalogModelOut(
                    id=model_id,
                    input_per_mtok=price.input_per_mtok if price else None,
                    output_per_mtok=price.output_per_mtok if price else None,
                    overridden=(provider, model_id) in override_table,
                    listed=model_id in listed,
                    excluded=(provider, model_id) in excluded,
                    description=meta.description if meta else None,
                    context_length=meta.context_length if meta else None,
                    capabilities=ModelCapabilitiesOut(
                        supports_temperature=caps.supports_temperature,
                        supports_seed=caps.supports_seed,
                        reasoning_efforts=list(caps.reasoning_efforts),
                        supports_max_output_tokens=caps.supports_max_output_tokens,
                    ),
                )
            )
        out.append(
            ProviderOut(
                provider=provider,
                env_var=env_var,
                status=probe.status,
                connected=probe.status == "connected",
                models=models,
            )
        )
    return out


@router.get("", response_model=list[ProviderOut])
async def list_models() -> list[ProviderOut]:
    return await _catalog()


@router.put("/pricing", response_model=list[ProviderOut])
async def set_price(payload: PricingOverrideIn) -> list[ProviderOut]:
    if payload.provider not in PROVIDER_ENV_VARS:
        raise HTTPException(status_code=400, detail=f"unknown provider {payload.provider!r}")
    pricing.set_override(
        payload.provider,
        payload.model,
        input_per_mtok=payload.input_per_mtok,
        output_per_mtok=payload.output_per_mtok,
    )
    return await _catalog()


@router.delete("/pricing", response_model=list[ProviderOut])
async def remove_price(provider: str, model: str) -> list[ProviderOut]:
    if not pricing.remove_override(provider, model):
        raise HTTPException(status_code=404, detail="no override for this model")
    return await _catalog()


@router.put("/excluded", response_model=list[ProviderOut])
async def set_excluded_model(payload: ExclusionIn) -> list[ProviderOut]:
    """Exclude or include a model. Excluded models are hidden from pickers."""
    if payload.provider not in PROVIDER_ENV_VARS:
        raise HTTPException(status_code=400, detail=f"unknown provider {payload.provider!r}")
    set_excluded(payload.provider, payload.model, payload.excluded)
    return await _catalog()


@router.post("/pricing/refresh", response_model=list[PriceProposalOut])
async def refresh_prices() -> list[PriceProposalOut]:
    """Fetch the pricing feeds and propose updates. Applies nothing."""
    try:
        feed = await fetch_feed_prices()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"pricing feeds unreachable: {exc}") from exc
    probes = await probe_all(list(PROVIDER_ENV_VARS))
    catalog_models = sorted(
        (set(known_models()) | {(p, m) for p, probe in probes.items() for m in probe.models})
        - set(excluded_models())
    )
    return [
        PriceProposalOut(
            provider=p.provider,
            model=p.model,
            current_input=p.current_input,
            current_output=p.current_output,
            new_input=p.new_input,
            new_output=p.new_output,
            source=p.source,
        )
        for p in build_proposals(catalog_models, feed)
    ]


@router.post("/pricing/apply", response_model=list[ProviderOut])
async def apply_prices(payload: PricingApplyIn) -> list[ProviderOut]:
    """Write the given prices into the local overrides."""
    entries = {
        (item.provider, item.model): Price(
            input_per_mtok=item.input_per_mtok, output_per_mtok=item.output_per_mtok
        )
        for item in payload.items
    }
    pricing.set_overrides(entries)
    return await _catalog()
