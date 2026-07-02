import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ModelPicker } from "@/components/ModelPicker";
import { SuggestModels } from "@/components/SuggestModels";
import { ModelParamsEditor } from "@/components/ModelParamsEditor";
import { cleanParams } from "@/lib/modelParams";
import { api, type ModelParams, type ModelPick } from "@/lib/api";

interface Props {
  /** Fixed dataset. When omitted, a dataset selector is shown. */
  datasetId?: number;
  navigate: (path: string) => void;
}

export function RunLauncher({ datasetId: fixedDatasetId, navigate }: Props) {
  const [selectedDataset, setSelectedDataset] = useState<number | "">("");
  const datasetId = fixedDatasetId ?? (selectedDataset === "" ? undefined : selectedDataset);

  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: api.listDatasets,
    enabled: fixedDatasetId === undefined,
  });
  const dataset = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.getDataset(datasetId as number),
    enabled: datasetId !== undefined,
  });

  const [models, setModels] = useState<string[]>([]);
  const [params, setParams] = useState<Record<string, ModelParams>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [maxCost, setMaxCost] = useState(5.0);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const judge = useQuery({
    queryKey: ["judge", datasetId],
    queryFn: () => api.getJudgeConfig(datasetId as number),
    enabled: datasetId !== undefined && dataset.data?.scorer === "llm_judge",
    retry: false,
  });

  const status = useQuery({
    queryKey: ["inline-run", datasetId],
    queryFn: () => api.inlineRunStatus(datasetId as number),
    enabled: polling && datasetId !== undefined,
    refetchInterval: polling ? 1000 : false,
  });

  const runId = polling && status.data?.status === "done" ? status.data.run_id : null;
  useEffect(() => {
    if (runId) navigate(`/runs/${runId}`);
  }, [runId, navigate]);

  // A restarted server loses in-process runs; polling then reports idle.
  // State is adjusted during render, not in an effect, so the poller stops
  // before it can fire again.
  const runLost = polling && status.data?.status === "idle";
  if (runLost) {
    setPolling(false);
    setError("The run did not complete because the server restarted. Start it again.");
  }

  const start = useMutation({
    mutationFn: () =>
      api.triggerRun(datasetId as number, {
        models,
        max_cost_usd: maxCost,
        temperature: 0.0,
        model_params: cleanParams(params),
      }),
    onSuccess: () => {
      setError(null);
      setPolling(true);
    },
    onError: (e: Error) => setError(e.message),
  });

  const running = polling && status.data?.status === "running";
  const lockedCount = dataset.data?.locked_count ?? 0;

  return (
    <Card className="border-foreground/20">
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Play className="size-4" /> Run eval
          </span>
        }
        subtitle="Score the selected models against the golden dataset"
      />
      <CardBody className="space-y-3">
        {fixedDatasetId === undefined && (
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Dataset</span>
            <select
              value={selectedDataset}
              onChange={(e) =>
                setSelectedDataset(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="h-9 rounded-md border bg-background px-3 text-sm"
            >
              <option value="">Select a dataset…</option>
              {[...new Set(datasets.data?.map((d) => d.name))].map((name) => (
                <optgroup key={name} label={name}>
                  {datasets.data
                    ?.filter((d) => d.name === name)
                    .map((d) => (
                      <option key={d.id} value={d.id} title={d.description ?? undefined}>
                        {d.name} {d.version} ({d.locked_count}/{d.case_count} locked)
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
        )}
        {dataset.data && lockedCount === 0 && (
          <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
            This dataset has no locked golden answers. Scores will be 0. Lock answers in the
            Dataset Builder first.
          </div>
        )}
        {dataset.data?.scorer === "llm_judge" &&
          (judge.data ? (
            <div className="rounded-md border bg-muted/30 p-3 text-xs">
              Judge: <span className="font-medium">{judge.data.judge_model}</span>, calibrated
              standard v{judge.data.version}, kappa{" "}
              {judge.data.agreement.summary.kappa.toFixed(2)}.
            </div>
          ) : (
            <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
              No calibrated judge. Runs use the dataset's default judge and rubric.
            </div>
          ))}
        {datasetId !== undefined && (
          <SuggestModels
            datasetId={datasetId}
            onPicked={(picks: ModelPick[]) => {
              setModels(picks.map((p) => p.model));
              setNotes(Object.fromEntries(picks.map((p) => [p.model, p.reason])));
            }}
          />
        )}
        <ModelPicker selected={models} onChange={setModels} />
        <ModelParamsEditor selected={models} params={params} onChange={setParams} notes={notes} />
        <div className="flex items-end gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Max cost USD</span>
            <input
              type="number"
              step="0.5"
              min={0.1}
              value={maxCost}
              onChange={(e) => setMaxCost(Number(e.target.value))}
              className="h-9 w-28 rounded-md border bg-background px-3 text-sm"
            />
          </label>
          <Button
            onClick={() => start.mutate()}
            disabled={running || start.isPending || models.length === 0 || datasetId === undefined}
          >
            {(running || start.isPending) && <Spinner />}
            {running ? "Running…" : "Run eval"}
          </Button>
        </div>
        {polling && status.data?.status === "error" && (
          <div className="text-xs text-destructive">{status.data.detail ?? "run failed"}</div>
        )}
        {error && <div className="text-xs text-destructive">{error}</div>}
      </CardBody>
    </Card>
  );
}
