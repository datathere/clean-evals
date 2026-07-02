import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { DownloadCloud, Eye, EyeOff, Pencil, Plus, RefreshCw, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { api, type CatalogModel, type PriceProposal, type Provider } from "@/lib/api";
import { formatContext, formatUsd } from "@/lib/utils";

export function ModelsPage() {
  const qc = useQueryClient();
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.getProviders });
  const [proposals, setProposals] = useState<PriceProposal[] | null>(null);
  const [feedError, setFeedError] = useState<string | null>(null);

  const refresh = useMutation({
    mutationFn: api.refreshPrices,
    onSuccess: (data) => {
      setFeedError(null);
      setProposals(data);
    },
    onError: (e: Error) => setFeedError(e.message),
  });
  const apply = useMutation({
    mutationFn: (items: PriceProposal[]) => api.applyPrices(items),
    onSuccess: (data) => {
      qc.setQueryData(["providers"], data);
      setProposals(null);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Models</h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? <Spinner /> : <DownloadCloud className="size-3.5" />}
            Refresh prices
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => providers.refetch()}
            disabled={providers.isFetching}
          >
            {providers.isFetching ? <Spinner /> : <RefreshCw className="size-3.5" />}
            Re-verify
          </Button>
        </div>
      </div>

      {feedError && <div className="text-sm text-destructive">{feedError}</div>}
      {proposals && (
        <ProposalsCard
          proposals={proposals}
          onApply={(items) => apply.mutate(items)}
          onDismiss={() => setProposals(null)}
          applying={apply.isPending}
        />
      )}

      {providers.isLoading && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Spinner /> Verifying providers…
        </div>
      )}
      {providers.error && (
        <div className="text-sm text-destructive">Failed to load the model catalog.</div>
      )}

      {providers.data?.map((p) => <ProviderCard key={p.provider} provider={p} />)}

      <Card>
        <CardHeader title="Connect a provider" />
        <CardBody className="text-sm space-y-3">
          <ol className="list-decimal list-inside space-y-1">
            <li>
              Copy <code>.env.example</code> to <code>.env</code>.
            </li>
            <li>Add your API key.</li>
            <li>
              Restart <code>clean-evals serve</code>.
            </li>
          </ol>
          <p className="text-muted-foreground text-xs">
            Connected: key verified with a live request. Status is cached for five minutes.
            Connected providers also report their model list; models without a price run at
            $0 until a price is set. Prices are stored in{" "}
            <code>clean-evals-data/pricing.yml</code>.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}

function ProposalsCard({
  proposals,
  onApply,
  onDismiss,
  applying,
}: {
  proposals: PriceProposal[];
  onApply: (items: PriceProposal[]) => void;
  onDismiss: () => void;
  applying: boolean;
}) {
  return (
    <Card className="border-foreground/20">
      <CardHeader
        title="Price updates from feeds"
        subtitle={proposals.length === 0 ? "Prices match the feeds" : `${proposals.length} changes`}
        right={
          <div className="flex gap-2">
            {proposals.length > 0 && (
              <Button size="sm" onClick={() => onApply(proposals)} disabled={applying}>
                {applying && <Spinner />}
                Apply all
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={onDismiss}>
              Dismiss
            </Button>
          </div>
        }
      />
      {proposals.length > 0 && (
        <CardBody className="p-0">
          <Table>
            <THead>
              <TR>
                <TH>Model</TH>
                <TH className="text-right">Input $/Mtok</TH>
                <TH className="text-right">Output $/Mtok</TH>
              </TR>
            </THead>
            <tbody>
              {proposals.map((p) => (
                <TR key={`${p.provider}/${p.model}`}>
                  <TD className="text-xs">
                    {p.provider}/{p.model}
                  </TD>
                  <TD className="text-right text-xs">
                    <PriceChange from={p.current_input} to={p.new_input} />
                  </TD>
                  <TD className="text-right text-xs">
                    <PriceChange from={p.current_output} to={p.new_output} />
                  </TD>
                </TR>
              ))}
            </tbody>
          </Table>
        </CardBody>
      )}
    </Card>
  );
}

function PriceChange({ from, to }: { from: number | null; to: number }) {
  return (
    <span>
      <span className="text-muted-foreground line-through mr-1.5">
        {from === null ? "unpriced" : formatUsd(from)}
      </span>
      {formatUsd(to)}
    </span>
  );
}

function StatusBadge({ status }: { status: Provider["status"] }) {
  switch (status) {
    case "connected":
      return <Badge variant="success">connected</Badge>;
    case "invalid_key":
      return <Badge variant="destructive">key rejected</Badge>;
    case "unreachable":
      return <Badge variant="warning">unreachable</Badge>;
    default:
      return <Badge variant="outline">not configured</Badge>;
  }
}

function ProviderCard({ provider }: { provider: Provider }) {
  const [adding, setAdding] = useState(false);
  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            {provider.provider}
            <StatusBadge status={provider.status} />
          </span>
        }
        subtitle={
          provider.status === "connected"
            ? `${provider.models.length} models`
            : provider.status === "invalid_key"
              ? `Check ${provider.env_var}.`
              : provider.status === "unreachable"
                ? "No response. Re-verify."
                : `Set ${provider.env_var} in .env.`
        }
        right={
          <Button size="sm" variant="ghost" onClick={() => setAdding(!adding)}>
            <Plus className="size-3.5" />
            Add model
          </Button>
        }
      />
      {(provider.models.length > 0 || adding) && (
        <CardBody className="p-0">
          {adding && (
            <AddModelRow provider={provider.provider} onDone={() => setAdding(false)} />
          )}
          <Table>
            <THead>
              <TR>
                <TH>Model</TH>
                <TH className="text-right">Input $/Mtok</TH>
                <TH className="text-right">Output $/Mtok</TH>
                <TH />
              </TR>
            </THead>
            <tbody>
              {provider.models
                .filter((m) => !m.excluded)
                .map((m) => (
                  <ModelRow key={m.id} provider={provider.provider} model={m} />
                ))}
            </tbody>
          </Table>
          <ExcludedSection provider={provider} />
        </CardBody>
      )}
    </Card>
  );
}

