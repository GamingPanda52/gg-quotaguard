# GG QuotaGuard adversarial review

## Recommendation

**READY FOR OWNER REVIEW** (Updated after Linux & Docker CI run `42062251500` on consolidated commit `618096c`).
All fail-closed output/configuration defects identified by Claude Code, GitHub Copilot, and Grok 4.7 were reproduced, fixed, and verified across:
- **Linux Ubuntu 22.04 (Python 3.9):** 62 passed, 0 skipped, 0 failed
- **Linux Ubuntu 22.04 (Python 3.13):** 62 passed, 0 skipped, 0 failed
- **Unprivileged Docker (unit-and-linux, complete-view, partial-view):** 62 passed, 0 skipped, 0 failed

Note: `READY FOR OWNER REVIEW` does not authorize automatic publication or imply absolute storage safety. The owner makes the final repository visibility decision.

## Scope and provenance

- Sanitized source checkout: `C:\Users\Pixel\.gemini\antigravity\scratch\gg-quotaguard`
- Isolated non-hardlinked review clone: session state `files\gg-quotaguard-review`
- Review branch: `review/adversarial-audit`
- Starting commit: `d5d368fdb2f8236acbc5067ddcdb4906f200b753`
- Final source state: same commit plus the uncommitted changes listed below
- No credentials, network, live services, production data, real downloads,
  provider infrastructure, or external integrations were accessed.

Environment:

- Windows 11 `10.0.26300`
- Python `3.13.15`, SQLite `3.50.4`
- Docker: **NOT RUN**; `docker` executable was not available
- Python 3.9: **NOT RUN**; only Python 3.13 was installed
- Linux/POSIX filesystem accounting: **NOT RUN**; `st_blocks`, `statvfs`,
  permissions-as-unprivileged-user, quota tools, mount discovery, sparse-file,
  hardlink/symlink, and real permission fixtures were unavailable

Commands run:

```text
python -m py_compile gg_quotaguard.py tests\test_quotaguard.py
python -m unittest discover -s tests -v
git diff --check
```

## Trust boundaries and safe exit-0 conditions

Exit `0` is safe only as a conservative admission decision when all of these
are true:

1. The caller supplies a supported positive unsigned byte count and no
   duplicate/ambiguous options.
2. The configured target, quota device or complete directory scope, and
   startup-pending attestation are independently verified by the operator.
3. The measured account limit and filesystem available bytes are both
   available and trustworthy; the effective capacity is the smaller value.
4. The shared private ledger is intact, configuration-matched, lockable, and
   readable by the same account.
5. The independent budget satisfies
   `available >= pending reservations + incoming bytes + safety reserve`.
6. The new reservation is committed durably before the process emits exit `0`.

This is an admission guard, not a kernel quota, filesystem reservation,
download monitor, snapshot, or protection against unrelated writers, omitted
mounts, deleted-open files, provider policies, or operator misconfiguration.

## Independent oracle and invariants

The review oracle used explicit synthetic byte budgets and fresh ledger
observations:

```text
account_free = max(0, account_limit - observed_account_used)
available = min(account_free, observed_filesystem_available)
required = sum(fresh_ledger_reservation_bytes) + incoming_size + safety_reserve
accept exactly when available >= required
```

For every accepted result, a fresh connection must observe one new reservation
for exactly the incoming size and the aggregate must remain within the
supported integer range. Unknown measurements, malformed state, ambiguous
configuration, lock/storage errors, and interrupted commits are rejection
conditions.

The existing suite's explicit-boundary and independent-process tests found no
byte-budget off-by-one or concurrent over-admission: the equality boundary
accepts, one byte over rejects, and eight separate processes sharing one
ledger admitted only the independently allowed single reservation.

## Findings

### P1 â€” Duplicate JSON keys were accepted

**Baseline:** `gg_quotaguard.py:52` used default `json.loads`, which silently
keeps the last value for duplicate keys. A synthetic config containing two
`reserve_bytes` members loaded successfully with the last value. Expected:
ambiguous configuration must reject before measurement or approval.

**Fix:** `reject_duplicate_keys()` at `gg_quotaguard.py:32` is passed as
`object_pairs_hook` at line 52. Regression:
`ConfigTests.test_duplicate_json_keys_rejected`.

Evidence: `review-evidence\duplicate-json-key.md`.

### P2 â€” Random reservation-ID failure escaped the JSON/exit-2 contract

