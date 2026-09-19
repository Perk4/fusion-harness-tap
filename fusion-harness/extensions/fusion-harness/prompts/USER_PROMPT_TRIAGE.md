ESCALATION: the builder has failed your acceptance gate {{FAILURES}} time{{FAILURES_PLURAL}} (cap: {{MAX_ROUNDS}}). Diagnose why it is stuck and produce the triage brief per your output contract.

# ORIGINAL REQUEST (what "done" means)
{{REQUEST}}

# RECENT GATE OUTPUT{{HISTORY_SUFFIX}}
{{GATE_HISTORY}}

# BUILDER'S LATEST REPORT (its claims — verify against the real state before trusting)
{{BUILDER_REPORT}}

# RUN ARTIFACTS (the full, untruncated history — the excerpts above are truncated)
{{ARTIFACTS_DIR}} — gate.py (your gate), gate-baseline.txt, builder-round-N.md (every builder report), gate-round-N.txt (every gate run). Read these files when you need the complete picture.
