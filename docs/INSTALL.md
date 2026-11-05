# Install and integrate

Use an unprivileged account. Do not alter managed applications, container capabilities, provider mount configuration, or other users' files.

## Establish a trustworthy measurement

Run `gg-quotaguard diagnose --target /ABSOLUTE/TARGET` from the exact environment that will execute the filter. Its JSON report omits account identifiers and paths. A host SSH diagnosis does not prove a container can access the same commands, mounts, quota, Python interpreter, or files.

Choose quota mode whenever a supported account quota is accessible. Independently inspect your own `findmnt -n -o SOURCE,FSTYPE --target /ABSOLUTE/TARGET` and `quota -w -p -u "$(id -u)"` output. Keep that raw output private. The target filesystem and the configured `quota_device` must agree; bind-mount source suffixes such as `[/account]` are removed for this comparison. Configure the device path as reported before the bracket suffix.

Confirm that the selected quota applies to all relevant downloads and that a stricter group, project, provider, or other limit does not apply. This implementation reads user quotas; it does not discover all additional quota policies. Do not confirm scope if this is uncertain.

Directory mode is an explicit fallback, not an automatic substitute for a failed quota read. Verify the quota in exact bytes with your provider, and include every charged directory, including application files, hidden files, completed and incomplete downloads, and any other billed data. The target must be inside the measured roots, and all roots must belong to the same filesystem. A list containing only the download folder is insufficient when the plan charges the entire account. A successful scan cannot prove there are no charged files outside its view, deleted-but-open files, snapshots, or provider-specific overhead.

All symlinks and special files encountered by a directory scan are rejected. Do not add exclusions merely to make a scan pass. Use a verified quota method or resolve the visibility problem.

## Confirm starting conditions

Pause new admissions and inspect existing download queues before setting `startup_pending_confirmed` to `true`. Existing outstanding downloads that QuotaGuard did not approve can still consume space. A safe startup requires no unaccounted pending allocation, or independently established conservative accounting for it. This version has no torrent-client reconciliation adapter; it cannot establish those conditions itself.

Set `scope_confirmed` to `true` only after verifying the measurement and billing scope. These are operator attestations, not automated discoveries. Unknown configuration keys, missing confirmations, zero reserves, unknown release sizes, or invalid limits reject.

The safety reserve must cover filesystem metadata, logs, quota rounding, measurement races, and plausible unrelated writes. No finite reserve can make arbitrary uncoordinated writers safe. If other software can consume unbounded storage, pause or coordinate it before relying on admission checks.

## Install reviewed files

Copy `gg_quotaguard.py` to an account-owned executable path such as `~/.local/bin/gg-quotaguard`, using the commands in the repository README. Do not pipe downloaded shell scripts into a shell. Keep configuration private with mode `0600`; keep the state directory private with mode `0700`. Use local disk storage with working SQLite locks and durable writes, rather than a network share with uncertain locking semantics.

Initialize once after confirming startup conditions:

```sh
gg-quotaguard init --config /ABSOLUTE/config.json
gg-quotaguard inspect --config /ABSOLUTE/config.json
gg-quotaguard status --config /ABSOLUTE/config.json
```

Use the absolute executable path if `~/.local/bin` is not in your shell's `PATH`. `init` refuses to overwrite existing state. `check` refuses missing or corrupt state; it does not silently create an empty ledger.

## Connect Autobrr

Create an isolated test configuration and state directory first. Use synthetic sizes and do not send real downloads. On the chosen filter, set a minimum size of `1`, choose an external Exec filter, set expected exit status `0`, and choose **On Error: Reject**. Do not choose a continue/ignore-errors behavior.

Use this argument template with verified local paths:

```text
check --config /ABSOLUTE/config.json --size {{ .Size }}
```

Autobrr renders template macros and splits arguments as shell words; it does not execute a shell pipeline. Do not use shell expansions, `&&`, pipes, or `~` in the field. Quoting paths with spaces is required. No special release-size environment variable is assumed; `{{ .Size }}` supplies integer bytes explicitly. This version rejects zero/unknown sizes rather than guessing.

Keep `{{ .Size }}` as the only dynamic argument. Do not interpolate string macros, including torrent names or torrent/indexer identifiers. A quote in rendered input can change the argument vector even though no shell is invoked. Duplicate command options reject, but that does not make arbitrary string interpolation an approved integration.

By default, QuotaGuard generates a fresh random attempt ID internally. Every accepted retry reserves another full size, which conservatively reduces capacity and needs reconciliation. A trusted direct CLI caller can supply `--request-id` with an opaque ID; repeating an already reserved explicit ID rejects. Do not populate that option using Autobrr string macros. No raw request ID appears in tool output, and IDs must not contain credentials or passkeys.

Call `check` through Autobrr's external-filter test facility when available, or an isolated, non-downloading release pipeline for your installed version. Verify an accepted synthetic check, an oversized rejection, a malformed/unknown-size rejection, and a missing-configuration rejection. Test reports must distinguish direct CLI tests from actual execution through Autobrr.

For managed Docker Autobrr, obtain supported access to run the tool and see the complete quota scope inside the container. Installing files over host SSH alone does not solve this. Do not use privileged containers or attempt to bypass Docker socket permissions. A separate user-space Autobrr installation is an alternative only when your provider permits it; it needs separate maintenance and does not inherit provider support or reverse proxy configuration automatically.

## Reconcile reservations

Every successful `check` adds the full release size to the ledger. Even if its storage is already visible in measured usage, the reservation remains until an operator releases it. This intentional double counting prevents timeout-based re-admission while a download is slow, paused, queued, or unavailable.

Find the reservation hash in the accepted JSON result or in `status`. Keep a private mapping from reservation hashes to downloads when needed. Release a reservation only after independently confirming either:

- The download is fully accounted in the storage measurement, and no further unaccounted allocation remains; or
- The action has been permanently cancelled, including queued/retry work, so it cannot allocate later.

Then run:

```sh
gg-quotaguard release --config /ABSOLUTE/config.json --reservation HASH --confirmed-accounted-or-cancelled
```

`release` obtains a fresh measurement, but it cannot verify your torrent-client assertion. An action that fails after approval still leaves a reservation. Crashing after a committed reservation but before approval reaches Autobrr can also leave one; that is a conservative leak. Do not delete ledger files or automatically expire entries to recover capacity.

All protected filters sharing an account pool must use the same state directory and compatible configuration. Different ledgers cannot coordinate. Configuration changes are rejected by the ledger fingerprint; reconcile outstanding work before a deliberate migration. Back up the ledger only while checks are paused and SQLite has no open transaction.

## Roll back

Disable the isolated test filter/instance first. Stop admissions and reconcile pending actions before disabling a live guard; removing it removes storage protection. Preserve configuration and reservation state until no related action can allocate more storage. Remove only the dedicated tool installation and test files you created. Never delete real downloads as part of rollback.
