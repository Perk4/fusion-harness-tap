import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { acquireWriterLease } from "../modules/writer-lease.ts";

const dirs: string[] = [];
afterEach(() => { while (dirs.length) rmSync(dirs.pop()!, { recursive: true, force: true }); });

describe("CWD writer lease", () => {
  test("allows one writer and rejects a concurrent lease", () => {
    const cwd = mkdtempSync(join(tmpdir(), "fh-writer-lease-")); dirs.push(cwd);
    const first = acquireWriterLease(cwd, "first");
    expect(() => acquireWriterLease(cwd, "second")).toThrow("already allowed to mutate");
    first.release();
    const second = acquireWriterLease(cwd, "second");
    expect(second.owner).not.toBe(first.owner);
    second.release();
  });
});
