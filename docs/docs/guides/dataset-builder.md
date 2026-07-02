# Dataset Builder

The hardest part of any eval project is building the golden dataset.
clean-evals treats this as a first-class flow.

## The flow

1. **Bring inputs.** Upload a CSV / JSON / JSONL / YAML file of input
   cases — no expected outputs required.
2. **Run candidates.** clean-evals runs the inputs through the candidate
   models in parallel. Cost ceiling enforced.
3. **Review side-by-side.** UI shows a grid: input on the left, model
   output as a column.
4. **Pick or edit.** Select the best output, or edit one inline to fix
   it.
5. **Lock.** Save → input + final output becomes a `Case` with `expected`
   set and `locked = True`.

## Optimistic concurrency

Multiple users editing the same dataset is supported. A `Case` row
carries a `rev` counter; the second writer to update sees a `409` and
re-fetches. No lost updates.

## Locking semantics

A locked case is immutable. Editing a locked case is treated as a
dataset-version bump (`v1` → `v2`); the old version stays addressable so
historical runs remain comparable.

Tagging a version locks the whole dataset.

## CLI shortcut

```bash
clean-evals build inputs.csv --name my_eval --version v1
```

Seeds an in-progress dataset row, then opens the Builder at
`http://localhost:8080/builder/<id>` so you can pick / edit / lock.
