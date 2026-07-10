# Working with production data and PII

clean-evals does **not** auto-scrub PII. Two boundaries accept an optional
scrubber you write for your own data — the protocols below are the whole
contract, and no scrubber implementation is shipped.

You are responsible for verifying your scrubber works for your data.

## The Scrubber protocol (dataset loading)

```python
class Scrubber(Protocol):
    def scrub(self, case: Case) -> Case: ...
```

Called by `Dataset.from_yaml(..., scrubber=...)` once per case after
parsing. Implementations must be pure — same input, same output.

## The TelemetryScrubber protocol (telemetry ingest)

Telemetry is production data by definition — see the
[Telemetry guide](telemetry.md). Envelopes are stored **raw** unless a
telemetry scrubber is configured, and the UI and every ingest response
say so plainly.

```python
class TelemetryScrubber(Protocol):
    def scrub_interaction(
        self, interaction: StructuredInteraction | TranscriptInteraction
    ) -> StructuredInteraction | TranscriptInteraction: ...
```

Register the implementation under the ``clean_evals.telemetry_scrubbers``
entry-point group and name it in ``CLEAN_EVALS_TELEMETRY_SCRUBBER``:

```toml
[project.entry-points."clean_evals.telemetry_scrubbers"]
company = "my_pkg.scrubbers:CompanyTelemetryScrubber"
```

It runs on every envelope *before* anything is persisted. A configured
name that resolves to nothing — or to something that does not satisfy the
protocol — fails ingest loudly rather than silently storing raw data.

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
