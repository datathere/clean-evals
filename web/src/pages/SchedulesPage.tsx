import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CalendarClock, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export function SchedulesPage() {
  const qc = useQueryClient();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.listDatasets });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.listSchedules });
  const [datasetId, setDatasetId] = useState<number | "">("");
  const [cron, setCron] = useState("0 0 * * *");
  const [enabled, setEnabled] = useState(true);
  const [models, setModels] = useState("claude-3-5-sonnet-20241022,gpt-4o-mini-2024-07-18");
  const [maxCost, setMaxCost] = useState(2.0);

  const create = useMutation({
    mutationFn: () =>
      api.createSchedule({
        dataset_id: typeof datasetId === "number" ? datasetId : Number(datasetId),
        cron,
        enabled,
        config: {
          models: models.split(",").map((m) => m.trim()).filter(Boolean),
          max_cost_usd: maxCost,
        },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteSchedule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Schedules</h1>

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Plus className="size-4 text-primary" /> New schedule
            </span>
          }
        />
        <CardBody className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Dataset</span>
            <select
              value={datasetId}
              onChange={(e) => setDatasetId(Number(e.target.value))}
              className="h-9 rounded-md border bg-background px-3 text-sm"
            >
              <option value="">Select dataset…</option>
              {datasets.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} {d.version}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Cron</span>
            <input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm"
              placeholder="0 0 * * *"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Models</span>
            <input
              value={models}
              onChange={(e) => setModels(e.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Max cost USD</span>
            <input
              type="number"
              step="0.5"
              value={maxCost}
              onChange={(e) => setMaxCost(Number(e.target.value))}
              className="h-9 rounded-md border bg-background px-3 text-sm"
            />
          </label>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />{" "}
            Enabled
          </label>
          <div className="flex items-end justify-end md:col-start-2">
            <Button
              onClick={() => create.mutate()}
              disabled={!datasetId || !cron || create.isPending}
            >
              {create.isPending && <Spinner />}
              Create schedule
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <CalendarClock className="size-4 text-primary" /> All schedules
            </span>
          }
          subtitle={`${schedules.data?.length ?? 0} total`}
        />
        <CardBody className="p-0">
          {schedules.isLoading && (
            <div className="p-6">
              <Spinner />
            </div>
          )}
          {schedules.data && schedules.data.length === 0 && (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No schedules yet.
            </div>
          )}
          {schedules.data && schedules.data.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Dataset</TH>
                  <TH>Cron</TH>
                  <TH>State</TH>
                  <TH>Last run</TH>
                  <TH>Next run</TH>
                  <TH />
                </TR>
              </THead>
              <tbody>
                {schedules.data.map((s) => (
                  <TR key={s.id}>
                    <TD>#{s.dataset_id}</TD>
                    <TD>
                      <code className="text-xs">{s.cron}</code>
                    </TD>
                    <TD>
                      <Badge variant={s.enabled ? "success" : "warning"}>
                        {s.enabled ? "enabled" : "disabled"}
                      </Badge>
                    </TD>
                    <TD className="text-xs text-muted-foreground">{formatDate(s.last_run_at)}</TD>
                    <TD className="text-xs text-muted-foreground">{formatDate(s.next_run_at)}</TD>
                    <TD className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => remove.mutate(s.id)}
                        aria-label="delete schedule"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
