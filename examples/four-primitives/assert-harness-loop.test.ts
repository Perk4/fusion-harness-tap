import { describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { attachRuntime, loadHarnessConfig } from "./primitives.ts";

const repoRoot = join(import.meta.dir, "../..");
const trioYaml = join(repoRoot, "fusion-harness/.pi/fusion-harness/model-stack-trio.yaml");
const cliPath = join(import.meta.dir, "cli.ts");

describe("assertHarnessLoop", () => {
	test("missing runtime fails closed", () => {
		const stack = loadHarnessConfig(trioYaml);
		expect(() => attachRuntime(stack, { runtime: "missing" })).toThrow(/runtime missing/);
	});

	test("one turn records tools and trace", () => {
		const result = spawnSync(process.execPath, [cliPath, trioYaml, "ping"], {
			encoding: "utf-8",
			cwd: repoRoot,
		});
		expect(result.status).toBe(0);
		expect(result.stderr).toBe("");
		const parsed = JSON.parse(result.stdout) as {
			output: string;
			trace: { toolCalls: number; toolNames: string[]; status: string };
		};
		expect(parsed.output).toBe("stub: fusion harness turn ok");
		expect(parsed.trace.status).toBe("done");
		expect(parsed.trace.toolCalls).toBe(1);
		expect(parsed.trace.toolNames).toEqual(["read"]);
	});
});
