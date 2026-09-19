import { describe, expect, test } from "bun:test";
import { join } from "node:path";
import { attachRuntime, loadHarnessConfig } from "./primitives.ts";

const trioYaml = join(import.meta.dir, "../../fusion-harness/.pi/fusion-harness/model-stack-trio.yaml");

describe("four primitives smoke", () => {
	test("loadHarnessConfig reads the trio stack", () => {
		const stack = loadHarnessConfig(trioYaml);
		expect(stack.codename).toBe("trio");
		expect(stack.primaryBuilder.id).toBe("sol");
		expect(stack.architect.name).toBe("fable");
		expect(stack.architect.architect).toBe(true);
		expect(stack.slots.map((slot) => slot.id)).toEqual(["fable", "sol", "terra"]);
	});

	test("loadHarnessConfig fails closed on a missing file", () => {
		expect(() => loadHarnessConfig("/no/such/fusion-harness-stack.yaml")).toThrow(
			/model-stack config invalid/,
		);
	});

	test("attachRuntime mints one spawn identity per slot", () => {
		const session = attachRuntime(loadHarnessConfig(trioYaml));
		expect(session.stack.codename).toBe("trio");
		expect([...session.spawnBySlot.keys()]).toEqual(["fable", "sol", "terra"]);
	});
});
