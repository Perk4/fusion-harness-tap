No project files changed, per validator triage. `bench.py` and `RESULTS.md` already satisfy every substantive requirement.

Required harness-side correction:

```diff
- return re.sub(r"[`*_]", "", s)
+ return re.sub(r"[`*]", "", s)
```

This preserves canonical strategy-name underscores and resolves all four failures: table matching, Speed Winner matching, Memory Winner matching, and measured-time parsing.