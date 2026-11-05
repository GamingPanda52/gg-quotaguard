# Counterexample: duplicate JSON configuration key

Starting commit: `d5d368fdb2f8236acbc5067ddcdb4906f200b753`

Synthetic configuration text contains the duplicate key:

```json
{"mode":"quota","target":"/tmp/downloads","quota_device":"/dev/test","reserve_bytes":100,"reserve_bytes":1,"scope_confirmed":true,"startup_pending_confirmed":true,"state_dir":"/tmp/state"}
```

Observed on the starting implementation:

- `load_config()` succeeds.
- The resulting `reserve_bytes` is `1` (the last JSON member wins).
- Exit status is not a rejection caused by the malformed duplicate-key input.

Independent expected result:

- Reject the configuration as ambiguous before any storage measurement or approval.
- A duplicate key can conceal the safety reserve selected by an operator or reviewer, so accepting the last occurrence is not fail-closed configuration handling.

Difference: Python's default `json.loads()` silently overwrites earlier members. The parser needs an explicit duplicate-key hook that raises `Block`.
