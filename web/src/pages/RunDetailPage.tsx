import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  BookOpenCheck,
  Calculator,
  DollarSign,
  ShieldCheck,
  Trophy,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { Badge } from "@/components/ui/Badge";
import { api, type CaseResult, type Recommendation } from "@/lib/api";
import { cn, formatLatency, formatPct, formatScore, formatUsd } from "@/lib/utils";

interface Props {
  runId: string;
  navigate: (path: string) => void;
}

type CaseKey = string;

const keyOf = (c: Pick<CaseResult, "case_id" | "model">): CaseKey =>
  `${c.case_id}::${c.model}`;

export function RunDetailPage({ runId, navigate }: Props) {
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId) });
  const recs = useQuery({
    queryKey: ["recs", runId],
    queryFn: () => api.getRecommendations(runId),
  });
  const cases = useQuery({
    queryKey: ["case-results", runId],
    queryFn: () => api.getCaseResults(runId),
  });
  const [selected, setSelected] = useState<CaseKey | null>(null);

  if (run.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Spinner /> Loading run…
      </div>
    );
  }
  if (run.error || !run.data) {
    return <div className="text-destructive text-sm">Failed to load run.</div>;
  }

  const summaryRows = Object.values(run.data.summary);
  const selectedResult = cases.data?.find((c) => keyOf(c) === selected) ?? null;

  return (
    <div className="space-y-8">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {run.data.dataset}{" "}
            <span className="text-muted-foreground font-normal">
              {run.data.dataset_version}
            </span>
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            {run.data.id} · pricing {run.data.pricing_version}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => navigate(`/builder/${run.data.dataset_id}`)}
          >
            <BookOpenCheck className="size-4" /> Golden dataset
          </Button>
          <Button variant="secondary" onClick={() => navigate(`/cost/${runId}`)}>
            <Calculator className="size-4" /> Cost projection
          </Button>
          <Button variant="secondary" onClick={() => navigate(`/live/${runId}`)}>
            <ArrowUpRight className="size-4" /> Live progress
          </Button>
        </div>
      </div>

      {/* Recommendations */}
      <div>
        {recs.isLoading && <Spinner />}
        {recs.data && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {recs.data.map((rec) => (
              <RecommendationCard key={rec.kind} rec={rec} />
            ))}
          </div>
        )}
      </div>

      {/* Leaderboard */}
      <Card>
        <CardHeader title="Leaderboard" subtitle={`${summaryRows.length} models`} />
        <CardBody className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Model</TH>
                <TH className="text-right">Score</TH>
                <TH className="text-right">Pass</TH>
                <TH className="text-right">p95 latency</TH>
                <TH className="text-right">Errors</TH>
                <TH className="text-right">$/run</TH>
                <TH className="text-right">$/correct</TH>
              </TR>
            </THead>
            <tbody>
              {summaryRows
                .slice()
                .sort((a, b) => b.score_mean - a.score_mean)
                .map((s) => (
                  <TR key={s.model}>
                    <TD className="text-xs">{s.model}</TD>
                    <TD className="text-right">{formatScore(s.score_mean)}</TD>
                    <TD className="text-right">
                      {s.cases_passed}/{s.cases_run}
                    </TD>
                    <TD className="text-right">{formatLatency(s.latency_p95_ms)}</TD>
                    <TD className="text-right">{formatPct(s.error_rate)}</TD>
                    <TD className="text-right">{formatUsd(s.total_cost_usd)}</TD>
                    <TD className="text-right">{formatUsd(s.cost_per_correct_usd)}</TD>
                  </TR>
                ))}
            </tbody>
          </Table>
        </CardBody>
      </Card>

      {/* Case results: what passed, what failed, expected vs got */}
      {cases.isLoading && <Spinner />}
      {cases.data && cases.data.length > 0 && (
        <Card>
          <CardHeader title="Per-case heatmap" />
          <CardBody>
            <Heatmap
              cases={cases.data}
              selected={selected}
              onSelect={(k) => setSelected(k === selected ? null : k)}
            />
          </CardBody>
        </Card>
      )}
      {cases.data && (
        <CaseResults
          cases={cases.data}
          selected={selected}
          onSelect={(k) => setSelected(k === selected ? null : k)}
        />
      )}

      {selectedResult && (
        <CaseInspector result={selectedResult} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const Icon =
    rec.kind === "max_accuracy" ? Trophy : rec.kind === "lowest_cost" ? DollarSign : ShieldCheck;
  const title =
    rec.kind === "max_accuracy"
      ? "Max Accuracy"
      : rec.kind === "lowest_cost"
        ? "Lowest Cost"
        : "Best Price/Performance";
  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Icon className="size-4" />
            {title}
          </span>
        }
        subtitle={rec.model ?? "no qualifying model"}
      />
      <CardBody className="space-y-3">
        {rec.summary && (
          <div className="grid grid-cols-3 gap-2 text-xs">
            <Stat label="Score" value={formatScore(rec.summary.score_mean)} />
            <Stat label="$/run" value={formatUsd(rec.summary.total_cost_usd)} />
            <Stat label="$/correct" value={formatUsd(rec.summary.cost_per_correct_usd)} />
          </div>
        )}
        <p className="text-sm text-muted-foreground leading-relaxed">{rec.rationale}</p>
      </CardBody>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-secondary/40 px-2 py-1.5">
      <div className="text-[0.65rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="font-medium text-foreground">{value}</div>
    </div>
  );
}

