import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, FileBarChart, HardDriveUpload, PencilRuler } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { Badge } from "@/components/ui/Badge";
import { api } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

interface Props {
  navigate: (path: string) => void;
}

export function DatasetsPage({ navigate }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.listDatasets,
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const groups = new Map<string, typeof data>();
  for (const d of data ?? []) {
    groups.set(d.name, [...(groups.get(d.name) ?? []), d]);
  }
  for (const versions of groups.values()) {
    versions!.sort((a, b) => b.created_at.localeCompare(a.created_at));
  }

  const toggle = (name: string) => {
    const next = new Set(expanded);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setExpanded(next);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Datasets</h1>
        <Button onClick={() => navigate("/builder")}>
          <HardDriveUpload className="size-4" />
          New dataset
        </Button>
      </div>

      <Card>
        <CardBody className="p-0">
          {isLoading && (
            <div className="p-6 flex items-center gap-2 text-muted-foreground">
              <Spinner /> Loading…
            </div>
          )}
          {error && (
            <div className="p-6 text-destructive text-sm">Failed to load datasets.</div>
          )}
          {data && data.length === 0 && (
            <div className="p-12 text-center text-sm text-muted-foreground">
              No datasets yet. Upload inputs to start the Dataset Builder workflow.
            </div>
          )}
          {data && data.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Version</TH>
                  <TH>Scorer</TH>
                  <TH className="text-right">Golden</TH>
                  <TH>Created</TH>
                  <TH />
                </TR>
              </THead>
              <tbody>
                {[...groups.entries()].map(([name, versions]) => {
                  const latest = versions![0];
                  const older = versions!.slice(1);
                  const open = expanded.has(name);
                  const rows = open ? versions! : [latest];
                  return (
                    <Fragment key={name}>
                      {rows.map((d, i) => (
                  <TR
                    key={d.id}
                    className={cn(
                      "cursor-pointer hover:bg-secondary/30",
                      i > 0 && "bg-muted/20",
                    )}
                    onClick={() => navigate(`/builder/${d.id}`)}
                  >
                    <TD className="font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        {i === 0 && older.length > 0 && (
                          <button
                            type="button"
                            aria-label={`Show versions of ${name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              toggle(name);
                            }}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            {open ? (
                              <ChevronDown className="size-3.5" />
                            ) : (
                              <ChevronRight className="size-3.5" />
                            )}
                          </button>
                        )}
                        {i === 0 ? d.name : ""}
                        {i === 0 && older.length > 0 && (
                          <span className="text-xs text-muted-foreground font-normal">
                            {versions!.length} versions
                          </span>
                        )}
                      </span>
                      {i === 0 && d.description && (
                        <div className="text-xs text-muted-foreground font-normal">
                          {d.description}
                        </div>
                      )}
                    </TD>
                    <TD>
                      <span className="text-xs text-muted-foreground">{d.version}</span>
                    </TD>
                    <TD>
                      <Badge variant="outline">{d.scorer}</Badge>
                    </TD>
                    <TD className="text-right">
                      <Badge
                        variant={
                          d.locked_count === d.case_count && d.case_count > 0
                            ? "success"
                            : d.locked_count > 0
                              ? "warning"
                              : "outline"
                        }
                      >
                        {d.locked_count}/{d.case_count}
                      </Badge>
                    </TD>
                    <TD className="text-muted-foreground text-xs">{formatDate(d.created_at)}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/builder/${d.id}`);
                          }}
                        >
                          <PencilRuler className="size-3.5" />
                          Edit cases
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/runs?dataset_id=${d.id}`);
                          }}
                        >
                          <FileBarChart className="size-3.5" />
                          View runs
                        </Button>
                      </div>
                    </TD>
                  </TR>
                      ))}
                    </Fragment>
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
