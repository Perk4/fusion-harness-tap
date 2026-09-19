---
description: Install and verify the fusion-harness toolchain (pi, just, jq, uv, Node deps, model auth)
---

# Purpose

Install everything the 2–5 model fusion-harness needs and verify both legacy and YAML-stack launches.

## Workflow

1. Check prerequisite binaries and install missing ones:
   - `pi` — `npm install -g @earendil-works/pi-coding-agent`
   - `just`, `jq`, `uv` — `brew install just jq uv` (macOS) or the user's package manager
   - `bun` — required for deterministic tests
2. Run `npm install` at the repo root to install the explicit `yaml` parser dependency.
3. Check `.env` for non-placeholder credentials required by every model in the selected stack. Never invent, display, or commit keys. Gotchas:
   - pi reads `GEMINI_API_KEY` for the google provider — `GOOGLE_GENERATIVE_AI_API_KEY` is NOT consulted.
   - The `fusion`/`fusion5` stacks need `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and `FIREWORKS_API_KEY`; the trio/legacy pairs need `OPENAI_API_KEY`.
   - Exported shell variables override justfile dotenv values.
4. Confirm these load paths exist:
   - `extensions/fusion-harness/fusion-harness.ts`
   - `extensions/fusion-harness/modules/{runtime,child-runner,prompt-library,tui,cmd-readonly,cmd-fusion,cmd-build,model-stack,agent-layout,collaboration-graph,writer-lease}.ts`
   - `extensions/fusion-harness/prompts/{SYSTEM,USER}_PROMPT_*.md`
   - `.pi/fusion-harness/model-stack-{fusion,fusion-5,trio}.yaml`
5. Run `npm test` (34 deterministic tests), `git diff --check`, and `pi -e extensions/fusion-harness/fusion-harness.ts --list-models`.
6. Launch one stack (startup validates registration, auth, and clean-room child visibility for every slot, then makes the primary slot the host):
   - `just fusion` — cross-provider trio (Fable architect + Gemini Main + DeepSeek)
   - `just fusion5` — 5-slot maximum (fusion trio + Kimi K3 + DeepSeek V4 Flash)
   - `just fh-stack .pi/fusion-harness/model-stack-trio.yaml` — explicit stack path
   - `just fh-workhorse` / `just fh-sota` — legacy two-slot mode
7. Confirm the boot banner shows one colored circle per configured slot, `/fh on` renders one model-bar row per slot (`role | name | model (thk) | context | tps | cost`), and `/fh-system-prompt` renders the responsive grid.
8. If the user wants the demo workspace: `../fusion-harness-v2-playground` has its own justfile (same recipes plus `prompt N` and `clean`), an `.env` symlink to this repo's `.env`, scraped DuckDB v2.0 docs under `ai_docs/`, and self-contained demo prompts under `prompts/duckdb/`.
9. Report installed/already-present components and any configured model that lacks child-visible registration or authentication.
