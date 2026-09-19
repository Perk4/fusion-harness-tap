import { createHash, randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface WriterLease {
	path: string;
	owner: string;
	release(): void;
}

function processAlive(pid: number): boolean {
	if (!Number.isInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch (error: any) {
		return error?.code === "EPERM";
	}
}

function canonicalCwd(cwd: string): string {
	try { return fs.realpathSync.native(cwd); } catch { return path.resolve(cwd); }
}

export function writerLeasePath(cwd: string): string {
	const root = path.join(fs.existsSync("/tmp") ? "/tmp" : os.tmpdir(), "fusion-harness-writer-locks");
	const key = createHash("sha256").update(canonicalCwd(cwd)).digest("hex").slice(0, 24);
	return path.join(root, `${key}.lock`);
}

export function acquireWriterLease(cwd: string, ownerLabel: string): WriterLease {
	const lockPath = writerLeasePath(cwd);
	fs.mkdirSync(path.dirname(lockPath), { recursive: true });
	const owner = `${process.pid}:${randomUUID()}:${ownerLabel}`;
	for (let attempt = 0; attempt < 2; attempt++) {
		try {
			const fd = fs.openSync(lockPath, "wx", 0o600);
			fs.writeFileSync(fd, JSON.stringify({ owner, pid: process.pid, command: ownerLabel, cwd: canonicalCwd(cwd), createdAt: Date.now() }));
			fs.closeSync(fd);
			return {
				path: lockPath,
				owner,
				release() {
					try {
						const current = JSON.parse(fs.readFileSync(lockPath, "utf8"));
						if (current.owner === owner) fs.unlinkSync(lockPath);
					} catch {
						/* already released/replaced */
					}
				},
			};
		} catch (error: any) {
			if (error?.code !== "EEXIST") throw error;
			let existing: any;
			try { existing = JSON.parse(fs.readFileSync(lockPath, "utf8")); } catch {}
			if (existing && processAlive(Number(existing.pid))) {
				throw new Error(`writer lease busy for ${canonicalCwd(cwd)} — ${existing.command ?? existing.owner ?? `pid ${existing.pid}`} is already allowed to mutate this checkout`);
			}
			try { fs.unlinkSync(lockPath); } catch {}
		}
	}
	throw new Error(`could not acquire writer lease for ${canonicalCwd(cwd)}`);
}
