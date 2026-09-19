import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadModelStack, orderedSlots, synthesizeLegacyStack } from "../modules/model-stack.ts";

const dirs: string[] = [];
afterEach(() => { while (dirs.length) rmSync(dirs.pop()!, { recursive: true, force: true }); });
function fixture(body: string, name = "model-stack-test.yaml") {
  const dir = mkdtempSync(join(tmpdir(), "fh-stack-test-")); dirs.push(dir);
  const file = join(dir, name); writeFileSync(file, body); return { dir, file };
}

const valid = `
- name: architect
  model: anthropic/claude-fable-5
  architect: true
  thinking: high
  color: "#A78BFA"
- name: main
  model: openai/gpt-5.6-sol
  primary: true
  thinking: xhigh
  color: "#F59E0B"
- name: reviewer
  model: google/gemini-3.6-flash
`;

describe("model stack", () => {
  test("loads and orders architect, Main, then builders", () => {
    const stack = loadModelStack(fixture(valid, "model-stack-trio.yaml").file);
    expect(stack.codename).toBe("trio");
    expect(orderedSlots(stack).map((s) => s.id)).toEqual(["architect", "main", "reviewer"]);
    expect(stack.primaryBuilder.primary).toBe(true);
    expect(stack.architect.primary).toBe(false);
    expect(stack.slots.every((s) => /^#[0-9A-F]{6}$/.test(s.color))).toBe(true);
  });

  test("stable-hash colors are deterministic", () => {
    const a = loadModelStack(fixture(valid, "model-stack-trio.yaml").file);
    const b = loadModelStack(fixture(valid, "model-stack-trio.yaml").file);
    expect(a.slots.map((s) => s.color)).toEqual(b.slots.map((s) => s.color));
  });

  test.each([
    ["no architect", valid.replace("  architect: true\n", "")],
    ["architect primary", valid.replace("  architect: true\n", "  architect: true\n  primary: true\n")],
    ["no primary builder", valid.replace("  primary: true\n", "")],
    ["duplicate names", valid.replace("- name: reviewer", "- name: main")],
    ["bad color", valid.replace('"#F59E0B"', '"amber"')],
    ["unknown key", valid.replace("  primary: true", "  primry: true")],
    ["model whitespace", valid.replace("openai/gpt-5.6-sol", "openai/gpt 5.6 sol")],
  ])("rejects %s", (_label, body) => {
    expect(() => loadModelStack(fixture(body).file)).toThrow("model-stack config invalid");
  });

  test("rejects six slots", () => {
    const extra = [1,2,3].map((n) => `- name: extra${n}\n  model: google/gemini-${n}\n`).join("");
    expect(() => loadModelStack(fixture(valid + extra).file)).toThrow("slot count must be between 2 and 5");
  });

  test("resolves a system prompt relative to YAML", () => {
    const { dir, file } = fixture(valid.replace("  thinking: high", "  thinking: high\n  system_prompt: ./architect.md"));
    writeFileSync(join(dir, "architect.md"), "ARCHITECT CUSTOM");
    expect(loadModelStack(file).architect.systemPrompt).toBe("ARCHITECT CUSTOM");
  });

  test("append_system_prompt accepts one inline entry", () => {
    const { file } = fixture(valid.replace("  thinking: high", "  thinking: high\n  append_system_prompt: Always cite evidence"));
    const stack = loadModelStack(file);
    expect(stack.architect.appendSystemPrompts).toEqual(["Always cite evidence"]);
    expect(stack.architect.systemPrompt).toBeUndefined(); // append never replaces the base
  });

  test("append_system_prompt accepts a list mixing files and inline text, in order", () => {
    const { dir, file } = fixture(
      valid.replace("  thinking: high", "  thinking: high\n  append_system_prompt:\n    - ./house-rules.md\n    - Inline second append"),
    );
    writeFileSync(join(dir, "house-rules.md"), "HOUSE RULES");
    expect(loadModelStack(file).architect.appendSystemPrompts).toEqual(["HOUSE RULES", "Inline second append"]);
  });

  test("append_system_prompt rejects a missing file path", () => {
    const { file } = fixture(valid.replace("  thinking: high", "  thinking: high\n  append_system_prompt: ./missing-append.md"));
    expect(() => loadModelStack(file)).toThrow("append_system_prompt[0]");
  });

  test("legacy stack preserves architect and host builder", () => {
    const stack = synthesizeLegacyStack({ architectModel: "a/model", builderModel: "b/model", architectThinking: "high", builderThinking: "medium" });
    expect(stack.slots).toHaveLength(2);
    expect(stack.primaryBuilder.model).toBe("b/model");
  });
});
