import { useEffect, useState } from "react";
import { Layout } from "@/components/Layout";
import { CostProjectionPage } from "@/pages/CostProjectionPage";
import { DatasetBuilderPage } from "@/pages/DatasetBuilderPage";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { LiveRunPage } from "@/pages/LiveRunPage";
import { ModelsPage } from "@/pages/ModelsPage";
import { RunDetailPage } from "@/pages/RunDetailPage";
import { RunsPage } from "@/pages/RunsPage";
import { SchedulesPage } from "@/pages/SchedulesPage";
import { useTheme } from "@/lib/theme";

type Route =
  | { name: "datasets" }
  | { name: "runs"; datasetId?: number }
  | { name: "run-detail"; runId: string }
  | { name: "live"; runId: string }
  | { name: "cost"; runId: string }
  | { name: "builder"; datasetId?: number }
  | { name: "models" }
  | { name: "schedules" };

function parseRoute(path: string, search: string): Route {
  const segments = path.split("/").filter(Boolean);
  const params = new URLSearchParams(search);
  if (segments.length === 0 || segments[0] === "datasets") return { name: "datasets" };
  if (segments[0] === "runs" && segments[1])
    return { name: "run-detail", runId: segments[1] };
  if (segments[0] === "runs") {
    const datasetId = params.get("dataset_id");
    return { name: "runs", datasetId: datasetId ? Number(datasetId) : undefined };
  }
  if (segments[0] === "live" && segments[1])
    return { name: "live", runId: segments[1] };
  if (segments[0] === "cost" && segments[1])
    return { name: "cost", runId: segments[1] };
  if (segments[0] === "builder")
    return { name: "builder", datasetId: segments[1] ? Number(segments[1]) : undefined };
  if (segments[0] === "models") return { name: "models" };
  if (segments[0] === "schedules") return { name: "schedules" };
  return { name: "datasets" };
}

export default function App() {
  useTheme();
  const [route, setRoute] = useState<Route>(() =>
    parseRoute(window.location.pathname, window.location.search),
  );

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname, window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = (path: string) => {
    window.history.pushState(null, "", path);
    const [pathname, search = ""] = path.split("?");
    setRoute(parseRoute(pathname, search));
  };

  return (
    <Layout currentRoute={route.name} navigate={navigate}>
      {route.name === "datasets" && <DatasetsPage navigate={navigate} />}
      {route.name === "runs" && <RunsPage navigate={navigate} datasetId={route.datasetId} />}
      {route.name === "run-detail" && (
        <RunDetailPage runId={route.runId} navigate={navigate} />
      )}
      {route.name === "live" && <LiveRunPage runId={route.runId} navigate={navigate} />}
      {route.name === "cost" && <CostProjectionPage runId={route.runId} />}
      {route.name === "builder" && (
        <DatasetBuilderPage datasetId={route.datasetId} navigate={navigate} />
      )}
      {route.name === "models" && <ModelsPage />}
      {route.name === "schedules" && <SchedulesPage />}
    </Layout>
  );
}
