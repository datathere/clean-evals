import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCheck,
  Inbox,
  Lock,
  RefreshCw,
  ShieldQuestion,
  Trash2,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { api, type TelemetryExchange } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

interface Props {
  navigate: (path: string) => void;
}

export function TelemetryPage({ navigate }: Props) {
  const qc = useQueryClient();
  const [source, setSource] = useState("");
  const [dataset, setDataset] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const inbox = useQuery({
    queryKey: ["telemetry-inbox", source, dataset],
    queryFn: () =>
      api.telemetryInbox({
        source: source || undefined,
        dataset: dataset || undefined,
      }),
  });
  const spotChecks = useQuery({
    queryKey: ["telemetry-spot-checks"],
    queryFn: api.telemetrySpotChecks,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["telemetry-inbox"] });
    void qc.invalidateQueries({ queryKey: ["telemetry-spot-checks"] });
  };

  const upload = useMutation({
    mutationFn: (file: File) => api.telemetryUpload(file),
    onSuccess: invalidate,
  });
  const derive = useMutation({ mutationFn: api.telemetryDerive, onSuccess: invalidate });
  const promote = useMutation({
    mutationFn: ({ id, lock }: { id: number; lock: boolean }) => api.telemetryPromote(id, lock),
    onSuccess: invalidate,
  });
  const discard = useMutation({
    mutationFn: (id: number) => api.telemetryDiscard(id),
    onSuccess: invalidate,
  });
  const resolve = useMutation({
    mutationFn: ({ id, resolution }: { id: number; resolution: "confirmed" | "overturned" }) =>
      api.telemetrySpotCheckResolve(id, resolution),
    onSuccess: invalidate,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-2xl font-semibold tracking-tight">Telemetry</h1>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => navigate("/telemetry/monitor")}>
            Monitoring
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => derive.mutate()}
            disabled={derive.isPending}
          >
            {derive.isPending ? <Spinner /> : <RefreshCw className="size-3.5" />}
            Derive pending
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".jsonl,.json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
              e.target.value = "";
            }}
          />
          <Button size="sm" onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? <Spinner /> : <Upload className="size-3.5" />}
            Upload JSONL
          </Button>
        </div>
      </div>

      <p className="text-sm text-muted-foreground max-w-3xl">
        Production interactions, derived into reviewable exchanges. Envelopes are stored{" "}
        <strong>raw</strong> unless a telemetry scrubber is configured — treat this inbox as
        containing whatever your application sent. Nothing enters a golden dataset without the
        review below.
      </p>

      {upload.error && (
        <div className="text-sm rounded-md border border-destructive/40 px-4 py-3 text-destructive">
          Upload failed: {String(upload.error)}
        </div>
      )}
      {derive.error && (
        <div className="text-sm rounded-md border border-destructive/40 px-4 py-3 text-destructive">
          Derivation failed: {String(derive.error)}
        </div>
      )}
      {upload.data && (
        <div className="text-sm rounded-md border px-4 py-3 bg-secondary/40">
          Accepted {upload.data.accepted}
          {upload.data.duplicates.length > 0 && <> · {upload.data.duplicates.length} duplicates</>}
          {upload.data.rejected.length > 0 && (
            <span className="text-destructive">
              {" "}
              · {upload.data.rejected.length} rejected ({upload.data.rejected[0].error})
            </span>
          )}
          {upload.data.scrubber === null && (
            <span className="text-muted-foreground"> · no scrubber configured — stored raw</span>
          )}
        </div>
      )}
      {derive.data && (
        <div className="text-sm rounded-md border px-4 py-3 bg-secondary/40">
          Derived {derive.data.exchanges} exchanges from {derive.data.interactions} interactions
          {derive.data.auto_locked > 0 && <> · {derive.data.auto_locked} auto-locked</>}
          {derive.data.classifier_cost_usd > 0 && (
            <> · classifier ${derive.data.classifier_cost_usd.toFixed(4)}</>
          )}
          {derive.data.skipped_budget > 0 && (
            <span className="text-destructive">
              {" "}
              · {derive.data.skipped_budget} skipped (daily classifier ceiling)
            </span>
          )}
        </div>
      )}

      {spotChecks.data && spotChecks.data.total > 0 && (
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <ShieldQuestion className="size-4 text-primary" /> Spot checks
              </span>
            }
            subtitle={`${spotChecks.data.total} auto-locked exchanges sampled for review — resolutions feed the lane's measured overturn rate`}
          />
          <CardBody className="space-y-4">
            {spotChecks.data.exchanges.map((ex) => (
              <ExchangeCard key={ex.id} exchange={ex}>
                <Button
                  size="sm"
                  onClick={() => resolve.mutate({ id: ex.id, resolution: "confirmed" })}
                  disabled={resolve.isPending}
                >
                  <CheckCheck className="size-3.5" /> Confirm
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => resolve.mutate({ id: ex.id, resolution: "overturned" })}
                  disabled={resolve.isPending}
                >
                  <AlertTriangle className="size-3.5" /> Overturn &amp; unlock
                </Button>
              </ExchangeCard>
            ))}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Inbox className="size-4 text-primary" /> Inbox
            </span>
          }
          subtitle={`${inbox.data?.total ?? 0} derived exchanges awaiting review`}
        />
        <CardBody className="space-y-4">
          <div className="flex gap-3 flex-wrap">
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="Filter by source…"
              className="h-9 rounded-md border bg-background px-3 text-sm w-48"
            />
            <input
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              placeholder="Filter by dataset…"
              className="h-9 rounded-md border bg-background px-3 text-sm w-48"
            />
          </div>

          {inbox.isLoading && <Spinner />}
          {inbox.data && inbox.data.exchanges.length === 0 && (
            <div className="py-12 text-center text-sm text-muted-foreground">
              Nothing to review. Ingest telemetry through{" "}
              <code>POST /api/v1/telemetry/interactions</code> or upload a JSONL file.
            </div>
          )}
          {inbox.data?.exchanges.map((ex) => (
            <ExchangeCard key={ex.id} exchange={ex}>
              <Button
                size="sm"
                onClick={() => promote.mutate({ id: ex.id, lock: true })}
                disabled={promote.isPending || ex.proposed_expected === null}
                title={
                  ex.proposed_expected === null
                    ? "No proposed golden answer — promote unlocked and pick one in the Builder"
                    : "Create a locked case with the proposed golden answer"
                }
              >
                <Lock className="size-3.5" /> Promote &amp; lock
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => promote.mutate({ id: ex.id, lock: false })}
                disabled={promote.isPending}
              >
                Promote unlocked
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => discard.mutate(ex.id)}
                disabled={discard.isPending}
                aria-label="discard exchange"
              >
                <Trash2 className="size-3.5" />
              </Button>
            </ExchangeCard>
          ))}
          {(promote.error || discard.error) && (
            <div className="text-sm text-destructive">
              {String(promote.error ?? discard.error)}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

const VERDICT_BADGE: Record<string, "success" | "warning" | "destructive" | "default"> = {
  positive: "success",
  negative: "destructive",
  incomplete: "warning",
  unrated: "default",
};

function ExchangeCard({
  exchange,
  children,
}: {
  exchange: TelemetryExchange;
  children: React.ReactNode;
}) {
  const [showContext, setShowContext] = useState(false);
  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
        <Badge variant={VERDICT_BADGE[exchange.verdict ?? "unrated"]}>
          {exchange.verdict ?? "unrated"}
        </Badge>
        {exchange.label && <Badge>{exchange.label.replaceAll("_", " ")}</Badge>}
        {exchange.rating !== null && <Badge>implicit {exchange.rating}/5</Badge>}
        {exchange.judge_score !== null && (
          <Badge variant={exchange.judge_score >= 0.7 ? "success" : "warning"}>
            judge {(exchange.judge_score * 100).toFixed(0)}% — concordance
          </Badge>
        )}
        {exchange.regen_count > 0 && (
          <Badge variant="warning">{exchange.regen_count} regens</Badge>
        )}
        {exchange.auto_locked && <Badge variant="warning">auto-locked</Badge>}
        <span>
          {exchange.source} → {exchange.dataset} · {exchange.kind}
          {exchange.kind === "transcript" && ` · turn ${exchange.turn_index}`} ·{" "}
          {formatDate(exchange.occurred_at)} · {exchange.response_model}
        </span>
      </div>

      {exchange.context.length > 0 && (
        <button
          type="button"
          onClick={() => setShowContext((v) => !v)}
          className="text-xs underline underline-offset-4 text-muted-foreground hover:text-foreground"
        >
          {showContext ? "Hide" : "Show"} conversation context ({exchange.context.length} turns)
        </button>
      )}
      {showContext && (
        <div className="space-y-1 border-l-2 pl-3">
          {exchange.context.map((turn, i) => (
            <p key={i} className="text-xs">
              <span className="font-medium">{turn.role}:</span>{" "}
              <span className="text-muted-foreground">{turn.text}</span>
            </p>
          ))}
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-3 text-sm">
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Request</p>
          <p className="whitespace-pre-wrap break-words">{exchange.request_text}</p>
        </div>
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Response</p>
          <p className="whitespace-pre-wrap break-words">{exchange.response_text}</p>
        </div>
      </div>

      {exchange.feedback && (
        <p className="text-sm">
          <span className="text-xs font-medium text-muted-foreground">Implicit feedback: </span>
          {exchange.feedback}
        </p>
      )}
      {exchange.proposed_expected && (
        <p className={cn("text-sm")}>
          <span className="text-xs font-medium text-muted-foreground">Proposed golden: </span>
          <code className="text-xs">{JSON.stringify(exchange.proposed_expected)}</code>
        </p>
      )}

      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}
