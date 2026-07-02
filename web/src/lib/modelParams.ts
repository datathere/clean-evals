import type { ModelParams } from "@/lib/api";

/** Drop empty entries before sending. */
export function cleanParams(params: Record<string, ModelParams>): Record<string, ModelParams> {
  const out: Record<string, ModelParams> = {};
  for (const [id, p] of Object.entries(params)) {
    const entry: ModelParams = {};
    if (p.temperature !== undefined) entry.temperature = p.temperature;
    if (p.reasoning_effort !== undefined) entry.reasoning_effort = p.reasoning_effort;
    if (p.max_output_tokens !== undefined) entry.max_output_tokens = p.max_output_tokens;
    if (Object.keys(entry).length > 0) out[id] = entry;
  }
  return out;
}
