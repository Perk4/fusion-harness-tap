import { randomUUID } from "node:crypto";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runChild } from "../../fusion-harness/extensions/fusion-harness/modules/child-runner.ts";
import { loadModelStack, orderedSlots, type ModelStack } from "../../fusion-harness/extensions/fusion-harness/modules/model-stack.ts";
import { opinionPrompt } from "../../fusion-harness/extensions/fusion-harness/modules/prompt-library.ts";
import {
	newRun,
	READONLY_TOOLS,
	type AgentRun,
	type SpawnIdentity,
} from "../../fusion-harness/extensions/fusion-harness/modules/runtime.ts";

export type HarnessConfig = ModelStack;

export type AttachOptions = {
	cwd?: string;
	runtime?: "stub" | "live" | "missing";
	childTimeoutMs?: number;
};

export type HarnessSession = {
	stack: ModelStack;
	cwd: string;
	artifactsDir: string;
	sessionsRoot: string;
	spawnBySlot: Map<string, SpawnIdentity>;
	childTimeoutMs: number;
};

export type TurnInput = string | { prompt: string; slot?: string };

export type TurnResult = {
	output: string;
	trace: AgentRun;
};

export function loadHarnessConfig(path: string): HarnessConfig {
	return loadModelStack(path);
}

export function attachRuntime(stack: ModelStack, options: AttachOptions = {}): HarnessSession {
	if (options.runtime === "missing") {
		throw new Error("fusion-harness: runtime missing");
	}
	if (options.runtime === "live" && process.env.FH_TAP_LIVE !== "1") {
		throw new Error("fusion-harness: runtime missing");
	}

	const cwd = options.cwd ?? process.cwd();
	const base = mkdtempSync(join(tmpdir(), "fh-tap-"));
	const artifactsDir = join(base, "artifacts");
	const sessionsRoot = join(base, "sessions");
	mkdirSync(artifactsDir, { recursive: true });
	mkdirSync(sessionsRoot, { recursive: true });

	const spawnBySlot = new Map<string, SpawnIdentity>();
	for (const slot of orderedSlots(stack)) {
		const sessionDir = join(sessionsRoot, slot.id);
		mkdirSync(sessionDir, { recursive: true });
		spawnBySlot.set(slot.id, { sessionDir, sessionId: randomUUID() });
	}

	return {
		stack,
		cwd,
		artifactsDir,
		sessionsRoot,
		spawnBySlot,
		childTimeoutMs: options.childTimeoutMs ?? 30_000,
	};
}

export async function runTurn(session: HarnessSession, input: TurnInput): Promise<TurnResult> {
	const prompt = typeof input === "string" ? input : input.prompt;
	const slotToken = typeof input === "string" ? undefined : input.slot;
	const slot = slotToken
		? session.stack.slots.find(
				(candidate) => candidate.id === slotToken || candidate.name === slotToken,
			)
		: session.stack.primaryBuilder;
	if (!slot) {
		throw new Error(`fusion-harness: unknown slot ${slotToken}`);
	}
	const spawn = session.spawnBySlot.get(slot.id);
	if (!spawn) {
		throw new Error("fusion-harness: runtime missing");
	}
	const run = newRun(slot.architect ? "ARCHITECT" : "BUILDER", slot.model, slot);
	await runChild({
		run,
		prompt: opinionPrompt(slot, session.stack, prompt),
		systemPrompt: slot.systemPrompt,
		appendSystemPrompts: slot.appendSystemPrompts,
		tools: READONLY_TOOLS,
		thinking: slot.thinking,
		sessionDir: spawn.sessionDir,
		sessionId: spawn.sessionId,
		cwd: session.cwd,
		timeoutMs: session.childTimeoutMs,
	});
	return { output: run.text, trace: run };
}
