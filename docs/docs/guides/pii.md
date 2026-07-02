# Working with production data and PII

clean-evals does **not** auto-scrub PII. The dataset loader supports an
optional `Scrubber` you write for your own data — the protocol below is
the whole contract, and no scrubber implementation is shipped.

You are responsible for verifying your scrubber works for your data.

## The Scrubber protocol

```python
class Scrubber(Protocol):
    def scrub(self, case: Case) -> Case: ...
```

Called by `Dataset.from_yaml(..., scrubber=...)` once per case after
parsing. Implementations must be pure — same input, same output.

## Why no auto-scrub

Auto-scrubbing creates false safety. A regex that matches "email-shaped"
strings will miss a hand-rolled customer-id. A heuristic that catches "SSN-shaped"
numbers will scrub a six-digit confirmation code. The wrong scrubber on
production data is more dangerous than no scrubber at all.

clean-evals' position: **scrubbing is the dataset loader's responsibility,
not clean-evals' core**. The contract is small and explicit:

```python
from clean_evals import Dataset, Scrubber

class CompanyScrubber:
    def scrub(self, case):
        # ... your auditable logic here ...
        return case

ds = Dataset.from_yaml("path.yml", scrubber=CompanyScrubber())
```

## Datasets are safe to commit (after scrubbing)

YAML is a static document. No env-var interpolation, no Jinja, no string
templating. If the file is in your repo, what's in it is what was meant to
be in it.
