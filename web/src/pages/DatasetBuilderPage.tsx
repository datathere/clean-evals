import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Copy,
  Download,
  Eye,
  FileUp,
  Lock,
  LockOpen,
  Play,
  Scale,
  Star,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { ModelPicker } from "@/components/ModelPicker";
import { RunLauncher } from "@/components/RunLauncher";
import { DatasetSettings } from "@/components/DatasetSettings";
import { SuggestModels } from "@/components/SuggestModels";
import { ModelParamsEditor } from "@/components/ModelParamsEditor";
import { cleanParams } from "@/lib/modelParams";
import {
  api,
  type Candidate,
  type Case,
  type GenerationStatus,
  type ModelParams,
  type ModelPick,
} from "@/lib/api";
import { cn, formatUsd } from "@/lib/utils";

interface Props {
  datasetId?: number;
  navigate: (path: string) => void;
}

export function DatasetBuilderPage({ datasetId, navigate }: Props) {
  if (datasetId === undefined) {
    return <UploadWizard navigate={navigate} />;
  }
  return <Workspace datasetId={datasetId} navigate={navigate} />;
}

// ---------------------------------------------------------------------------
// Stage 1 — upload wizard
// ---------------------------------------------------------------------------

const SCORERS = [
  { value: "exact_match", label: "exact_match: output must equal the expected answer" },
  { value: "json_field_match", label: "json_field_match: one JSON field must match" },
  { value: "llm_judge", label: "llm_judge: a judge model grades open-ended output" },
];

const TEMPLATE_CSV = `id,ticket
ticket_001,"My card was charged twice for the same order"
ticket_002,"How do I change the email on my account?"
ticket_003,"The app crashes when I open settings"
`;

