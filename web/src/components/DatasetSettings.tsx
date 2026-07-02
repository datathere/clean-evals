import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ModelPicker } from "@/components/ModelPicker";
import { api, type Dataset } from "@/lib/api";

/** View and edit the dataset's prompt spec and scorer configuration. */
export function DatasetSettings({ dataset }: { dataset: Dataset }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(dataset.system_prompt ?? "");
  const [sharedContext, setSharedContext] = useState(dataset.shared_context ?? "");
  const [userTemplate, setUserTemplate] = useState(dataset.user_template ?? "");
  const [field, setField] = useState(String(dataset.scorer_config.field ?? ""));
  const [judgeModel, setJudgeModel] = useState<string[]>(
    dataset.scorer_config.judge_model ? [String(dataset.scorer_config.judge_model)] : [],
  );
  const [passThreshold, setPassThreshold] = useState(
    String(dataset.scorer_config.pass_threshold ?? "0.7"),
  );
  const [rubric, setRubric] = useState(String(dataset.scorer_config.rubric ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () => {
      const scorerConfig: Record<string, unknown> = { ...dataset.scorer_config };
      if (dataset.scorer === "exact_match" || dataset.scorer === "json_field_match") {
        if (field.trim()) scorerConfig.field = field.trim();
        else delete scorerConfig.field;
      }
      if (dataset.scorer === "llm_judge") {
        if (judgeModel[0]) scorerConfig.judge_model = judgeModel[0];
        scorerConfig.pass_threshold = Number(passThreshold);
        if (rubric.trim()) scorerConfig.rubric = rubric.trim();
        else delete scorerConfig.rubric;
      }
      return api.editSettings(dataset.id, {
        system_prompt: systemPrompt,
        shared_context: sharedContext,
        user_template: userTemplate,
        scorer_config: scorerConfig,
      });
    },
    onSuccess: (updated) => {
      setError(null);
      setSaved(true);
      qc.setQueryData(["dataset", dataset.id], updated);
      qc.invalidateQueries({ queryKey: ["preview", dataset.id] });
    },
    onError: (e: Error) => {
      setSaved(false);
      setError(
        e.message.includes("409")
          ? "Runs reference this version. Create a new version to edit settings."
          : e.message,
      );
    },
  });

  const locked = dataset.has_runs;

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Settings2 className="size-4" /> Settings
          </span>
        }
        subtitle={
          locked
            ? "Read-only: runs reference this version. Create a new version to edit."
            : undefined
        }
        right={
          <Button size="sm" variant="outline" onClick={() => setOpen(!open)}>
            {open ? "Hide" : "Show"}
          </Button>
        }
      />
      {open && (
        <CardBody className="space-y-4">
          {dataset.request_shape === "templated" && (
            <>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">System prompt</span>
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  disabled={locked}
                  className="min-h-20 rounded-md border bg-background p-3 text-sm disabled:opacity-60"
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  Context (optional)
                </span>
                <textarea
                  value={sharedContext}
                  onChange={(e) => setSharedContext(e.target.value)}
                  disabled={locked}
                  className="min-h-16 rounded-md border bg-background p-3 text-sm disabled:opacity-60"
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  User message template (optional; defaults to context then case)
                </span>
                <input
                  value={userTemplate}
                  onChange={(e) => setUserTemplate(e.target.value)}
                  disabled={locked}
                  placeholder="{context}\n\n{case}"
                  className="h-9 rounded-md border bg-background px-3 text-sm disabled:opacity-60"
                />
              </label>
            </>
          )}

          <div className="text-xs font-medium text-muted-foreground">
            Scorer: {dataset.scorer}
          </div>
          {(dataset.scorer === "exact_match" || dataset.scorer === "json_field_match") && (
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                Expected field to compare (optional)
              </span>
              <input
                value={field}
                onChange={(e) => setField(e.target.value)}
                disabled={locked}
                placeholder="label"
                className="h-9 w-64 rounded-md border bg-background px-3 text-sm disabled:opacity-60"
              />
            </label>
          )}
          {dataset.scorer === "llm_judge" && (
            <>
              <div className="space-y-2">
                <span className="text-xs font-medium text-muted-foreground">Judge model</span>
                <ModelPicker selected={judgeModel} onChange={setJudgeModel} single />
              </div>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">
                  Pass threshold (0 to 1)
                </span>
                <input
                  value={passThreshold}
                  onChange={(e) => setPassThreshold(e.target.value)}
                  disabled={locked}
                  className="h-9 w-24 rounded-md border bg-background px-3 text-sm disabled:opacity-60"
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-muted-foreground">Rubric</span>
                <textarea
                  value={rubric}
                  onChange={(e) => setRubric(e.target.value)}
                  disabled={locked}
                  className="min-h-28 rounded-md border bg-background p-3 text-xs disabled:opacity-60"
                />
              </label>
            </>
          )}

          {!locked && (
            <div className="flex items-center gap-3">
              <Button onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending && <Spinner />}
                Save settings
              </Button>
              {saved && !save.isPending && (
                <span className="text-xs text-success">Saved.</span>
              )}
            </div>
          )}
          {error && <div className="text-xs text-destructive">{error}</div>}
        </CardBody>
      )}
    </Card>
  );
}