function ExcludedSection({ provider }: { provider: Provider }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const excluded = provider.models.filter((m) => m.excluded);
  const include = useMutation({
    mutationFn: (model: string) => api.setExcluded(provider.provider, model, false),
    onSuccess: (data) => qc.setQueryData(["providers"], data),
  });
  if (excluded.length === 0) return null;
  return (
    <div className="border-t">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2 text-left text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? "Hide" : "Show"} excluded ({excluded.length})
      </button>
      {open && (
        <div className="divide-y">
          {excluded.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between px-3 py-1.5 opacity-60"
            >
              <span className="text-xs">{m.id}</span>
              <Button size="sm" variant="ghost" onClick={() => include.mutate(m.id)}>
                <Eye className="size-3.5" />
                Include
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModelRow({ provider, model }: { provider: string; model: CatalogModel }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState(String(model.input_per_mtok ?? ""));
  const [output, setOutput] = useState(String(model.output_per_mtok ?? ""));

  const save = useMutation({
    mutationFn: () => api.setPrice(provider, model.id, Number(input), Number(output)),
    onSuccess: (data) => {
      qc.setQueryData(["providers"], data);
      setEditing(false);
    },
  });
  const revert = useMutation({
    mutationFn: () => api.removePrice(provider, model.id),
    onSuccess: (data) => qc.setQueryData(["providers"], data),
  });
  const exclude = useMutation({
    mutationFn: () => api.setExcluded(provider, model.id, true),
    onSuccess: (data) => qc.setQueryData(["providers"], data),
  });

  if (editing) {
    return (
      <TR>
        <TD className="text-xs">{model.id}</TD>
        <TD className="text-right">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="h-7 w-24 rounded-md border bg-background px-2 text-xs text-right"
          />
        </TD>
        <TD className="text-right">
          <input
            value={output}
            onChange={(e) => setOutput(e.target.value)}
            className="h-7 w-24 rounded-md border bg-background px-2 text-xs text-right"
          />
        </TD>
        <TD className="text-right">
          <div className="flex justify-end gap-1">
            <Button
              size="sm"
              onClick={() => save.mutate()}
              disabled={save.isPending || !Number(input) || !Number(output)}
            >
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </TD>
      </TR>
    );
  }

  return (
    <TR>
      <TD className="text-xs">
        {model.id}
        {model.context_length !== null && (
          <span className="ml-2 text-[0.65rem] text-muted-foreground">
            {formatContext(model.context_length)} context
          </span>
        )}
        {model.overridden && (
          <Badge variant="outline" className="ml-2">
            custom
          </Badge>
        )}
        {model.listed && model.input_per_mtok === null && (
          <span className="ml-2 text-[0.65rem] text-warning">no price</span>
        )}
        {model.description && (
          <div className="mt-0.5 max-w-xl truncate text-[0.7rem] text-muted-foreground" title={model.description}>
            {model.description}
          </div>
        )}
      </TD>
      <TD className="text-right">{formatUsd(model.input_per_mtok)}</TD>
      <TD className="text-right">{formatUsd(model.output_per_mtok)}</TD>
      <TD className="text-right">
        <div className="flex justify-end gap-1">
          <button
            type="button"
            aria-label={`Edit price for ${model.id}`}
            onClick={() => setEditing(true)}
            className="p-1 text-muted-foreground hover:text-foreground"
          >
            <Pencil className="size-3.5" />
          </button>
          {model.overridden && (
            <button
              type="button"
              aria-label={`Revert price for ${model.id}`}
              onClick={() => revert.mutate()}
              className="p-1 text-muted-foreground hover:text-foreground"
            >
              <Undo2 className="size-3.5" />
            </button>
          )}
          <button
            type="button"
            aria-label={`Exclude ${model.id}`}
            title="Exclude from pickers"
            onClick={() => exclude.mutate()}
            className="p-1 text-muted-foreground hover:text-foreground"
          >
            <EyeOff className="size-3.5" />
          </button>
        </div>
      </TD>
    </TR>
  );
}

function AddModelRow({ provider, onDone }: { provider: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [id, setId] = useState("");
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const add = useMutation({
    mutationFn: () => api.setPrice(provider, id.trim(), Number(input), Number(output)),
    onSuccess: (data) => {
      qc.setQueryData(["providers"], data);
      onDone();
    },
  });
  return (
    <div className="flex items-center gap-2 border-b px-3 py-2">
      <input
        value={id}
        onChange={(e) => setId(e.target.value)}
        placeholder="model id"
        className="h-8 flex-1 rounded-md border bg-background px-2 text-xs"
      />
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="input $/Mtok"
        className="h-8 w-28 rounded-md border bg-background px-2 text-xs"
      />
      <input
        value={output}
        onChange={(e) => setOutput(e.target.value)}
        placeholder="output $/Mtok"
        className="h-8 w-28 rounded-md border bg-background px-2 text-xs"
      />
      <Button
        size="sm"
        onClick={() => add.mutate()}
        disabled={add.isPending || !id.trim() || !Number(input) || !Number(output)}
      >
        Add
      </Button>
    </div>
  );
}
