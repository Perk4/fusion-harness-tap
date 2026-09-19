import { describe, expect, test } from "bun:test";
import { computeAgentGridLayout } from "../modules/agent-layout.ts";

describe("AgentGrid layout", () => {
  test("never allocates columns beyond widths 40-300", () => {
    for (let width = 40; width <= 300; width++) {
      for (const count of [2, 3, 4, 5]) {
        const layout = computeAgentGridLayout(width, count, 3, 34);
        expect(layout.count).toBe(count);
        expect(layout.columnWidth).toBeGreaterThan(0);
        if (!layout.stacked) {
          expect(layout.columnWidth * count + layout.gutterWidth * (count - 1)).toBeLessThanOrEqual(width);
          expect(layout.columnWidth).toBeGreaterThanOrEqual(34);
        }
      }
    }
  });

  test("stacks five agents on narrow terminals and keeps columns on wide terminals", () => {
    expect(computeAgentGridLayout(100, 5).stacked).toBe(true);
    expect(computeAgentGridLayout(220, 5).stacked).toBe(false);
  });

  test("stacks three agents below the minimum-per-column threshold", () => {
    expect(computeAgentGridLayout(100, 3).stacked).toBe(true);
    expect(computeAgentGridLayout(108, 3).stacked).toBe(false);
  });
});
