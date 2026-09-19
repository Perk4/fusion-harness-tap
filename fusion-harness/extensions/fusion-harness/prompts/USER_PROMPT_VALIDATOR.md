# REQUEST (the builder will be asked to do exactly this — your script defines when it is done)
{{PROMPT}}

Project root: {{CWD}}
Run artifacts dir: {{ARTIFACTS_DIR}} — your gate lives here, and the harness saves every builder report (builder-round-N.md) and gate run (gate-round-N.txt) here as the loop progresses.
NOTE: the build has NOT happened yet. Inspect the current state read-only, then WRITE the gate script for the requested end state to this exact absolute path with your write tool:

    {{GATE_PATH}}

Do NOT paste the script into your reply and do NOT put it in a code fence — the harness runs the file, not your message. Reply with a short confirmation only.
