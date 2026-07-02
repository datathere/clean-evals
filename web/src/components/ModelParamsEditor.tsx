import { useQuery } from "@tanstack/react-query";
import { api, type ModelParams } from "@/lib/api";
import { formatUsd } from "@/lib/utils";

interface Props {
  selected: string[];
  params: Record<string, ModelParams>;
  onChange: (params: Record<string, ModelParams>) => void;
  /** Note per model id, e.g. the suggestion reason. */
  notes?: Record<string, string>;
}

/** Per-model parameter inputs, shown for the parameters the model supports. */
export function ModelParamsEditor({ selected, params, onChange, notes }: Props) {
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.getProviders });
  if (!providers.data || selected.length === 0) return null;

  const catalog = new Map(
    providers.data.flatMap((p) => p.models.map((m) => [m.id, m] as const)),
  );
  const rows = selected
    .map((id) => catalog.get(id))
    .filter((m): m is NonNullable<typeof m> => m !== undefined);
  if (rows.length === 0) return null;

  const update = (id: string, patch: Partial<ModelParams>) => {
    const next = { ...params, [id]: { ...params[id], ...patch } };
    onChange(next);
  };

  return (
    <div className="rounded-md border divide-y">
      {rows.map((m) => (
        <div key={m.id} className="px-3 py-2 space-y-1">
          <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs w-56 truncate">
            {m.id}
            <span className="block text-muted-foreground">
              {m.input_per_mtok === null
                ? "no price"
                : `in ${formatUsd(m.input_per_mtok)}/M · out ${formatUsd(m.output_per_mtok)}/M`}
            </span>
          </span>
          {m.capabilities.supports_temperature && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              temperature
              <input
                type="number"
                step="0.1"
                min={0}
                max={2}
                placeholder="0"
                value={params[m.id]?.temperature ?? ""}
                onChange={(e) =>
                  update(m.id, {
                    temperature: e.target.value === "" ? undefined : Number(e.target.value),
                  })
                }
                className="h-7 w-16 rounded-md border bg-background px-1.5 text-xs"
              />
            </label>
          )}
          {m.capabilities.reasoning_efforts.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              effort
              <select
                value={params[m.id]?.reasoning_effort ?? ""}
                onChange={(e) =>
                  update(m.id, {
                    reasoning_effort:
                      e.target.value === ""
                        ? undefined
                        : (e.target.value as ModelParams["reasoning_effort"]),
                  })
                }
                className="h-7 rounded-md border bg-background px-1.5 text-xs"
              >
                <option value="">default</option>
                {m.capabilities.reasoning_efforts.map((eff) => (
                  <option key={eff} value={eff}>
                    {eff}
                  </option>
                ))}
              </select>
            </label>
          )}
          {m.capabilities.supports_max_output_tokens && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              max output tokens
              <input
                type="number"
                min={1}
                placeholder="default"
                value={params[m.id]?.max_output_tokens ?? ""}
                onChange={(e) =>
                  update(m.id, {
                    max_output_tokens:
                      e.target.value === "" ? undefined : Number(e.target.value),
                  })
                }
                className="h-7 w-24 rounded-md border bg-background px-1.5 text-xs"
              />
            </label>
          )}
          </div>
          {notes?.[m.id] && (
            <div className="text-xs text-muted-foreground">{notes[m.id]}</div>
          )}
        </div>
      ))}
    </div>
  );
}
