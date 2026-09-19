import { join } from "node:path";
import { toStat } from "../../fusion-harness/extensions/fusion-harness/modules/runtime.ts";
import { attachRuntime, loadHarnessConfig, runTurn } from "./primitives.ts";

// runChild re-invokes process.argv[1] with `--mode json`. This file is that entry.
if (isStubPiArgv(process.argv)) {
	process.stdout.write(
		[
			JSON.stringify({ type: "session", id: "stub-session" }),
			JSON.stringify({ type: "tool_execution_start", toolName: "read", args: { path: "README.md" } }),
			JSON.stringify({ type: "tool_execution_end" }),
			JSON.stringify({
				type: "message_end",
				message: {
					role: "assistant",
					content: [{ type: "text", text: "stub: fusion harness turn ok" }],
					stopReason: "stop",
					usage: { input: 1, output: 8, totalTokens: 9 },
				},
			}),
			"",
		].join("\n"),
	);
	process.exit(0);
}

const defaultConfig = join(
	import.meta.dir,
	"../../fusion-harness/.pi/fusion-harness/model-stack-trio.yaml",
);
const configPath = process.argv[2] ?? defaultConfig;
const prompt = process.argv.slice(3).join(" ") || "ping";
const stack = loadHarnessConfig(configPath);
const session = attachRuntime(stack);
const turn = await runTurn(session, prompt);
process.stdout.write(`${JSON.stringify({ output: turn.output, trace: toStat(turn.trace) })}\n`);

function isStubPiArgv(argv: string[]): boolean {
	for (let i = 0; i < argv.length; i++) {
		if (argv[i] === "--mode" && argv[i + 1] === "json") return true;
		if (argv[i] === "--mode=json") return true;
	}
	return false;
}
