import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronRight, Play, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { Badge } from "@/components/ui/Badge";
import { RunLauncher } from "@/components/RunLauncher";
import { api } from "@/lib/api";
import { formatDate, formatScore, formatUsd } from "@/lib/utils";

interface Props {
  navigate: (path: string) => void;
  datasetId?: number;
}

export function RunsPage({ navigate, datasetId }: Props) {
  const [launcherOpen, setLauncherOpen] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["runs", datasetId ?? null],
    queryFn: () => api.listRuns(datasetId),
  });

  const filterName = datasetId !== undefined && data?.[0] ? data[0].dataset : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          {datasetId !== undefined && (
            <button
              type="button"
              onClick={() => navigate("/runs")}
              className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/60"
            >
              dataset: {filterName ?? `#${datasetId}`}
              <X className="size-3" />
            </button>
          )}
        </div>
        <Button onClick={() => setLauncherOpen(!launcherOpen)}>
          <Play className="size-4" />
          New run
        </Button>
      </div>

      {launcherOpen && <RunLauncher datasetId={datasetId} navigate={navigate} />}

      <Card>
        <CardHeader title="Recent runs" subtitle={`${data?.length ?? 0} total`} />
        <CardBody className="p-0">
          {isLoading && (
            <div className="p-6 flex items-center gap-2 text-muted-foreground">
              <Spinner /> Loading…
            </div>
          )}
          {error && <div className="p-6 text-destructive text-sm">Failed to load runs.</div>}
          {data && data.length === 0 && (
            <div className="p-12 text-center text-sm text-muted-foreground">
              No runs yet. Run <code>clean-evals run</code> or trigger one from a dataset.
            </div>
          )}
          {data && data.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Run id</TH>
                  <TH>Dataset</TH>
                  <TH>Status</TH>
                  <TH>Triggered by</TH>
                  <TH>Best score</TH>
                  <TH>Total cost</TH>
                  <TH>Created</TH>
                  <TH />
                </TR>
              </THead>
              <tbody>
                {data.map((r) => {
                  const summaries = Object.values(r.summary);
                  const bestScore =
                    summaries.length > 0
                      ? Math.max(...summaries.map((s) => s.score_mean))
                      : null;
                  const totalCost =
                    summaries.reduce((acc, s) => acc + s.total_cost_usd, 0) || 0;
                  return (
                    <TR
                      key={r.id}
                      className="cursor-pointer hover:bg-secondary/30"
                      onClick={() => navigate(`/runs/${r.id}`)}
                    >
                      <TD className="text-xs">{r.id}</TD>
                      <TD>
                        {r.dataset}{" "}
                        <span className="text-xs text-muted-foreground">{r.dataset_version}</span>
                      </TD>
                      <TD>
                        <Badge
                          variant={
                            r.status === "done"
                              ? "success"
                              : r.status === "aborted"
                                ? "destructive"
                                : "warning"
                          }
                        >
                          {r.status}
                        </Badge>
                      </TD>
                      <TD className="text-xs text-muted-foreground">{r.triggered_by}</TD>
                      <TD>{formatScore(bestScore)}</TD>
                      <TD>{formatUsd(totalCost)}</TD>
                      <TD className="text-xs text-muted-foreground">
                        {formatDate(r.created_at)}
                      </TD>
                      <TD>
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </TD>
                    </TR>
                  );
                })}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
