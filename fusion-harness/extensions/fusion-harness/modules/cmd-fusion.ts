/**
 * cmd-fusion.ts — /fh-fusion: N read-only sources → one sole-writer FUSION → context ACKs.
 *
 * Every configured slot researches concurrently with read-only tools; one fresh
 * temporary FUSION agent (full tools, CWD writer lease) merges and implements; then
 * the complete fused result synchronizes to every slot, each returning an exact
 * `ACK FUSION <run-id>` with a shared SHA-256 over the fused bytes.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runChild } from "./child-runner.ts";
import { orderedSlots } from "./model-stack.ts";
import {
	contractSystemPrompt,
	defaultFusionPrompt,
	fuserPrompt,
	fusionContextAckPrompt,
	parseFusionArgs,
	workerPrompt,
} from "./prompt-library.ts";
import {
	CUSTOM_TYPE,
	FULL_TOOLS,
	newRun,
	READONLY_TOOLS,
	runError,
	runOk,
	splitUtf8,
	toStat,
	type AgentRun,
	type FhDetails,
	type HarnessDeps,
	type Role,
	type SpawnIdentity,
} from "./runtime.ts";
import { acquireWriterLease, type WriterLease } from "./writer-lease.ts";

export function registerFusionCommand(pi: ExtensionAPI, h: HarnessDeps): void {
	pi.registerCommand("fh-fusion", {
		description: 'All configured agents research in parallel read-only; one fresh FUSION agent merges/builds, then every slot acknowledges the fused context.',
		handler: async (raw, ctx) => {
			h.noteHost(ctx);
			const input = (raw ?? "").trim();
			if (!input) {
				ctx.ui.notify('Usage: /fh-fusion "<prompt>" "<fusion-prompt>"  (or: /fh-fusion <prompt> :: <fusion-prompt>)', "warning");
				return;
			}
			const parsed = parseFusionArgs(input);
			const prompt = parsed.prompt;
			const fusionInstruction = parsed.fusion || defaultFusionPrompt();
			const stack = h.modelStack();
			const slots = orderedSlots(stack);
			const startedAt = Date.now();
			const artifactsDir = await h.mkArtifacts();
			await h.save(artifactsDir, "prompt.md", `${prompt}\n\nFUSION INSTRUCTION:\n${fusionInstruction}`);
			await h.save(artifactsDir, "stack.json", JSON.stringify(stack, null, 2));
			await fs.promises.mkdir(path.join(artifactsDir, "agents"), { recursive: true });

			h.panel({ kind: "prompt", command: "fh-fusion", ok: true }, `/fh-fusion ${input}`);
			h.panel({ kind: "banner", command: "fh-fusion", ok: true, prompt, fusionPrompt: fusionInstruction, roles: [...slots.map((slot) => ({ role: (slot.architect ? "ARCHITECT" : "BUILDER") as Role, model: slot.model, slotId: slot.id, slotName: slot.name, color: slot.color, primary: slot.primary, architect: slot.architect })), { role: "FUSION" as Role, model: stack.architect.model }], artifactsDir }, "");

			const runs = slots.map(h.newSlotRun);
			const initialSpawns = new Map(slots.map((slot) => [slot.id, h.slotInitialSpawn(slot, ctx, path.join(artifactsDir, "agents", slot.id))]));
			const fuser = newRun("FUSION", stack.architect.model);
			const stopper = h.startStoppable(ctx, "fh-fusion");
			const stopWidget = h.startGridWidget(ctx, "fh-fusion", runs, fuser, startedAt);
			let writerLease: WriterLease | undefined;
			let hostContextChunks = 0;
			const ackRuns: AgentRun[] = []; // every ACK attempt — absorbed into the model bar after the widget stops
			ctx.ui.setStatus(CUSTOM_TYPE, `fusion: ${runs.length} read-only agents researching…`);

			try {
				await Promise.all(runs.map(async (run) => {
					const slot = run.slot!;
					const agentDir = path.join(artifactsDir, "agents", slot.id);
					await fs.promises.mkdir(agentDir, { recursive: true });
					await runChild({ run, prompt: workerPrompt(slot, stack, prompt), systemPrompt: slot.systemPrompt, appendSystemPrompts: slot.appendSystemPrompts, tools: READONLY_TOOLS, thinking: slot.thinking, ...initialSpawns.get(slot.id)!, cwd: ctx.cwd, timeoutMs: h.childTimeoutMs(), signal: stopper.signal });
					await h.save(agentDir, "answer.md", runOk(run) ? run.text : `FAILED: ${runError(run)}`);
				}));
				if (stopper.stopped()) {
					h.stoppedPanel("fh-fusion", runs, artifactsDir, startedAt, "All active source agents were stopped; completed source artifacts remain on disk.");
					return;
				}

				const sourceManifest = runs.map((run) => ({ slot: run.slot!.id, name: run.slot!.name, model: run.model, status: run.status, ok: runOk(run), artifact: path.join(artifactsDir, "agents", run.slot!.id, "answer.md"), error: runOk(run) ? undefined : runError(run) }));
				await h.save(artifactsDir, "source-manifest.json", JSON.stringify(sourceManifest, null, 2));
				h.panel({ kind: "multi", command: "fh-fusion", title: "READ-ONLY SOURCE RESULTS", ok: runs.every(runOk), prompt, sources: runs.map(toStat), answers: runs.map((run) => ({ role: run.role, model: run.model, text: runOk(run) ? run.text : `FAILED: ${runError(run)}`, slotId: run.slot!.id, slotName: run.slot!.name, color: run.slot!.color, primary: run.slot!.primary })), artifactsDir, ...h.totals(runs, startedAt) }, runs.map((run) => `## ${run.slot!.name}\n${runOk(run) ? run.text : `FAILED: ${runError(run)}`}`).join("\n\n"));

				const successful = runs.filter(runOk);
				if (successful.length < 2) {
					h.panel({ kind: "error", command: "fh-fusion", ok: false, sources: runs.map(toStat), artifactsDir, ...h.totals(runs, startedAt) }, `FUSION did not run: at least 2 successful sources are required; found ${successful.length}.`);
					return;
				}

				try {
					writerLease = acquireWriterLease(ctx.cwd, `/fh-fusion ${path.basename(artifactsDir)}`);
				} catch (error) {
					h.panel({ kind: "error", command: "fh-fusion", ok: false, sources: runs.map(toStat), artifactsDir }, error instanceof Error ? error.message : String(error));
					return;
				}
				ctx.ui.setStatus(CUSTOM_TYPE, "fusion: temporary sole-writer agent merging and implementing…");
				await runChild({ run: fuser, prompt: fuserPrompt(fusionInstruction, prompt, runs, fuser.model, stack.architect.thinking, artifactsDir), systemPrompt: contractSystemPrompt(stack.architect.systemPrompt, "SYSTEM_PROMPT_FUSION.md"), appendSystemPrompts: stack.architect.appendSystemPrompts, tools: FULL_TOOLS, thinking: stack.architect.thinking, sessionDir: path.join(artifactsDir, "fusion"), cwd: ctx.cwd, timeoutMs: h.childTimeoutMs(), signal: stopper.signal });
				if (stopper.stopped()) {
					h.stoppedPanel("fh-fusion", [...runs, fuser], artifactsDir, startedAt, "The temporary FUSION writer was stopped; source work remains on disk.");
					return;
				}
				await h.save(artifactsDir, "fused.md", runOk(fuser) ? fuser.text : `FAILED: ${runError(fuser)}`);
				if (!runOk(fuser)) {
					h.panel({ kind: "error", command: "fh-fusion", ok: false, agent: toStat(fuser), sources: runs.map(toStat), artifactsDir, ...h.totals([...runs, fuser], startedAt) }, `Sources completed, but the temporary FUSION agent failed: ${runError(fuser)}`);
					return;
				}

				// Render/persist the fused result into the host context before the Main ACK fork.
				// Pi custom messages are size-capped, so oversized results use one visible head
				// plus hidden continuation messages; together they retain every byte for raw Main.
				const fusedChunks = splitUtf8(fuser.text, 80_000);
				hostContextChunks = fusedChunks.length;
				h.panel({ kind: "fused", command: "fh-fusion", ok: true, prompt, fusionPrompt: fusionInstruction, agent: toStat(fuser), sources: runs.map(toStat), artifactsDir, ...h.totals([...runs, fuser], startedAt) }, fusedChunks[0] + (fusedChunks.length > 1 ? `\n\n… ${fusedChunks.length - 1} complete continuation chunk(s) added invisibly to Main context` : ""));
				for (let index = 1; index < fusedChunks.length; index++) {
					pi.sendMessage<FhDetails>({ customType: CUSTOM_TYPE, content: `[FUSED RESULT CONTINUATION ${index + 1}/${fusedChunks.length}]\n${fusedChunks[index]}`, display: false, details: { kind: "sync", command: "fh-fusion", ok: true, artifactsDir } });
				}
				await h.save(artifactsDir, "fusion-context.md", fuser.text);

				const runId = path.basename(artifactsDir);
				const ackSpec = fusionContextAckPrompt(runId, fuser.text);
				let mainContextRoute = "host-memory+pinned-ack";
				try {
					const hostFile = ctx.sessionManager.getSessionFile?.();
					if (hostFile && fs.existsSync(hostFile) && fs.statSync(hostFile).size > 0) mainContextRoute = "persisted-host+fork-ack";
				} catch {}
				const acknowledgements: Array<{ slot: string; model: string; status: "acknowledged" | "failed"; route: string; response: string; error?: string }> = [];
				await fs.promises.mkdir(path.join(artifactsDir, "acks"), { recursive: true });
				ctx.ui.setStatus(CUSTOM_TYPE, `fusion: synchronizing context to ${slots.length} agents…`);

				await Promise.all(slots.map(async (slot) => {
					const sourceRun = runs.find((run) => run.slot!.id === slot.id)!;
					const ackRun = h.newSlotRun(slot);
					const sourceInitial = initialSpawns.get(slot.id)!;
					const identity = slot.primary ? h.slotInitialSpawn(slot, ctx, path.join(artifactsDir, "acks", slot.id)) : h.slotNextSpawn(slot, sourceRun, sourceInitial, ctx);
					await runChild({ run: ackRun, prompt: ackSpec.prompt, systemPrompt: slot.systemPrompt, appendSystemPrompts: slot.appendSystemPrompts, tools: "none", thinking: slot.thinking, ...identity, cwd: ctx.cwd, timeoutMs: h.childTimeoutMs(), signal: stopper.signal });
					let finalRun = ackRun;
					const expected = `ACK FUSION ${runId}`;
					if (!runOk(finalRun) || finalRun.text.trim() !== expected) {
						const retry = h.newSlotRun(slot);
						const retryIdentity: SpawnIdentity = finalRun.sessionRef ? { sessionDir: identity.sessionDir, resume: finalRun.sessionRef } : identity;
						await runChild({ run: retry, prompt: ackSpec.prompt, systemPrompt: slot.systemPrompt, appendSystemPrompts: slot.appendSystemPrompts, tools: "none", thinking: slot.thinking, ...retryIdentity, cwd: ctx.cwd, timeoutMs: h.childTimeoutMs(), signal: stopper.signal });
						finalRun = retry;
					}
					// Both attempts spent real tokens; the FINAL one carries the slot's post-sync
					// context reading, so it is pushed last and wins the remembered bar state.
					ackRuns.push(ackRun);
					if (finalRun !== ackRun) ackRuns.push(finalRun);
					const acknowledged = runOk(finalRun) && finalRun.text.trim() === expected && finalRun.toolCalls === 0;
					const record = { slot: slot.id, model: slot.model, status: (acknowledged ? "acknowledged" : "failed") as "acknowledged" | "failed", route: slot.primary ? mainContextRoute : "persistent-slot-session", response: finalRun.text, error: acknowledged ? undefined : runError(finalRun) || `expected exact ${expected}` };
					acknowledgements.push(record);
					await h.save(path.join(artifactsDir, "acks"), `${slot.id}.md`, `${record.status.toUpperCase()}\nmodel: ${slot.model}\nroute: ${record.route}\nhash: ${ackSpec.hash}\nresponse: ${record.response || "(none)"}\n${record.error ? `error: ${record.error}` : ""}`);
				}));

				const syncOk = acknowledgements.length === slots.length && acknowledgements.every((ack) => ack.status === "acknowledged");
				h.panel({ kind: "sync", command: "fh-fusion", ok: syncOk, sources: runs.map(toStat), artifactsDir, ...h.totals([...runs, fuser], startedAt) }, [`fused sha256: ${ackSpec.hash}`, ...orderedSlots(stack).map((slot) => { const ack = acknowledgements.find((item) => item.slot === slot.id); return `${ack?.status === "acknowledged" ? "✓" : "✗"} ${slot.name} · ${slot.model} · ${ack?.status ?? "missing"} · ${ack?.route ?? "no-route"}`; })].join("\n"));
				await h.save(artifactsDir, "summary.json", JSON.stringify({ command: "fh-fusion", ok: syncOk, fusionOk: true, contextSync: acknowledgements, fusedHash: ackSpec.hash, hostContextChunks, writerLeasePath: writerLease?.path, agents: [...runs, fuser].map(toStat), sessions: Object.fromEntries(slots.map((slot) => [slot.id, runs.find((run) => run.slot?.id === slot.id)?.sessionRef ?? h.cachedSlotId(slot)])), ...h.totals([...runs, fuser], startedAt) }, null, 2));
			} finally {
				await h.ensureSummary(artifactsDir, { command: "fh-fusion", ok: false, stopped: stopper.stopped(), hostContextChunks, agents: [...runs, fuser].map(toStat), sessions: Object.fromEntries(slots.map((slot) => [slot.id, runs.find((run) => run.slot?.id === slot.id)?.sessionRef ?? h.cachedSlotId(slot)])), ...h.totals([...runs, fuser], startedAt) });
				writerLease?.release();
				stopper.release();
				stopWidget();
				// AFTER stopWidget: the widget absorbs the runs it was started with (workers +
				// fuser) — folding the ACK turns in last leaves each slot's remembered context
				// bar on its post-sync session, not the smaller read-only research turn.
				h.absorbRuns(ackRuns);
				ctx.ui.setStatus(CUSTOM_TYPE, undefined);
			}
		},
	});
}
