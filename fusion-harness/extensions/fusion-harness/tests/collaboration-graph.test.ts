import { describe, expect, test } from "bun:test";
import { validateCollaborationPlan } from "../modules/collaboration-graph.ts";

const slots = ["architect", "main", "reviewer"];

describe("collaboration graph", () => {
  test("builds dependency waves", () => {
    const plan = validateCollaborationPlan({ tasks: [
      { id: "1.a", assignee: "architect", description: "design", depends_on: [], mode: "read" },
      { id: "1.b", assignee: "main", description: "implement core", depends_on: [], outputs: ["core.ts"], mode: "write" },
      { id: "2.a", assignee: "reviewer", description: "integrate", depends_on: ["1.a", "1.b"], mode: "write" },
    ]}, slots);
    expect(plan.waves.map((wave) => wave.map((task) => task.id))).toEqual([["1.a", "1.b"], ["2.a"]]);
  });

  test("defaults mode to write", () => {
    const plan = validateCollaborationPlan({ tasks: [{ id: "1.a", assignee: "main", description: "ship", depends_on: [] }] }, slots);
    expect(plan.tasks[0].mode).toBe("write");
  });

  test("rejects unknown assignees", () => {
    expect(() => validateCollaborationPlan({ tasks: [{ id: "1.a", assignee: "ghost", description: "x", depends_on: [] }] }, slots)).toThrow("unknown");
  });

  test("rejects mixed-type dependency and output entries instead of dropping them", () => {
    expect(() => validateCollaborationPlan({ tasks: [
      { id: "1.a", assignee: "main", description: "a", depends_on: [123], outputs: ["ok", false] },
    ]}, slots)).toThrow("entries must all be strings");
  });

  test("rejects cycles", () => {
    expect(() => validateCollaborationPlan({ tasks: [
      { id: "1.a", assignee: "main", description: "a", depends_on: ["1.b"] },
      { id: "1.b", assignee: "reviewer", description: "b", depends_on: ["1.a"] },
    ]}, slots)).toThrow("cycle");
  });

  test("allows two same-slot tasks in one dependency level (scheduler serializes per slot)", () => {
    const plan = validateCollaborationPlan({ tasks: [
      { id: "1.a", assignee: "main", description: "a", depends_on: [] },
      { id: "1.b", assignee: "main", description: "b", depends_on: [] },
    ]}, slots);
    expect(plan.waves.map((wave) => wave.map((task) => task.id))).toEqual([["1.a", "1.b"]]);
  });
});
