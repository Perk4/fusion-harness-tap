# fusion-harness-tap

Full clone of [disler/fusion-harness](https://github.com/disler/fusion-harness) plus a practical four-primitive example (IndyDevDan / Pi Fusion Harness). Upstream is MIT, copyright IndyDevDan, and lives unmodified at `fusion-harness/`.

**Status.** teach-tap done when this PR is green. expand-demo still open.

## Run the full upstream

```bash
cd fusion-harness
npm install
npm test
cp .env.example .env
```

Fill provider keys, then:

```bash
just fusion
```

See `fusion-harness/README.md` for stacks, commands, and the single-writer rules.

## Run the four-primitive example

```bash
npm install --prefix fusion-harness
bun examples/four-primitives/cli.ts fusion-harness/.pi/fusion-harness/model-stack-trio.yaml ping
bun test examples/four-primitives
```

That example maps `loadHarnessConfig` → `loadModelStack`, `attachRuntime` → session dirs and `SpawnIdentity`, `runTurn` → `runChild`, and `assertHarnessLoop` → one recorded tool trace plus fail-closed attach. CI stubs the child JSON stream because `runChild` re-invokes `cli.ts` instead of calling paid models. Details: `examples/four-primitives/README.md`.