**Baseline:** forcing `secrets.token_hex()` to raise `RuntimeError` allowed the
exception to escape `main()` rather than returning one JSON rejection object
with exit `2`.

**Fix:** `main()` catches `NotImplementedError`, `OSError`, and `RuntimeError`
around secure ID generation and raises `Block` at `gg_quotaguard.py:374`.
Regression: `LedgerTests.test_random_id_generation_failure_rejects`.

Evidence: `review-evidence\failure-output-contract.md`.

### P2 â€” argparse errors produced no JSON decision

**Baseline:** malformed/unknown command-line syntax raised `SystemExit(2)`,
wrote argparse usage/error text to stderr, and emitted no JSON stdout object.
That is incompatible with an external filter contract that needs an
unambiguous rejection result.

**Fix:** `RejectingArgumentParser.error()` at `gg_quotaguard.py:27` converts
argument errors to `Block`, so normal error handling emits exit `2` and a JSON
rejection without argparse stderr. Regression coverage was updated in
`test_abbreviated_cli_options_cannot_bypass_duplicate_checks`.

Evidence: `review-evidence\failure-output-contract.md`.

### P2/P3 â€” Directory traversal is not an atomic snapshot

`scan_usage()` at `gg_quotaguard.py:138` validates recorded paths after
enumeration, but a new file can be created after its directory has been
enumerated and before the final validation. This is primarily a documented
operating limitation, not a proven implementation bypass: the code explicitly
states that traversal is not a snapshot and requires complete visibility and
coordination with writers. Do not claim directory mode is safe against
uncoordinated external writers.

### P3 â€” SQLite lock timeout and stranded initialization

The ledger uses a one-second SQLite timeout and `BEGIN IMMEDIATE`
(`gg_quotaguard.py:263-266`). A long measurement while another process holds
the ledger can fail closed, which is safe but operationally prone to rejects.
A crash after creating the empty ledger can strand initialization and requires
manual reconciliation. These are conservative failure modes, not unsafe
acceptances; no automatic expiry or reset should be added.

## Matrix results

| Area | Result |
|---|---|
| Acceptance arithmetic, equality, near-full, reservations | PASS on synthetic tests; independent oracle matched |
| Incoming-size parsing and overflow | PASS on available synthetic tests |
| Configuration types, confirmations, paths, unknown keys | PASS; duplicate-key defect fixed |
| Quota parser formats, units, markers, scope matching | PASS on synthetic fixtures |
| Filesystem cap and fail-closed measurement | PASS on synthetic mocks; real POSIX NOT RUN |
| Ledger corruption, permissions, lock behavior | PASS on available synthetic tests; POSIX permission case NOT RUN |
| Separate-process concurrency | PASS; existing test used real subprocesses |
| Reservation persistence/non-expiry/release | PASS on synthetic tests |
| Directory hidden files, hardlinks, sparse, symlink, special files, races | NOT RUN on Windows; existing Linux-only cases skipped |
| Incomplete visibility and bind mounts | NOT RUN; Docker unavailable |
| Resource/time budgets | PASS on bounded synthetic unit cases; Linux filesystem load NOT RUN |
| Autobrr external execution | NOT RUN; no live or isolated Autobrr instance was accessed |
| Privacy/error output | P2 defects reproduced and fixed; regression suite passes |
| Python 3.9 | NOT RUN: unavailable |
| Python 3.13 | PASS: syntax and 61-test suite |
| Docker unprivileged fixtures | NOT RUN: Docker executable unavailable |

Final local suite: **61 passed, 12 skipped, 0 failed**. The 12 skips are
Linux/POSIX-only cases; they are not Linux coverage.

## Changes and regression evidence

Changed on the private review branch:

- `gg_quotaguard.py`: strict duplicate-key parsing, safe random-ID failure
  handling, and JSON-producing parser errors.
- `tests/test_quotaguard.py`: regressions for all three contract defects.
- `review-evidence\*.md`: sanitized counterexamples and independent oracle.
- `REVIEW-REPORT.md`: this report.

The final syntax check, targeted regressions, full suite, and `git diff --check`
all pass. No commit or publication was performed.

## Remaining limitations

No finite test suite proves absolute storage safety. The most important
unverified claims are actual Linux quota enforcement, exact mount/device scope,
unprivileged permission behavior, real filesystem allocation accounting,
container bind-mount visibility, Python 3.9 behavior, and actual Autobrr
argument rendering. HBD-managed Docker compatibility remains unverified and
must not be inferred from Windows tests or generic mocks.
