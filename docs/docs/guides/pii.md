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

## Why there is no auto-scrub

Generic scrubbing rules produce unreliable results: a regex for
email-shaped strings misses a custom customer-id format, and a heuristic
for SSN-shaped numbers scrubs six-digit confirmation codes. Correct
scrubbing rules depend on your data, so clean-evals requires you to
provide them.

Scrubbing is implemented at the dataset-loading boundary through one
explicit contract:

```python
from clean_evals import Dataset, Scrubber

class CompanyScrubber:
    def scrub(self, case):
        # ... your auditable logic here ...
        return case

ds = Dataset.from_yaml("path.yml", scrubber=CompanyScrubber())
```

## Committing scrubbed datasets

Dataset YAML is a static document with no env-var interpolation and no
template engine. The file contents are exactly what the runner sends, so
a scrubbed dataset can be reviewed and committed like any other file.
