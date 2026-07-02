import { describe, expect, it } from "vitest";
import { formatLatency, formatPct, formatScore, formatUsd } from "@/lib/utils";

describe("formatters", () => {
  it("formats currency", () => {
    expect(formatUsd(1.234)).toBe("$1.23");
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(0)).toBe("$0");
    // Sub-cent values keep two significant digits instead of flattening to $0.00.
    expect(formatUsd(0.00055)).toBe("$0.00055");
    expect(formatUsd(0.0001035)).toBe("$0.00010");
  });
  it("formats percent", () => {
    expect(formatPct(0.345)).toBe("34.5%");
  });
  it("formats score", () => {
    expect(formatScore(0.91234)).toBe("0.912");
  });
  it("formats latency", () => {
    expect(formatLatency(450)).toBe("450ms");
    expect(formatLatency(1500)).toBe("1.5s");
  });
});
