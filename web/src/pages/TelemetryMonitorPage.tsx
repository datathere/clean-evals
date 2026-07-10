import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Activity, ShieldQuestion } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { TD, TH, THead, TR, Table } from "@/components/ui/Table";
import { api, type TelemetrySeriesRow } from "@/lib/api";
import { formatPct } from "@/lib/utils";
import { useThemeStore } from "@/lib/theme";

// Categorical series palette, validated with the six-checks script against
// this app's card surfaces (#ffffff light, #171717 dark). Fixed slot order —
// colors follow the model, never its rank. Light slots 2/3/6 sit below 3:1,
// so the legend names every series in text and the table view below is the
// relief channel.
const SERIES_LIGHT = ["#2a78d6", "#1baf7a", "#eda100", "#4a3aa7", "#e34948", "#e87ba4"];
const SERIES_DARK = ["#3987e5", "#199e70", "#c98500", "#9085e9", "#e66767", "#d55181"];
const MAX_SERIES = 6;

interface Props {
  navigate: (path: string) => void;
}

export function TelemetryMonitorPage({ navigate }: Props) {
  const [days, setDays] = useState(30);
  const stats = useQuery({
    queryKey: ["telemetry-stats", days],
    queryFn: () => api.telemetryStats(days),
  });
  const autolock = useQuery({ queryKey: ["telemetry-autolock"], queryFn: api.telemetryAutolock });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-2xl font-semibold tracking-tight">Telemetry monitoring</h1>
        <div className="flex items-center gap-2">
          {[7, 30, 90].map((d) => (
            <Button
              key={d}
              size="sm"
              variant={days === d ? "secondary" : "ghost"}
              onClick={() => setDays(d)}
            >
              {d}d
            </Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => navigate("/telemetry")}>
            Inbox
          </Button>
        </div>
      </div>

      {autolock.data && (
        <Card>
          <CardHeader
            title={
              <span className="inline-flex items-center gap-2">
                <ShieldQuestion className="size-4 text-primary" /> Auto-lock lane
              </span>
            }
          />
          <CardBody className="flex items-center gap-6 flex-wrap text-sm">
            <Badge variant={autolock.data.enabled ? "success" : "default"}>
              {autolock.data.enabled ? "enabled" : "disabled"}
            </Badge>
            {autolock.data.self_disabled && (
              <Badge variant="destructive">self-disabled — overturn rate too high</Badge>
            )}
            <span className="text-muted-foreground">
              {autolock.data.checked} spot checks resolved · {autolock.data.overturned} overturned
              ({formatPct(autolock.data.overturn_rate, 0)}) · disables at{" "}
              {formatPct(autolock.data.disable_threshold, 0)}
            </span>
          </CardBody>
        </Card>
      )}

      {stats.isLoading && <Spinner />}
      {stats.data && stats.data.sources.length === 0 && (
        <div className="py-16 text-center text-sm text-muted-foreground">
          No telemetry in the last {days} days.
        </div>
      )}

      {stats.data && stats.data.sources.length > 0 && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.data.sources.map((s) => (
              <Card key={s.source}>
                <CardBody className="space-y-1">
                  <p className="text-xs text-muted-foreground">{s.source}</p>
                  <p className="text-2xl font-semibold">{formatPct(s.accept_rate, 0)}</p>
                  <p className="text-xs text-muted-foreground">
                    accepted · {s.interactions} interactions
                    {s.mean_turns_to_accept !== null &&
                      ` · ${s.mean_turns_to_accept.toFixed(1)} turns to accept`}
                  </p>
                </CardBody>
              </Card>
            ))}
          </div>

          <div className="grid lg:grid-cols-2 gap-6">
            <MetricChart
              title="Acceptance rate"
              subtitle="share of exchanges accepted, as-is or after edits, per model"
              rows={stats.data.series}
              value={(r) => r.acceptance_rate}
              format={(v) => formatPct(v, 0)}
              domain={[0, 1]}
            />
            <MetricChart
              title="Mean implicit rating"
              subtitle="1–5, derived from edits, follow-ups, and accepts"
              rows={stats.data.series}
              value={(r) => r.mean_rating}
              format={(v) => v.toFixed(2)}
              domain={[1, 5]}
            />
          </div>

          <Card>
            <CardHeader
              title={
                <span className="inline-flex items-center gap-2">
                  <Activity className="size-4 text-primary" /> Daily detail
                </span>
              }
              subtitle="the numbers behind the charts"
            />
            <CardBody className="p-0 overflow-x-auto">
              <Table>
                <THead>
                  <TR>
                    <TH>Date</TH>
                    <TH>Source</TH>
                    <TH>Model</TH>
                    <TH className="text-right">Exchanges</TH>
                    <TH className="text-right">Accepted</TH>
                    <TH className="text-right">Corrected</TH>
                    <TH className="text-right">Mean rating</TH>
                    <TH className="text-right">Regens/exchange</TH>
                    <TH className="text-right">Judge (sampled)</TH>
                  </TR>
                </THead>
                <tbody>
                  {stats.data.series.map((r) => (
                    <TR key={`${r.date}-${r.source}-${r.model}`}>
                      <TD className="tabular-nums text-xs">{r.date}</TD>
                      <TD className="text-xs">{r.source}</TD>
                      <TD className="text-xs">{r.model}</TD>
                      <TD className="text-right tabular-nums">{r.exchanges}</TD>
                      <TD className="text-right tabular-nums">{formatPct(r.acceptance_rate, 0)}</TD>
                      <TD className="text-right tabular-nums">{formatPct(r.correction_rate, 0)}</TD>
                      <TD className="text-right tabular-nums">
                        {r.mean_rating === null ? "—" : r.mean_rating.toFixed(2)}
                      </TD>
                      <TD className="text-right tabular-nums">{r.mean_regens.toFixed(2)}</TD>
                      <TD className="text-right tabular-nums">
                        {r.mean_judge_score === null
                          ? "—"
                          : `${formatPct(r.mean_judge_score, 0)} (${r.judge_scored})`}
                      </TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Line chart: one series per model, hover crosshair + tooltip, legend in text.
// ---------------------------------------------------------------------------

interface ChartProps {
  title: string;
  subtitle: string;
  rows: TelemetrySeriesRow[];
  value: (row: TelemetrySeriesRow) => number | null;
  format: (v: number) => string;
  domain: [number, number];
}

const W = 560;
const H = 220;
const PAD = { top: 12, right: 16, bottom: 24, left: 40 };

function MetricChart({ title, subtitle, rows, value, format, domain }: ChartProps) {
  const { theme } = useThemeStore();
  const palette = theme === "dark" ? SERIES_DARK : SERIES_LIGHT;
  const [hover, setHover] = useState<number | null>(null);

  const { dates, models, points, truncated } = useMemo(() => {
    const byVolume = new Map<string, number>();
    for (const r of rows) byVolume.set(r.model, (byVolume.get(r.model) ?? 0) + r.exchanges);
    const ranked = [...byVolume.entries()].sort((a, b) => b[1] - a[1]).map(([m]) => m);
    const kept = ranked.slice(0, MAX_SERIES);
    const dateList = [...new Set(rows.map((r) => r.date))].sort();
    // model -> date -> weighted value across sources
    const table = new Map<string, Map<string, { sum: number; weight: number }>>();
    for (const r of rows) {
      if (!kept.includes(r.model)) continue;
      const v = value(r);
      if (v === null) continue;
      const perDate = table.get(r.model) ?? new Map();
      const cell = perDate.get(r.date) ?? { sum: 0, weight: 0 };
      cell.sum += v * r.exchanges;
      cell.weight += r.exchanges;
      perDate.set(r.date, cell);
      table.set(r.model, perDate);
    }
    const pts = new Map<string, (number | null)[]>();
    for (const model of kept) {
      const perDate = table.get(model);
      pts.set(
        model,
        dateList.map((d) => {
          const cell = perDate?.get(d);
          return cell && cell.weight > 0 ? cell.sum / cell.weight : null;
        }),
      );
    }
    return {
      dates: dateList,
      models: kept,
      points: pts,
      truncated: ranked.length - kept.length,
    };
  }, [rows, value]);

  const x = (i: number) =>
    PAD.left + (dates.length <= 1 ? 0 : (i / (dates.length - 1)) * (W - PAD.left - PAD.right));
  const y = (v: number) =>
    PAD.top + (1 - (v - domain[0]) / (domain[1] - domain[0])) * (H - PAD.top - PAD.bottom);

  const gridline = theme === "dark" ? "#2c2c2a" : "#e5e5e5";
  const inkMuted = "#898781";

  return (
    <Card>
      <CardHeader title={title} subtitle={subtitle} />
      <CardBody className="space-y-3">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          role="img"
          aria-label={`${title} over time per model`}
          onMouseMove={(e) => {
            if (dates.length < 2) return;
            const rect = e.currentTarget.getBoundingClientRect();
            const px = ((e.clientX - rect.left) / rect.width) * W;
            const idx = Math.round(
              ((px - PAD.left) / (W - PAD.left - PAD.right)) * (dates.length - 1),
            );
            setHover(Math.max(0, Math.min(dates.length - 1, idx)));
          }}
          onMouseLeave={() => setHover(null)}
        >
          {[0, 0.5, 1].map((f) => {
            const v = domain[0] + f * (domain[1] - domain[0]);
            return (
              <g key={f}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke={gridline} />
                <text x={PAD.left - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill={inkMuted}>
                  {format(v)}
                </text>
              </g>
            );
          })}
          {dates.length > 0 && (
            <>
              <text x={x(0)} y={H - 8} fontSize="10" fill={inkMuted}>
                {dates[0]}
              </text>
              <text x={x(dates.length - 1)} y={H - 8} textAnchor="end" fontSize="10" fill={inkMuted}>
                {dates[dates.length - 1]}
              </text>
            </>
          )}
          {models.map((model, mi) => {
            const series = points.get(model) ?? [];
            const segments: string[] = [];
            let current: string[] = [];
            series.forEach((v, i) => {
              if (v === null) {
                if (current.length) segments.push(current.join(" "));
                current = [];
              } else {
                current.push(`${current.length ? "L" : "M"}${x(i)},${y(v)}`);
              }
            });
            if (current.length) segments.push(current.join(" "));
            return (
              <g key={model}>
                {segments.map((d, si) => (
                  <path key={si} d={d} fill="none" stroke={palette[mi]} strokeWidth="2" />
                ))}
                {series.map((v, i) =>
                  v === null ? null : (
                    <circle
                      key={i}
                      cx={x(i)}
                      cy={y(v)}
                      r={hover === i ? 4 : 2.5}
                      fill={palette[mi]}
                      stroke={theme === "dark" ? "#171717" : "#ffffff"}
                      strokeWidth="2"
                    />
                  ),
                )}
              </g>
            );
          })}
          {hover !== null && dates.length > 1 && (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke={inkMuted}
              strokeDasharray="3 3"
            />
          )}
        </svg>

        {hover !== null && (
          <div className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{dates[hover]}</span>
            {models.map((model, mi) => {
              const v = points.get(model)?.[hover];
              if (v === null || v === undefined) return null;
              return (
                <span key={model} className="ml-3 inline-flex items-center gap-1">
                  <span
                    className="inline-block size-2 rounded-full"
                    style={{ backgroundColor: palette[mi] }}
                  />
                  {model}: <span className="text-foreground">{format(v)}</span>
                </span>
              );
            })}
          </div>
        )}

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {models.map((model, mi) => (
            <span key={model} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block size-2.5 rounded-full"
                style={{ backgroundColor: palette[mi] }}
              />
              <span className="text-muted-foreground">{model}</span>
            </span>
          ))}
          {truncated > 0 && (
            <span className="text-muted-foreground">
              +{truncated} more models in the table below
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
