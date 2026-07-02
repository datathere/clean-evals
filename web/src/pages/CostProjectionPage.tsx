import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Calculator } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { api, type CostProjectionRow } from "@/lib/api";
import { formatScore, formatUsd } from "@/lib/utils";

interface Props {
  runId: string;
}

export function CostProjectionPage({ runId }: Props) {
  const [callsPerMonth, setCallsPerMonth] = useState(100_000);
  const [scoreFloor, setScoreFloor] = useState(0.8);

  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.getRun(runId) });

  const project = useMutation({
    mutationFn: () => api.costProjection(runId, callsPerMonth, scoreFloor),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Cost Projection</h1>

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Calculator className="size-4" /> Inputs
            </span>
          }
          subtitle={
            run.data
              ? `Based on run ${run.data.id} · dataset ${run.data.dataset} ${run.data.dataset_version}`
              : ""
          }
        />
        <CardBody className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Field label="Calls per month">
            <input
              type="number"
              min={1}
              value={callsPerMonth}
              onChange={(e) => setCallsPerMonth(Number(e.target.value))}
              className="w-full h-9 rounded-md border bg-background px-3 text-sm"
            />
          </Field>
          <Field label="Acceptable score floor">
            <input
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={scoreFloor}
              onChange={(e) => setScoreFloor(Number(e.target.value))}
              className="w-full h-9 rounded-md border bg-background px-3 text-sm"
            />
          </Field>
          <div className="flex items-end">
            <Button
              onClick={() => project.mutate()}
              disabled={project.isPending}
              className="w-full"
            >
              {project.isPending && <Spinner />}
              Project cost
            </Button>
          </div>
        </CardBody>
      </Card>

      {project.data && <ProjectionTable rows={project.data} />}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function ProjectionTable({ rows }: { rows: CostProjectionRow[] }) {
  return (
    <Card>
      <CardHeader title="Projection" />
      <CardBody className="p-0">
        <Table>
          <THead>
            <TR>
              <TH>Model</TH>
              <TH className="text-right">Score</TH>
              <TH>Qualifies</TH>
              <TH className="text-right">Projected monthly</TH>
            </TR>
          </THead>
          <tbody>
            {rows
              .slice()
              .sort((a, b) => a.projected_monthly_usd - b.projected_monthly_usd)
              .map((r) => (
                <TR key={r.model}>
                  <TD className="text-xs">{r.model}</TD>
                  <TD className="text-right">{formatScore(r.score_mean)}</TD>
                  <TD>
                    <Badge variant={r.qualifies ? "success" : "warning"}>
                      {r.qualifies ? "yes" : "below floor"}
                    </Badge>
                  </TD>
                  <TD className="text-right font-medium">{formatUsd(r.projected_monthly_usd)}</TD>
                </TR>
              ))}
          </tbody>
        </Table>
      </CardBody>
    </Card>
  );
}
