import { useQuery } from "@tanstack/react-query";
import { api, type Provider } from "@/lib/api";
import { Spinner } from "@/components/ui/Spinner";
import { cn, formatContext, formatUsd } from "@/lib/utils";

/** Models offered by the picker. When a connected provider reports its
 * model list, catalog entries it no longer serves are hidden, unless the
 * user added them as overrides. */
function pickable(p: Provider) {
  const providerReportsList = p.connected && p.models.some((m) => m.listed);
  return p.models.filter(
    (m) => !m.excluded && (!providerReportsList || m.listed || m.overridden),
  );
}

function ProviderStatus({ provider }: { provider: Provider }) {
  switch (provider.status) {
    case "connected":
      // Verified: an authenticated request to the provider succeeded.
      return (
        <span className="text-[0.65rem] uppercase tracking-wide text-success">connected</span>
      );
    case "invalid_key":
      return <span className="text-[0.65rem] text-destructive">key rejected</span>;
    case "unreachable":
      return <span className="text-[0.65rem] text-warning">unreachable</span>;
    default:
      return (
        <span className="text-[0.65rem] text-muted-foreground">
          set {provider.env_var} to enable
        </span>
      );
  }
}

interface Props {
  selected: string[];
  onChange: (models: string[]) => void;
  /** Single-select mode (judge picker). */
  single?: boolean;
}

export function ModelPicker({ selected, onChange, single = false }: Props) {
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.getProviders });

  if (providers.isLoading) return <Spinner />;
  if (!providers.data) {
    return <div className="text-xs text-destructive">Failed to load model catalog.</div>;
  }

  const anyConnected = providers.data.some((p) => p.connected && p.models.length > 0);

  const toggle = (id: string) => {
    if (single) {
      onChange([id]);
      return;
    }
    onChange(selected.includes(id) ? selected.filter((m) => m !== id) : [...selected, id]);
  };

  return (
    <div className="space-y-3">
      {!anyConnected && (
        <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
          No providers are connected. See the Models page to connect one.
        </div>
      )}
      {providers.data
        .filter((p) => p.models.length > 0)
        .map((p) => (
          <div key={p.provider}>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-xs font-medium">{p.provider}</span>
              <ProviderStatus provider={p} />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {pickable(p).map((m) => {
                const active = selected.includes(m.id);
                return (
                  <button
                    key={m.id}
                    type="button"
                    disabled={!p.connected}
                    onClick={() => toggle(m.id)}
                    title={[
                      m.input_per_mtok === null
                        ? "No price set. Runs record $0; set a price on the Models page."
                        : `$${m.input_per_mtok}/M in · $${m.output_per_mtok}/M out`,
                      m.context_length !== null
                        ? `${formatContext(m.context_length)} token context`
                        : null,
                      m.description,
                    ]
                      .filter(Boolean)
                      .join("\n")}
                    className={cn(
                      "rounded-md border px-2.5 py-1 text-xs transition-colors",
                      active
                        ? "border-foreground bg-secondary/60 font-medium"
                        : "hover:bg-secondary/40",
                      !p.connected && "opacity-40 cursor-not-allowed",
                    )}
                  >
                    {m.id}
                    <span className="text-muted-foreground ml-1.5">
                      {m.input_per_mtok === null ? "no price" : `${formatUsd(m.input_per_mtok)}/M`}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
    </div>
  );
}
