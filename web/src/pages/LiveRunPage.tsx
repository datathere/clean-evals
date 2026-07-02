import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

interface RunEvent {
  type: string;
  run_id: string;
  at: string;
  payload: Record<string, unknown>;
}

interface Props {
  runId: string;
  navigate: (path: string) => void;
}

export function LiveRunPage({ runId, navigate }: Props) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const url = `/api/v1/events?run_id=${encodeURIComponent(runId)}`;
    const source = new EventSource(url);

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as RunEvent;
        setEvents((prev) => [event, ...prev].slice(0, 500));
      } catch {
        // ignore malformed
      }
    };
    return () => source.close();
  }, [runId]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          <span className="text-muted-foreground">live</span> {runId}
        </h1>
        <div className="flex items-center gap-2">
          <Badge variant={connected ? "success" : "warning"}>
            <Activity className="size-3 mr-1" />
            {connected ? "connected" : "reconnecting…"}
          </Badge>
          <Button variant="secondary" onClick={() => navigate(`/runs/${runId}`)}>
            Run detail
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader title="Events" subtitle={`${events.length} received`} />
        <CardBody>
          {events.length === 0 ? (
            <div className="text-sm text-muted-foreground py-12 text-center">
              No events yet. They&apos;ll appear here as soon as the worker emits them.
            </div>
          ) : (
            <ul className="text-xs space-y-1 max-h-[60vh] overflow-y-auto scrollbar-thin">
              {events.map((e, i) => (
                <li key={i} className="border-b last:border-0 py-1.5">
                  <span className="text-muted-foreground">{new Date(e.at).toLocaleTimeString()}</span>{" "}
                  <Badge variant="outline">{e.type}</Badge>{" "}
                  <span>{JSON.stringify(e.payload)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