function shortJson(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  const s = JSON.stringify(value);
  return s.length > 80 ? `${s.slice(0, 77)}…` : s;
}

function gotText(c: CaseResult): string {
  if (c.status !== "ok") return c.error ?? c.status;
  if (c.response?.parsed) return shortJson(c.response.parsed);
  return c.response?.content ?? "—";
}

function expectedText(c: CaseResult): string {
  if (!c.expected) return "—";
  const values = Object.values(c.expected);
  if (values.length === 1) return shortJson(values[0]);
  return shortJson(c.expected);
}

function CaseResults({
  cases,
  selected,
  onSelect,
}: {
  cases: CaseResult[];
  selected: CaseKey | null;
  onSelect: (k: CaseKey) => void;
}) {
  const [view, setView] = useState<"failures" | "all">("failures");
  const failures = useMemo(
    () => cases.filter((c) => c.status !== "ok" || c.passed === false),
    [cases],
  );
  const shown = view === "failures" ? failures : cases;
  const sorted = shown
    .slice()
    .sort((a, b) => a.case_id.localeCompare(b.case_id) || a.model.localeCompare(b.model));

  return (
    <Card>
      <CardHeader
        title="Case results"
        subtitle={`${cases.length - failures.length} passed · ${failures.length} failed`}
        right={
          <div className="flex rounded-md border p-0.5 text-xs">
            <FilterTab
              active={view === "failures"}
              onClick={() => setView("failures")}
              label={`Failures (${failures.length})`}
            />
            <FilterTab
              active={view === "all"}
              onClick={() => setView("all")}
              label={`All (${cases.length})`}
            />
          </div>
        }
      />
      <CardBody className="p-0">
        {sorted.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">
            {view === "failures" ? "No failures." : "No case results."}
          </div>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Case</TH>
                <TH>Model</TH>
                <TH>Result</TH>
                <TH>Expected</TH>
                <TH>Got</TH>
                <TH className="text-right">Score</TH>
                <TH className="text-right">Latency</TH>
              </TR>
            </THead>
            <tbody>
              {sorted.map((c) => {
                const k = keyOf(c);
                const failed = c.status !== "ok" || c.passed === false;
                return (
                  <TR
                    key={k}
                    className={cn(
                      "cursor-pointer hover:bg-secondary/30",
                      selected === k && "bg-secondary/50",
                    )}
                    onClick={() => onSelect(k)}
                  >
                    <TD className="text-xs">{c.case_id}</TD>
                    <TD className="text-xs">{c.model}</TD>
                    <TD>
                      {c.status !== "ok" ? (
                        <Badge variant="destructive">{c.status}</Badge>
                      ) : c.passed ? (
                        <Badge variant="success">pass</Badge>
                      ) : (
                        <Badge variant="warning">fail</Badge>
                      )}
                    </TD>
                    <TD className="text-xs max-w-48 truncate">{expectedText(c)}</TD>
                    <TD
                      className={cn(
                        "text-xs max-w-48 truncate",
                        failed && "text-destructive",
                      )}
                    >
                      {gotText(c)}
                    </TD>
                    <TD className="text-right">{formatScore(c.score)}</TD>
                    <TD className="text-right text-xs">{formatLatency(c.latency_ms)}</TD>
                  </TR>
                );
              })}
            </tbody>
          </Table>
        )}
      </CardBody>
    </Card>
  );
}

