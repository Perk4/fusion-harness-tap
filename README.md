# fusion-harness-tap

Vendored from [Fusion Harness](https://github.com/disler/fusion-harness) (IndyDevDan, MIT) at `fusion-harness/`.

## Status

teach-tap done (CI green on the draft). expand-demo still open.

## Run the vendored harness

```bash
cd fusion-harness
npm install
npm test
```

`just fusion` needs API keys and `pi` on PATH.

## Run the teaching example

```bash
npm install --prefix fusion-harness
bun examples/four-primitives/cli.ts fusion-harness/.pi/fusion-harness/model-stack-trio.yaml "What is Fusion Harness?"
bun test examples/four-primitives
```

See `examples/four-primitives/README.md` for the argv[1] trap and why CI uses the stub.