function downloadTemplate() {
  const blob = new Blob([TEMPLATE_CSV], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "clean-evals-template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function UploadWizard({ navigate }: { navigate: (path: string) => void }) {
  const [shape, setShape] = useState<"raw" | "templated">("templated");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [sharedContext, setSharedContext] = useState("");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("v1");
  const [scorer, setScorer] = useState("exact_match");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Pick a file first");
      if (!name.trim()) throw new Error("Name is required");
      if (shape === "templated" && !systemPrompt.trim())
        throw new Error("System prompt is required for this shape");
      return api.uploadInputs(name, version, scorer, file, {
        request_shape: shape,
        system_prompt: systemPrompt.trim() || undefined,
        shared_context: sharedContext.trim() || undefined,
      });
    },
    onSuccess: ({ dataset_id }) => navigate(`/builder/${dataset_id}`),
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">New dataset</h1>

      <Card>
        <CardHeader title="How does your app talk to the model?" />
        <CardBody className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ShapeCard
            active={shape === "templated"}
            onClick={() => setShape("templated")}
            title="Same setup, different data"
            body="The system prompt stays fixed. Upload the data that varies."
          />
          <ShapeCard
            active={shape === "raw"}
            onClick={() => setShape("raw")}
            title="Complete requests"
            body="Your code builds the full request. Upload finished requests, one per row. Sent unchanged."
          />
        </CardBody>
      </Card>

      {shape === "templated" && (
        <Card>
          <CardHeader title="Shared setup" />
          <CardBody className="space-y-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                System prompt
              </span>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="You are a support agent for Acme. Classify the ticket as billing, fraud, or technical. Reply with the category only."
                className="min-h-24 rounded-md border bg-background p-3 text-sm"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                Context (optional). Add a `context` column to vary it per case.
              </span>
              <textarea
                value={sharedContext}
                onChange={(e) => setSharedContext(e.target.value)}
                placeholder="Refund policy: refunds within 30 days…"
                className="min-h-20 rounded-md border bg-background p-3 text-sm"
              />
            </label>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <FileUp className="size-4" />
              {shape === "templated" ? "Variables (one row per case)" : "Requests (one per row)"}
            </span>
          }
        />
        <CardBody className="space-y-4">
          <div className="rounded-md border bg-muted/30 p-4 text-sm space-y-3">
            <pre className="text-xs bg-background border rounded-md p-3 overflow-auto">
              {shape === "templated"
                ? 'id,ticket\nticket_001,"My card was charged twice for the same order"\nticket_002,"How do I change the email on my account?"'
                : 'id,prompt\nreq_001,"<the full request your app sent>"\nreq_002,"<another full request>"'}
            </pre>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                CSV, JSON, JSONL, or YAML. <span className="font-medium">id</span> optional.
                Start with 10 to 50 cases.
              </span>
              <Button size="sm" variant="outline" onClick={downloadTemplate}>
                <Download className="size-3.5" />
                Template
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <LabeledInput label="Name" value={name} onChange={setName} />
            <LabeledInput label="Version" value={version} onChange={setVersion} />
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              How outputs get scored
            </span>
            <select
              value={scorer}
              onChange={(e) => setScorer(e.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm"
            >
              {SCORERS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Input file</label>
            <input
              type="file"
              accept=".csv,.json,.jsonl,.yaml,.yml"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-secondary-foreground"
            />
          </div>
          {error && <div className="text-sm text-destructive">{error}</div>}
          <Button onClick={() => upload.mutate()} disabled={upload.isPending}>
            {upload.isPending && <Spinner />}
            Create dataset
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}

function ShapeCard({
  active,
  onClick,
  title,
  body,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  body: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md border p-4 text-left transition-colors",
        active ? "border-foreground bg-secondary/50" : "hover:bg-secondary/30",
      )}
    >
      <div className="font-medium text-sm mb-1">{title}</div>
      <div className="text-xs text-muted-foreground leading-relaxed">{body}</div>
    </button>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border bg-background px-3 text-sm"
      />
    </label>
  );
}

// ---------------------------------------------------------------------------
// Stages 2-4 — the dataset workspace
// ---------------------------------------------------------------------------

function Workspace({
  datasetId,
  navigate,
}: {
  datasetId: number;
  navigate: (path: string) => void;
}) {
  const qc = useQueryClient();
  const dataset = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.getDataset(datasetId),
  });
  const cases = useQuery({
    queryKey: ["cases", datasetId],
    queryFn: () => api.listCases(datasetId),
  });
  const candidates = useQuery({
    queryKey: ["candidates", datasetId],
    queryFn: () => api.listCandidates(datasetId),
  });
  const genStatus = useQuery({
    queryKey: ["gen-status", datasetId],
    queryFn: () => api.generationStatus(datasetId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
  });
  const newVersion = useMutation({
    mutationFn: () => api.newVersion(datasetId),
    onSuccess: (clone) => {
      qc.invalidateQueries({ queryKey: ["datasets"] });
      navigate(`/builder/${clone.id}`);
    },
  });

  if (dataset.isLoading || !dataset.data) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Spinner /> Loading…
      </div>
    );
  }
  const ds = dataset.data;
  const total = ds.case_count;
  const locked = ds.locked_count;
  const allLocked = total > 0 && locked === total;
  const byCase = new Map<number, Candidate[]>();
  for (const c of candidates.data ?? []) {
    byCase.set(c.case_id, [...(byCase.get(c.case_id) ?? []), c]);
  }
  const hasCandidates = (candidates.data?.length ?? 0) > 0;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["dataset", datasetId] });
    qc.invalidateQueries({ queryKey: ["cases", datasetId] });
    qc.invalidateQueries({ queryKey: ["candidates", datasetId] });
    qc.invalidateQueries({ queryKey: ["gen-status", datasetId] });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          {ds.name}{" "}
          <span className="text-muted-foreground text-sm font-normal">{ds.version}</span>
        </h1>
        <div className="flex items-center gap-2">
          {allLocked ? (
            <Badge variant="success">
              <CheckCircle2 className="size-3 mr-1" /> Golden dataset · {total} cases
            </Badge>
          ) : (
            <Badge variant="warning">
              {locked}/{total} locked
            </Badge>
          )}
          <Button size="sm" variant="outline" onClick={() => newVersion.mutate()}>
            <Copy className="size-3.5" /> New version
          </Button>
          {allLocked && (
            <Button size="sm" onClick={() => navigate(`/runs?dataset_id=${datasetId}`)}>
              <Play className="size-3.5" /> View runs
            </Button>
          )}
        </div>
      </div>

      <DatasetSettings key={`${ds.id}-${ds.has_runs}`} dataset={ds} />
      <RequestPreviewCard datasetId={datasetId} shape={ds.request_shape} />
      {allLocked && <RunLauncher datasetId={datasetId} navigate={navigate} />}
      {!allLocked && (
        <GenerateCard
          datasetId={datasetId}
          status={genStatus.data}
          hasCandidates={hasCandidates}
          onDone={refresh}
        />
      )}

      <div className="space-y-4">
        {cases.isLoading && <Spinner />}
        {cases.data?.map((caseRow) => (
          <CaseReview
            key={caseRow.id}
            datasetId={datasetId}
            caseRow={caseRow}
            candidates={byCase.get(caseRow.id) ?? []}
            canUnlock={!ds.has_runs}
            onChanged={refresh}
          />
        ))}
      </div>

      {ds.scorer === "llm_judge" && hasCandidates && (
        <JudgeCard datasetId={datasetId} candidates={candidates.data ?? []} />
      )}
    </div>
  );
}