function FilterTab({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded px-2.5 py-1 transition-colors",
        active ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}

function Heatmap({
  cases,
  selected,
  onSelect,
}: {
  cases: CaseResult[];
  selected: CaseKey | null;
  onSelect: (k: CaseKey) => void;
}) {
  const caseIds = Array.from(new Set(cases.map((c) => c.case_id))).sort();
  const models = Array.from(new Set(cases.map((c) => c.model))).sort();
  const lookup = new Map(cases.map((c) => [keyOf(c), c]));
  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-separate border-spacing-1">
        <thead>
          <tr>
            <th className="text-left px-2 text-muted-foreground font-normal">case</th>
            {models.map((m) => (
              <th key={m} className="text-left px-2 text-muted-foreground font-normal">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {caseIds.map((caseId) => (
            <tr key={caseId}>
              <td className="px-2 text-xs">{caseId}</td>
              {models.map((m) => {
                const cell = lookup.get(`${caseId}::${m}`);
                return (
                  <td key={m}>
                    <HeatCell
                      cell={cell}
                      selected={cell ? selected === keyOf(cell) : false}
                      onSelect={onSelect}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
        <Swatch className="bg-success/40" /> pass
        <Swatch className="bg-warning/40" /> fail
        <Swatch className="bg-destructive/40" /> error
        <Swatch className="bg-muted/40" /> no data
      </div>
    </div>
  );
}

function HeatCell({
  cell,
  selected,
  onSelect,
}: {
  cell: CaseResult | undefined;
  selected: boolean;
  onSelect: (k: CaseKey) => void;
}) {
  if (!cell) return <span className="block size-6 rounded bg-muted/40" />;
  let bg = "bg-muted/40";
  let title = "no data";
  if (cell.status !== "ok") {
    bg = "bg-destructive/40";
    title = `${cell.status}: ${cell.error ?? ""}`;
  } else if (cell.passed) {
    bg = "bg-success/40";
    title = `score ${cell.score?.toFixed(3)} · pass`;
  } else if (cell.score !== null) {
    bg = "bg-warning/40";
    title = `score ${cell.score?.toFixed(3)} · fail`;
  }
  return (
    <button
      type="button"
      title={title}
      aria-label={`Inspect ${cell.case_id} on ${cell.model}`}
      onClick={() => onSelect(keyOf(cell))}
      className={cn(
        "block size-6 rounded transition-all hover:ring-2 hover:ring-ring",
        bg,
        selected && "ring-2 ring-foreground",
      )}
    />
  );
}

function Swatch({ className }: { className: string }) {
  return <span className={`inline-block size-3 rounded ${className}`} />;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground mb-1">{label}</div>
      {children}
    </div>
  );
}

function CaseInspector({ result, onClose }: { result: CaseResult; onClose: () => void }) {
  const failed = result.status !== "ok" || result.passed === false;
  const prompt =
    typeof result.input?.prompt === "string"
      ? result.input.prompt
      : result.input
        ? JSON.stringify(result.input, null, 2)
        : "—";
  return (
    <Card className={cn("border-2", failed ? "border-warning/60" : "border-success/60")}>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2 text-sm">
            {result.case_id}
            <span className="text-muted-foreground font-normal">on</span>
            {result.model}
            {result.status !== "ok" ? (
              <Badge variant="destructive">{result.status}</Badge>
            ) : result.passed ? (
              <Badge variant="success">pass</Badge>
            ) : (
              <Badge variant="warning">fail</Badge>
            )}
          </span>
        }
        right={
          <button
            type="button"
            aria-label="Close inspector"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        }
      />
      <CardBody className="space-y-4">
        <Field label="Input">
          <pre className="text-xs bg-muted/40 rounded-md p-3 whitespace-pre-wrap max-h-48 overflow-auto">
            {prompt}
          </pre>
        </Field>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Field label="Expected (golden)">
            <pre className="text-xs bg-success/5 border border-success/20 rounded-md p-3 whitespace-pre-wrap max-h-48 overflow-auto">
              {result.expected ? JSON.stringify(result.expected, null, 2) : "—"}
            </pre>
          </Field>
          <Field label="Model answer">
            <pre
              className={cn(
                "text-xs rounded-md p-3 whitespace-pre-wrap max-h-48 overflow-auto border",
                failed
                  ? "bg-destructive/5 border-destructive/20"
                  : "bg-success/5 border-success/20",
              )}
            >
              {result.status !== "ok"
                ? (result.error ?? result.status)
                : result.response?.parsed
                  ? JSON.stringify(result.response.parsed, null, 2)
                  : (result.response?.content ?? "—")}
            </pre>
          </Field>
        </div>
        <div className="flex gap-6 text-xs text-muted-foreground">
          <span>score {formatScore(result.score)}</span>
          <span>{formatLatency(result.latency_ms)}</span>
          <span>{formatUsd(result.cost_usd)}</span>
        </div>
      </CardBody>
    </Card>
  );
}
