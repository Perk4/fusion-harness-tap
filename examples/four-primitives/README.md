# Four primitives against Fusion Harness

This example maps four teaching names onto real Fusion Harness modules. It does not replace the harness.

| Teaching name | Real surface |
| --- | --- |
| `loadHarnessConfig(path)` | `loadModelStack` in `fusion-harness/extensions/fusion-harness/modules/model-stack.ts` |
| `attachRuntime(config)` | isolated session dirs plus `SpawnIdentity`, the same shape `runChild` takes |
| `runTurn(session, input)` | `newRun` + `opinionPrompt` + `READONLY_TOOLS` + `runChild` |
| `assertHarnessLoop` | bun tests: one stub turn records a tool trace; missing runtime throws |

## Run the full upstream

Prereqs from the upstream README: [`pi`](https://pi.dev/), [`just`](https://github.com/casey/just), [`bun`](https://bun.sh), `jq`, [`uv`](https://github.com/astral-sh/uv).

```bash
cd fusion-harness
npm install
npm test
cp .env.example .env
```

Fill `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `FIREWORKS_API_KEY`, `OPENAI_API_KEY` as needed. Launch:

```bash
just fusion
```

Or an explicit stack:

```bash
just fh-stack .pi/fusion-harness/model-stack-trio.yaml
```

That path needs provider keys. `npm test` inside `fusion-harness/` does not.

## Run this example

From the tap repo root:

```bash
npm install --prefix fusion-harness
bun examples/four-primitives/cli.ts fusion-harness/.pi/fusion-harness/model-stack-trio.yaml "What is Fusion Harness?"
bun test examples/four-primitives
```

The CLI prints one JSON object with `output` and `trace` (`toStat` of the live `AgentRun`).

## Stub vs live models

`runChild` does not look up `pi` on `PATH` when `process.argv[1]` exists. It re-runs that file with `--mode json`. Under this example, that file is `cli.ts`, so the child is a stub that emits Pi JSON events (a `read` tool call, then assistant text). CI uses that path. There are no API keys.

To attach a real Pi host instead, run the upstream recipes above. `attachRuntime(stack, { runtime: "live" })` throws `fusion-harness: runtime missing` unless `FH_TAP_LIVE=1`.
