No project files changed, exactly as required by validator triage. `bench.py` and freshly generated `RESULTS.md` are correct.

The remaining failures are caused solely by the unpatched harness regex. The human/harness operator must change `/tmp/fusion-harness-K48sbW/gate.py:61`:

```diff
- return re.sub(r"[`*_]", "", s)
+ return re.sub(r"[`*]", "", s)
```

No builder-side workaround can legitimately satisfy the defective matcher.