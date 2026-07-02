"""First-run sample datasets.

A fresh install gets three samples, seeded once when the datasets table
is empty:

- ``sample-ticket-triage`` — inputs only. Walks the full path: generate
  candidates, review, lock, run.
- ``sample-sentiment`` — golden answers locked. Runnable at once with
  ``exact_match``.
- ``sample-summaries`` — golden answers locked. Runnable at once with
  the LLM judge.

Normal datasets afterwards: editable, versionable, never re-seeded.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from clean_evals.storage.db import CaseRow, DatasetRow

_log = logging.getLogger(__name__)

STARTER_NAME = "sample-ticket-triage"

STARTER_SYSTEM_PROMPT = (
    "You are a support agent. Classify the ticket as billing, account, or "
    "technical. Reply with the category only."
)

STARTER_TICKETS: list[tuple[str, str]] = [
    ("t01", "My card was charged twice for the same order"),
    ("t02", "How do I change the email on my account?"),
    ("t03", "The app crashes when I open settings"),
    ("t04", "I want a refund for my last invoice"),
    ("t05", "I forgot my password and the reset link never arrives"),
    ("t06", "Why did my subscription price go up this month?"),
    ("t07", "The export button gives me a 500 error"),
    ("t08", "Can I move my account to my new company email?"),
    ("t09", "You billed me after I cancelled"),
    ("t10", "Sync stopped working between my phone and laptop"),
    ("t11", "I need an invoice with my VAT number on it"),
    ("t12", "Two-factor codes are not being accepted"),
]

_SENTIMENT_TEMPLATE = (
    "Classify the sentiment of the following text as exactly one of: "
    '"positive", "neutral", or "negative". Reply with only that single word.'
    "\n\nText:\n{prompt}"
)

_SENTIMENT_CASES: list[tuple[str, str, str]] = [
    ("pos_001", "I absolutely love this product. It exceeded every expectation.", "positive"),
    ("pos_002", "Best purchase I've made all year. Highly recommend.", "positive"),
    ("pos_003", "Sturdy build, fast shipping, exactly as described.", "positive"),
    ("pos_004", "The color is gorgeous and it fits perfectly.", "positive"),
    ("neu_001", "It works. Nothing special, nothing wrong.", "neutral"),
    ("neu_002", "Arrived on time. Functions as advertised.", "neutral"),
    ("neu_003", "Average product for the price range.", "neutral"),
    ("neu_004", "Same as the previous version.", "neutral"),
    ("neg_001", "Stopped working after two days. Terrible quality.", "negative"),
    ("neg_002", "Nothing about this lived up to the marketing.", "negative"),
    (
        "neg_003",
        "I expected better at this price. The packaging was destroyed and the "
        "item itself feels cheap.",
        "negative",
    ),
    ("neg_004", "Avoid. Wish I could give zero stars.", "negative"),
]

_SUMMARY_RUBRIC = (
    "Score the response on a 0-10 scale. The response should be:\n"
    "- a single sentence\n"
    "- faithful to the EXPECTED summary's facts\n"
    "- free of hedging or filler\n\n"
    'Return ONLY a JSON object: {"score": <0-10 integer>, "reason": "<one sentence>"}.'
)

_SUMMARY_SYSTEM_PROMPT = "Summarise the text in one sentence."

_SUMMARY_CASES: list[tuple[str, str, str]] = [
    (
        "sum_001",
        "Photosynthesis is the process by which green plants, algae, and "
        "some bacteria convert light energy into chemical energy. Inside "
        "chloroplasts, the pigment chlorophyll absorbs sunlight and drives a "
        "chain of reactions that split water molecules and fix carbon "
        "dioxide from the air. The immediate products are glucose, which "
        "the organism uses for growth and energy storage, and oxygen, which "
        "is released as a by-product. The reaction chain runs in two "
        "stages: the light-dependent reactions, which capture energy, and "
        "the Calvin cycle, which builds sugars. Nearly all life on Earth "
        "depends on this process, either directly as a food source or "
        "indirectly through the oxygen it releases. Scientists estimate "
        "that photosynthetic organisms produce hundreds of billions of "
        "tonnes of oxygen a year.",
        "Photosynthesis is the two-stage process by which plants, algae, "
        "and some bacteria use sunlight to turn water and carbon dioxide "
        "into glucose and oxygen, sustaining nearly all life on Earth.",
    ),
    (
        "sum_002",
        "The James Webb Space Telescope launched on 25 December 2021 after "
        "more than two decades of development and repeated delays. With a "
        "6.5-metre segmented mirror, it is the largest telescope ever sent "
        "to space, dwarfing Hubble's 2.4-metre mirror. It observes "
        "primarily in the infrared, which lets it see through dust clouds "
        "and detect light from the earliest galaxies, stretched into longer "
        "wavelengths by the expansion of the universe. To keep its "
        "instruments cold enough for infrared work, it carries a tennis-"
        "court-sized sunshield and orbits the Sun about 1.5 million "
        "kilometres from Earth. In its first years of operation it has "
        "imaged galaxies from less than 400 million years after the Big "
        "Bang and analysed the atmospheres of planets around other stars.",
        "The James Webb Space Telescope, launched in December 2021 with a "
        "6.5-metre mirror, observes the infrared universe from 1.5 million "
        "kilometres away and has captured the earliest galaxies ever seen.",
    ),
    (
        "sum_003",
        "Bitcoin was introduced in 2009 by a person or group writing under "
        "the name Satoshi Nakamoto, whose identity remains unknown. It is a "
        "peer-to-peer digital currency that operates without a central "
        "bank: transactions are verified by a network of computers and "
        "recorded on a public ledger called the blockchain. New bitcoins "
        "are created through mining, a process in which computers compete "
        "to solve cryptographic puzzles, and the total supply is capped at "
        "21 million coins. The currency's price has swung dramatically over "
        "its history, from fractions of a cent to tens of thousands of "
        "dollars. Supporters see it as a hedge against inflation and a "
        "route to financial access; critics point to its energy "
        "consumption, volatility, and use in crime.",
        "Bitcoin, launched in 2009 by the pseudonymous Satoshi Nakamoto, is "
        "a peer-to-peer digital currency with a 21-million-coin cap, "
        "recorded on a public blockchain and mined by solving "
        "cryptographic puzzles.",
    ),
    (
        "sum_004",
        "The Great Pacific Garbage Patch is a vast accumulation of marine "
        "debris floating between Hawaii and California, held in place by "
        "the circular currents of the North Pacific Gyre. Estimates put its "
        "surface area at around 1.6 million square kilometres, roughly "
        "twice the size of Texas, though most of the debris floats below "
        "the surface and is invisible from above. The patch is dominated "
        "not by large objects but by microplastics, tiny fragments produced "
        "as sunlight and waves break down bottles, packaging, and fishing "
        "gear. Discarded nets make up a large share of the mass and "
        "continue to trap fish, turtles, and seabirds for years. Because "
        "the debris sits in international waters, no single country is "
        "responsible for cleaning it up, and removal efforts by non-profit "
        "groups have collected only a small fraction of the total.",
        "The Great Pacific Garbage Patch is a Texas-doubling expanse of "
        "mostly microplastic debris trapped by North Pacific currents, "
        "which no country is responsible for cleaning up.",
    ),
    (
        "sum_005",
        "TypeScript is a programming language developed by Microsoft and "
        "released in 2012 as a superset of JavaScript. It adds static "
        "typing to JavaScript, letting developers declare the shapes of "
        "their data so that mistakes are caught at compile time rather "
        "than in production. TypeScript code compiles to plain JavaScript "
        "and runs anywhere JavaScript runs, from browsers to servers. The "
        "type system is structural and optional, so teams can adopt it "
        "gradually in an existing codebase. It has become the default "
        "choice for large web applications, with frameworks such as "
        "Angular written in it and editors like VS Code built on it. "
        "Surveys of developers regularly rank it among the most used and "
        "most loved languages.",
        "TypeScript, Microsoft's 2012 superset of JavaScript, adds "
        "optional static typing that catches errors at compile time and "
        "has become the default for large web applications.",
    ),
    (
        "sum_006",
        "Antibiotic resistance occurs when bacteria evolve to survive the "
        "drugs designed to kill them. Resistance arises through natural "
        "selection: when an antibiotic wipes out susceptible bacteria, the "
        "rare mutants that survive multiply and pass on their defences, "
        "and can even share resistance genes with other species. The "
        "problem is accelerated by overuse and misuse of antibiotics in "
        "medicine and agriculture, from unfinished prescriptions to "
        "routine dosing of livestock. Infections that were once trivial "
        "to treat, such as some strains of tuberculosis and gonorrhoea, "
        "now resist multiple drugs. The World Health Organization ranks "
        "antimicrobial resistance among the biggest threats to global "
        "health and estimates that resistant infections already contribute "
        "to more than a million deaths a year, while the pipeline of new "
        "antibiotics remains thin.",
        "Antibiotic resistance, driven by natural selection and "
        "accelerated by overuse in medicine and farming, lets bacteria "
        "survive once-effective drugs and now contributes to over a "
        "million deaths a year.",
    ),
]


def _add_dataset(
    session: Session,
    *,
    name: str,
    description: str,
    scorer: str,
    scorer_config: dict[str, Any],
    request_shape: str = "raw",
    system_prompt: str | None = None,
    cases: list[tuple[str, dict[str, Any], dict[str, Any] | None, bool]],
) -> int:
    ds = DatasetRow(
        name=name,
        version="v1",
        description=description,
        scorer=scorer,
        scorer_config=scorer_config,
        request_shape=request_shape,
        system_prompt=system_prompt,
    )
    session.add(ds)
    session.flush()
    for external_id, case_input, expected, locked in cases:
        session.add(
            CaseRow(
                dataset_id=ds.id,
                case_id_external=external_id,
                input_jsonb=case_input,
                expected_jsonb=expected,
                tags_jsonb=[],
                locked=locked,
                metadata_jsonb={},
            )
        )
    return ds.id


def seed_starter_dataset(session: Session) -> int | None:
    """Insert the sample datasets when no datasets exist.

    Returns the ticket-triage dataset id, or ``None`` when any dataset is
    already present — this only ever fires on a pristine install.
    """
    existing = session.execute(select(DatasetRow.id).limit(1)).first()
    if existing is not None:
        return None

    triage_id = _add_dataset(
        session,
        name=STARTER_NAME,
        description="Support tickets without expected answers, for building a golden dataset from model outputs.",
        scorer="exact_match",
        scorer_config={},
        request_shape="templated",
        system_prompt=STARTER_SYSTEM_PROMPT,
        cases=[(cid, {"ticket": text}, None, False) for cid, text in STARTER_TICKETS],
    )
    _add_dataset(
        session,
        name="sample-sentiment",
        description="Product reviews with locked sentiment labels, ready for eval runs.",
        scorer="exact_match",
        scorer_config={"field": "label", "prompt_template": _SENTIMENT_TEMPLATE},
        cases=[
            (cid, {"prompt": text}, {"label": label}, True) for cid, text, label in _SENTIMENT_CASES
        ],
    )
    _add_dataset(
        session,
        name="sample-summaries",
        description="Paragraphs paired with one-sentence reference summaries, scored by an LLM judge.",
        scorer="llm_judge",
        scorer_config={
            "judge_model": "claude-haiku-4-5-20251001",
            "pass_threshold": 0.7,
            "rubric": _SUMMARY_RUBRIC,
        },
        request_shape="templated",
        system_prompt=_SUMMARY_SYSTEM_PROMPT,
        cases=[
            (cid, {"text": text}, {"summary": summary}, True)
            for cid, text, summary in _SUMMARY_CASES
        ],
    )
    session.commit()
    _log.info("Seeded sample datasets (triage id=%s)", triage_id)
    return triage_id