function RequestPreviewCard({
  datasetId,
  shape,
}: {
  datasetId: number;
  shape: "raw" | "templated";
}) {
  const [open, setOpen] = useState(false);
  const preview = useQuery({
    queryKey: ["preview", datasetId],
    queryFn: () => api.previewRequest(datasetId),
    enabled: open,
  });
  return (
    <Card>
      <CardHeader
        title="Request preview"
        subtitle={
          shape === "templated"
            ? "System and user message for the first case"
            : "Requests are sent unchanged"
        }
        right={
          <Button size="sm" variant="outline" onClick={() => setOpen(!open)}>
            <Eye className="size-3.5" />
            {open ? "Hide" : "Show"}
          </Button>
        }
      />
      {open && (
        <CardBody className="space-y-3">
          {preview.isLoading && <Spinner />}
          {preview.data && (
            <>
              <div className="text-xs text-muted-foreground">
                First case: {preview.data.case_id_external}
              </div>
              {preview.data.system && (
                <div>
                  <div className="text-xs font-medium text-muted-foreground mb-1">
                    System role
                  </div>
                  <pre className="text-xs bg-muted/40 rounded-md p-3 whitespace-pre-wrap">
                    {preview.data.system}
                  </pre>
                </div>
              )}
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">
                  User message
                </div>
                <pre className="text-xs bg-muted/40 rounded-md p-3 whitespace-pre-wrap">
                  {preview.data.user}
                </pre>
              </div>
            </>
          )}
        </CardBody>
      )}
    </Card>
  );
}

