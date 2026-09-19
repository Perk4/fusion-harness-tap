import * as fs from "node:fs";

export type CollaborationTaskMode = "read" | "write";

export interface CollaborationTask {
	id: string;
	assignee: string;
	description: string;
	depends_on: string[];
	outputs: string[];
	mode: CollaborationTaskMode;
}

export interface CollaborationPlan {
	tasks: CollaborationTask[];
}

export interface ValidatedCollaborationPlan extends CollaborationPlan {
	waves: CollaborationTask[][];
}

const TASK_ID_RE = /^\d+\.[A-Za-z0-9_-]+$/;

export function readCollaborationPlan(planPath: string, assigneeIds: Iterable<string>): ValidatedCollaborationPlan {
	let parsed: unknown;
	try {
		parsed = JSON.parse(fs.readFileSync(planPath, "utf8"));
	} catch (error) {
		throw new Error(`plan.json could not be read/parsed: ${error instanceof Error ? error.message : String(error)}`);
	}
	return validateCollaborationPlan(parsed, assigneeIds);
}

export function validateCollaborationPlan(input: unknown, assigneeIds: Iterable<string>): ValidatedCollaborationPlan {
	const errors: string[] = [];
	const knownAssignees = new Set(assigneeIds);
	if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("collaboration plan must be a JSON object");
	const rawTasks = (input as Record<string, unknown>).tasks;
	if (!Array.isArray(rawTasks) || rawTasks.length === 0) throw new Error("collaboration plan.tasks must be a non-empty array");

	const tasks: CollaborationTask[] = [];
	const ids = new Set<string>();
	for (let i = 0; i < rawTasks.length; i++) {
		const raw = rawTasks[i];
		const label = `tasks[${i}]`;
		if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
			errors.push(`${label} must be an object`);
			continue;
		}
		const value = raw as Record<string, unknown>;
		const id = typeof value.id === "string" ? value.id.trim() : "";
		if (!TASK_ID_RE.test(id)) errors.push(`${label}.id must look like 1.a, 1.b, 2.a; found ${JSON.stringify(value.id)}`);
		if (ids.has(id)) errors.push(`${label}.id duplicates ${id}`);
		ids.add(id);
		const assignee = typeof value.assignee === "string" ? value.assignee.trim() : "";
		if (!knownAssignees.has(assignee)) errors.push(`${label}.assignee is unknown: ${JSON.stringify(value.assignee)}`);
		const description = typeof value.description === "string" ? value.description.trim() : "";
		if (!description) errors.push(`${label}.description must be a non-empty string`);
		const dependsOn = Array.isArray(value.depends_on) ? value.depends_on.filter((item): item is string => typeof item === "string") : [];
		if (!Array.isArray(value.depends_on)) errors.push(`${label}.depends_on must be an array`);
		else if (value.depends_on.some((item) => typeof item !== "string")) errors.push(`${label}.depends_on entries must all be strings`);
		if (dependsOn.includes(id)) errors.push(`${label} cannot depend on itself`);
		const outputs = value.outputs === undefined ? [] : Array.isArray(value.outputs) ? value.outputs.filter((item): item is string => typeof item === "string") : [];
		if (value.outputs !== undefined && !Array.isArray(value.outputs)) errors.push(`${label}.outputs must be an array when present`);
		else if (Array.isArray(value.outputs) && value.outputs.some((item) => typeof item !== "string")) errors.push(`${label}.outputs entries must all be strings`);
		const mode: CollaborationTaskMode = value.mode === "read" ? "read" : "write";
		if (value.mode !== undefined && value.mode !== "read" && value.mode !== "write") errors.push(`${label}.mode must be read or write`);
		tasks.push({ id, assignee, description, depends_on: dependsOn, outputs, mode });
	}

	const byId = new Map(tasks.map((task) => [task.id, task]));
	for (const task of tasks) {
		for (const dep of task.depends_on) if (!byId.has(dep)) errors.push(`${task.id} depends on unknown task ${dep}`);
	}
	if (errors.length) throw new Error(errors.join("\n"));

	// Waves are dependency LEVELS: cycle detection plus a readable parallelism preview.
	// They are not an execution schedule — the harness runs on per-task readiness, and a
	// slot may own several tasks in one level (its session simply runs them one at a time).
	const remaining = new Map(tasks.map((task) => [task.id, task]));
	const completed = new Set<string>();
	const waves: CollaborationTask[][] = [];
	while (remaining.size) {
		const wave = [...remaining.values()].filter((task) => task.depends_on.every((dep) => completed.has(dep)));
		if (!wave.length) {
			throw new Error(`collaboration plan contains a dependency cycle involving: ${[...remaining.keys()].join(", ")}`);
		}
		waves.push(wave);
		for (const task of wave) {
			remaining.delete(task.id);
			completed.add(task.id);
		}
	}
	return { tasks, waves };
}
