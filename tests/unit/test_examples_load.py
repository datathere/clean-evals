"""Sanity check that the bundled examples load without error.

Used both as a unit test and as a CI smoke check that authors haven't broken
the example schema while editing the public Pydantic models.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clean_evals.models import Dataset

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize(
    "name",
    ["sentiment", "json_extraction", "summary_quality"],
)
def test_example_dataset_loads(name: str) -> None:
    yml = EXAMPLES / name / "dataset.yml"
    ds = Dataset.from_yaml(yml)
    assert ds.cases, f"{name}: empty cases list"
    assert ds.scorer