function GenerateCard({
  datasetId,
  status,
  hasCandidates,
  onDone,
}: {
  datasetId: number;
  status: GenerationStatus | undefined;
  hasCandidates: boolean;
  onDone: () => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [params, setParams] = useState<Record<string, ModelParams>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [maxCost, setMaxCost] = useState(2.0);
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();

  const start = useMutation({
    mutationFn: () => api.startGeneration(datasetId, models, maxCost, cleanParams(params)),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["gen-status", datasetId] });
    },
    onError: (e: Error) =>
      setError(e.message.includes("409") ? "A generation is already running." : e.message),
  });

  const running = status?.status === "running";

  // Load the outputs into the review list the moment generation finishes.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (running) wasRunning.current = true;
    if (!running && wasRunning.current && status?.status === "done") {
      wasRunning.current = false;
      onDone();
    }
  }, [running, status?.status, onDone]);

  return (
    <Card>
      <CardHeader
        title="Generate candidates"
        subtitle={
          hasCandidates
            ? `${status?.candidate_count ?? 0} outputs stored`
            : "Run the dataset through the selected models"
        }
      />
      <CardBody className="space-y-3">
        <SuggestModels
          datasetId={datasetId}
          onPicked={(picks: ModelPick[]) => {
            setModels(picks.map((p) => p.model));
            setNotes(Object.fromEntries(picks.map((p) => [p.model, p.reason])));
          }}
        />
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
            disabled={running || start.isPending || models.length === 0}
          >
            {(running || start.isPending) && <Spinner />}
            {hasCandidates ? "Regenerate" : "Generate"}
          </Button>
        </div>
        {running && status && (
          <div className="space-y-1">
            <div className="h-2 rounded bg-muted overflow-hidden">
              <div
                className="h-full bg-foreground transition-all"
                style={{ width: `${status.total ? (status.done / status.total) * 100 : 0}%` }}
              />
            </div>
            <div className="text-xs text-muted-foreground">
              {status.done}/{status.total} · {formatUsd(status.cost_usd)} spent
              {status.errors > 0 && ` · ${status.errors} errors`}
            </div>
          </div>
        )}
        {status?.status === "done" && status.done > 0 && (
          <div className="text-xs text-muted-foreground">
            Done. {status.done} outputs, {formatUsd(status.cost_usd)}
            {status.errors > 0 && `, ${status.errors} errors`}.
          </div>
        )}
        {status?.status === "aborted_cost" && (
          <div className="text-xs text-destructive">{status.detail}</div>
        )}
        {status?.status === "error" && (
          <div className="text-xs text-destructive">{status.detail ?? "generation failed"}</div>
        )}
        {error && <div className="text-xs text-destructive">{error}</div>}
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Stage 3 — blind review, one case at a time
// ---------------------------------------------------------------------------

const LETTERS = "ABCDEFGH";

function CaseReview({
  datasetId,
  caseRow,
  candidates,
  canUnlock,
  onChanged,
}: {
  datasetId: number;
  caseRow: Case;
  candidates: Candidate[];
  canUnlock: boolean;
  onChanged: () => void;
}) {
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const unlock = useMutation({
    mutationFn: () => api.unlockCase(datasetId, caseRow.id),
    onSuccess: onChanged,
    onError: (e: Error) => setUnlockError(e.message),
  });
  // Stable blind order: shuffle by candidate id, not model name.
  const ordered = useMemo(
    () => [...candidates].sort((a, b) => ((a.id * 2654435761) % 97) - ((b.id * 2654435761) % 97)),
    [candidates],
  );

  const variables = Object.entries(caseRow.input).filter(
    ([k]) => k !== "id" && k !== "context",
  );

  return (
    <Card className={cn(caseRow.locked && "border-success/40")}>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2 text-sm">
            {caseRow.case_id_external}
            {caseRow.locked ? (
              <Badge variant="success">
                <Lock className="size-3 mr-1" /> golden
              </Badge>
            ) : (
              <Badge variant="warning">pending</Badge>
            )}
          </span>
        }
        right={
          caseRow.locked ? (
            canUnlock ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => unlock.mutate()}
                disabled={unlock.isPending}
              >
                <LockOpen className="size-3.5" />
                Unlock
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">
                Runs reference this version. Create a new version to edit.
              </span>
            )
          ) : undefined
        }
      />
      <CardBody className="space-y-4">
        <div className="text-sm bg-muted/30 rounded-md p-3">
          {variables.map(([k, v]) => (
            <div key={k}>
              <span className="text-xs text-muted-foreground">{k}: </span>
              {typeof v === "string" ? v : JSON.stringify(v)}
            </div>
          ))}
        </div>

        {unlockError && (
          <div className="text-xs text-destructive">
            {unlockError.includes("409")
              ? "Runs reference this dataset. Create a new version to edit."
              : unlockError}
          </div>
        )}
        {caseRow.locked ? (
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">
              Golden answer
            </div>
            <pre className="text-xs bg-success/5 border border-success/20 rounded-md p-3 whitespace-pre-wrap">
              {JSON.stringify(caseRow.expected, null, 2)}
            </pre>
          </div>
        ) : ordered.length === 0 ? (
          <div className="text-xs text-muted-foreground">
            No outputs yet. Generate candidates above, then rate them here.
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {ordered.map((cand, i) => (
              <CandidateReview
                key={cand.id}
                datasetId={datasetId}
                candidate={cand}
                letter={LETTERS[i] ?? String(i + 1)}
                caseId={caseRow.id}
                onChanged={onChanged}
              />
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function CandidateReview({
  datasetId,
  candidate,
  letter,
  caseId,
  onChanged,
}: {
  datasetId: number;
  candidate: Candidate;
  letter: string;
  caseId: number;
  onChanged: () => void;
}) {
  const [feedback, setFeedback] = useState(candidate.feedback ?? "");
  const qc = useQueryClient();

  const rate = useMutation({
    mutationFn: (rating: number) =>
      api.rateCandidate(datasetId, candidate.id, rating, feedback.trim() || null),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["candidates", datasetId] }),
  });
  const pick = useMutation({
    mutationFn: () => api.pickGolden(datasetId, caseId, candidate.id),
    onSuccess: onChanged,
  });

  const rated = candidate.rating !== null;

  return (
    <div className="rounded-md border p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">
          Output {letter}
          {rated && (
            <span className="text-muted-foreground font-normal"> · {candidate.model}</span>
          )}
        </span>
        {candidate.status !== "ok" && <Badge variant="destructive">{candidate.status}</Badge>}
      </div>
      <pre className="text-xs bg-muted/30 rounded-md p-2.5 whitespace-pre-wrap max-h-40 overflow-auto">
        {candidate.status === "ok" ? candidate.content : (candidate.error ?? "failed")}
      </pre>
      <div className="flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            aria-label={`Rate ${n} of 5`}
            onClick={() => rate.mutate(n)}
            className="p-0.5"
          >
            <Star
              className={cn(
                "size-4 transition-colors",
                candidate.rating !== null && n <= candidate.rating
                  ? "fill-warning text-warning"
                  : "text-muted-foreground hover:text-foreground",
              )}
            />
          </button>
        ))}
        {rated && (
          <span className="text-xs text-muted-foreground ml-1">{candidate.rating}/5</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          onBlur={() => {
            if (candidate.rating !== null && feedback.trim() !== (candidate.feedback ?? "")) {
              rate.mutate(candidate.rating);
            }
          }}
          placeholder="Optional feedback, e.g. 'too verbose'"
          className="h-8 flex-1 rounded-md border bg-background px-2 text-xs"
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => pick.mutate()}
          disabled={pick.isPending || candidate.status !== "ok"}
        >
          <CheckCircle2 className="size-3.5" />
          Use as golden
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage 4 — judge calibration
// ---------------------------------------------------------------------------

function JudgeCard({ datasetId, candidates }: { datasetId: number; candidates: Candidate[] }) {
  const [judgeModel, setJudgeModel] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();
  const config = useQuery({
    queryKey: ["judge", datasetId],
    queryFn: () => api.getJudgeConfig(datasetId),
    retry: false,
  });
  const calibrate = useMutation({
    mutationFn: () => api.calibrateJudge(datasetId, judgeModel[0]),
    onSuccess: () => {
      setError(null);
      qc.invalidateQueries({ queryKey: ["judge", datasetId] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const ratedCount = candidates.filter((c) => c.rating !== null).length;
  const summary = config.data?.agreement.summary;
  const disagreements =
    config.data?.agreement.rows.filter((r) => Math.abs(r.human - r.judge) >= 1) ?? [];

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Scale className="size-4" /> Judge calibration
          </span>
        }
        subtitle={`${ratedCount} rated outputs available`}
      />
      <CardBody className="space-y-4">
        <div className="space-y-2">
          <span className="text-xs font-medium text-muted-foreground">Judge model</span>
          <ModelPicker selected={judgeModel} onChange={setJudgeModel} single />
        </div>
        <Button
          onClick={() => calibrate.mutate()}
          disabled={calibrate.isPending || ratedCount === 0 || judgeModel.length === 0}
        >
          {calibrate.isPending && <Spinner />}
          Calibrate
        </Button>
        {error && <div className="text-xs text-destructive">{error}</div>}

        {summary && config.data && (
          <div className="space-y-3">
            <div className="grid grid-cols-4 gap-2 text-center">
              <JudgeStat label="outputs" value={String(summary.n)} />
              <JudgeStat label="exact" value={`${Math.round(summary.exact * 100)}%`} />
              <JudgeStat label="within ±1" value={`${Math.round(summary.within_one * 100)}%`} />
              <JudgeStat
                label="kappa"
                value={summary.kappa.toFixed(2)}
                good={summary.kappa >= 0.6}
              />
            </div>
            <div className="text-xs text-muted-foreground">
              v{config.data.version} · {config.data.judge_model} · 0.6 kappa is the standard
              threshold.
              {summary.kappa < 0.6 && " Add feedback on the disagreements and recalibrate."}
            </div>
            {disagreements.length > 0 && (
              <div className="text-xs space-y-1">
                <div className="font-medium text-muted-foreground">Disagreements</div>
                {disagreements.map((r) => (
                  <div key={`${r.case_id}-${r.model}`} className="flex gap-2">
                    <span>{r.case_id}</span>
                    <span className="text-muted-foreground">{r.model}</span>
                    <span>
                      you {r.human}/5 · judge {r.judge}/5
                    </span>
                    {r.reason && <span className="text-muted-foreground">“{r.reason}”</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function JudgeStat({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-md bg-secondary/40 px-2 py-2">
      <div className={cn("text-lg font-semibold", good === true && "text-success")}>{value}</div>
      <div className="text-[0.65rem] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
