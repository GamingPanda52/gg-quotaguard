# Testing and evidence

This file describes how to reproduce validation. It is not a certificate of production readiness. Completed executions and deployment acceptance should be recorded separately with their environment, source version, command, result, and skipped coverage.

## Local suite

From a clean checkout, use Python 3.9 or newer:

```sh
python3 -m py_compile gg_quotaguard.py
python3 -m unittest discover -s tests -v
```

Tests must use temporary directories and synthetic content. The suite should cover strict numeric parsing and configuration, exact quota formats, minimum soft/hard limits, target-device matching, failures without filesystem-only fallback, safety-buffer boundaries, unknown and oversized incoming releases, state initialization/corruption, concurrent reservation accounting, and persistence across process invocations.

Filesystem cases belong on Linux: empty trees, hidden files, hardlinks, overlapping roots, sparse files, symlinks, missing paths, permission failures, cross-device/visibility limits, mutation detection and bounded scans. A root-run permission test can mask real denials; execute permission fixtures as a nonroot user. Windows does not expose the POSIX allocation/accounting needed for supported storage measurement, so skipped Linux cases must be reported explicitly.

## Docker and quota infrastructure

Use the fixtures under `tests/docker/` according to their README. Bind-mount tests must distinguish full scope from incomplete container visibility and must not use privileged containers or the shared host's Docker socket. Docker being unavailable is a missing coverage item, not a passing result.

Quota-parser fixtures validate interpretation, not kernel enforcement. Real quota-controlled tests require a suitable owned test filesystem or an already-provisioned account; they must not reconfigure shared provider quotas. Verify a real finite quota, compare it to an independent private observation, and confirm sufficient-space and oversized-release behavior. Do not fill an actual shared account to create a nearly-full fixture. Use an intentionally small synthetic manual quota or mocked capacity for that boundary.

## Isolated server and Autobrr acceptance

Before deploying, run the suite in a temporary, account-owned staging directory, then install reviewed files under a separate test path. Keep synthetic state separate from any live download guard. Record checks for:

1. Exact quota and target mount access under the actual unprivileged execution account.
2. Acceptance that creates a durable reservation.
3. Oversized, unknown-size, invalid-config and missing-ledger rejection.
4. Duplicate and concurrent checks, with one shared ledger.
5. Reservation persistence and deliberate release after verification.
6. Execution through the installed Autobrr external-filter facility or an isolated pipeline with no real downloads.
7. Service restart, test-instance liveness, and rollback path.

A direct CLI success does not establish an actual Autobrr integration. An external-filter test that invokes `check` can add reservations. Use synthetic requests and remove test reservations only after confirming no action can allocate storage. Installing a user-space instance does not establish compatibility with HBD's managed Docker app or its reverse proxy.

## Completed runs on 2026-11-05

| Environment | Completed validation | Result |
| --- | --- | --- |
| Local Windows, Python 3.13 | Unit suite against synthetic fixtures | 59 tests discovered; 47 executed successfully, 12 Linux-specific cases skipped. |
| Authorized HBD host, nonroot account, Python 3.9.2 | Unit/integration suite against synthetic fixtures | All 59 tests passed; no skips. |
| Authorized HBD host | Read-only account quota and mount probes | Exact finite user quota accessible over SSH; target filesystem independently identified. |
| Isolated native Autobrr 1.90.0 | Actual external-filter execution through `POST /api/filters/external/test` | All nine synthetic cases below produced the expected result. |
| Isolated native Autobrr 1.90.0 | Service restart and reservation reconciliation | 4,500,000,000 synthetic reserved bytes persisted across restart; explicitly reconciled after verifying there were no configured indexers or clients; final pending bytes zero. |
| GitHub Actions, unprivileged Docker | Full Linux suite plus complete/partial bind-mount visibility fixtures | 59 tests and both visibility fixtures passed in run `42058181423`. This is generic container coverage, not managed HBD container acceptance. |
| Local Windows / HBD host | Docker execution availability | No local engine; HBD account has no Docker daemon permission. Docker coverage was run in GitHub Actions instead. |

The tested QuotaGuard source has SHA-256 `83745030fcc696f9c903575c04419266994992e3235a774e617d603dfcfe8e96`. The isolated Autobrr installation uses upstream version 1.90.0. Its downloaded Linux x86-64 archive was checked against the upstream published checksum before installation: SHA-256 `ec6b85ae757e18a443115461eef1291c9e578bfbf9d0468b245efb604a9956a5`.

The separate native test instance runs as a user systemd service, listens only on loopback, and has authentication configured. It has a disabled demonstration filter and no real indexers or download clients. Actual external-filter API tests exercised the installed guard with the following results:

| Synthetic case | Expected and observed script status |
| --- | --- |
| Typed numeric `{{ .Size }}` rendered as 1,500,000,000 bytes | `0`, accepted and durably reserved. |
| Second attempt using the internally generated random ID | `0`, accepted with another independent reservation. |
| Trusted explicit synthetic request ID | `0`, accepted and reserved. |
| Repeated explicit request ID | `2`, rejected. |
| Oversized 4,000,000,000,000-byte request | `1`, rejected. |
| Zero incoming size | `2`, rejected. |
| Nonnumeric `NaN` incoming size | `2`, rejected. |
| Missing configuration | `2`, rejected. |
| Duplicate `--size` options | `2`, rejected. |

The three accepted synthetic checks created no real downloads. Their combined 4,500,000,000-byte ledger obligation survived a service restart. The test operator then confirmed there were no configured indexers, clients or downloading actions and explicitly released those synthetic reservations. This verifies the isolated external-execution and ledger workflow; it is not real torrent-client acceptance.

These results do not establish general HBD managed-container support, long-duration production reliability, or real torrent-client download acceptance. A local/private repository push is not a public release.
