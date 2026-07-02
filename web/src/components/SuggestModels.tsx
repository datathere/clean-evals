import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { api, type ModelPick } from "@/lib/api";

interface Props {
  datasetId: number;
  onPicked: (picks: ModelPick[]) => void;
}

/** Suggests two cheap, two medium, two expensive models for the dataset's task. */
export function SuggestModels({ datasetId, onPicked }: Props) {
  const [pickedBy, setPickedBy] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const suggest = useMutation({
    mutationFn: () => api.suggestModels(datasetId),
    onSuccess: (data) => {
      setError(null);
      setPickedBy(data.picked_by);
      onPicked(data.picks);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="flex items-center gap-3">
      <Button
        size="sm"
        variant="outline"
        onClick={() => suggest.mutate()}
        disabled={suggest.isPending}
      >
        {suggest.isPending ? <Spinner /> : <Sparkles className="size-3.5" />}
        Suggest models
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
      {pickedBy !== undefined && !error && (
        <span className="text-xs text-muted-foreground">
          {pickedBy ? `Picked by ${pickedBy}. Adjust as needed.` : "Picked by price tier."}
        </span>
      )}
    </div>
  );
}
