set dotenv-load := true

# Bare `just` lists every recipe (first recipe = default — keep this one on top).
default:
    @just --list

# fusion-harness — 2-5 configured agents, AND not OR.
WORKHORSE_ARCHITECT := "anthropic/claude-sonnet-5"
WORKHORSE_BUILDER := "openai/gpt-5.6-terra"
SOTA_ARCHITECT := "anthropic/claude-fable-5"
SOTA_BUILDER := "openai/gpt-5.6-sol"

# Cheap legacy two-slot pair. Raw chat is the builder.
fh-workhorse *ARGS:
    pi -e extensions/fusion-harness/fusion-harness.ts \
        --model {{WORKHORSE_BUILDER}} \
        --architect {{WORKHORSE_ARCHITECT}} --builder {{WORKHORSE_BUILDER}} \
        --architect-thinking medium --builder-thinking medium \
        {{ARGS}}

# Frontier legacy two-slot pair.
fh-sota *ARGS:
    pi -e extensions/fusion-harness/fusion-harness.ts \
        --model {{SOTA_BUILDER}} \
        --architect {{SOTA_ARCHITECT}} --builder {{SOTA_BUILDER}} \
        --architect-thinking medium --builder-thinking medium \
        {{ARGS}}

# Explicit 2-5 slot YAML stack. The extension selects configured Main as host.
fh-stack CONFIG *ARGS:
    pi -e extensions/fusion-harness/fusion-harness.ts \
        --fh-config {{CONFIG}} {{ARGS}}

# THE fusion stack: rune=Fable 5 architect · flux=Gemini 3.7 Flash Main · drift=DeepSeek V4 Pro
fusion *ARGS:
    just fh-stack .pi/fusion-harness/model-stack-fusion.yaml {{ARGS}}

# 5-slot fusion stack: fusion trio + fire=Kimi K3 + hawk=DeepSeek V4 Flash (both Fireworks)
fusion5 *ARGS:
    just fh-stack .pi/fusion-harness/model-stack-fusion-5.yaml {{ARGS}}
