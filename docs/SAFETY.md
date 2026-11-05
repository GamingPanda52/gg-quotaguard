# Security and operational limits

GG QuotaGuard is an admission check. It does not enforce a kernel quota, reserve physical filesystem blocks, monitor a torrent client's queue, or stop unrelated writers.

## Trust boundaries

The user must verify the quota scope, device, manual limit when applicable, target, complete directory visibility, and initial unaccounted pending allocation. The two configuration confirmations record those attestations. Setting them to `true` without verification does not create evidence.

Quota mode supports the current user's Linux quota-tools `-w -p` output in an exact expected row layout, with 1 KiB block values and numeric grace fields. Unsupported layouts, unavailable commands, nonzero command status, warnings on stderr, zero/unlimited limits, duplicate device rows, and target/device mismatch reject. The smaller nonzero soft or hard block limit is used. A filesystem's available bytes are only a second ceiling; they never replace an account limit. Exhausted filesystem or reported user inode capacity also rejects. This is a byte-admission guard and does not predict how many inodes an incoming torrent will require.

Directory mode is an upper estimate of the visible tree, using `max(allocated_blocks * 512, logical_size)` for each distinct `(device, inode)`. It includes dotfiles and directory blocks, deduplicates hardlinks and overlapping roots, and rejects symlinks, special files, cross-filesystem traversal, missing/inaccessible files, observed mutations, and resource-budget failures. Sparse files can therefore be counted above their current allocation, intentionally reducing approvals.

A traversal is not a filesystem snapshot. It cannot discover all omitted bind mounts, billed files outside the roots, deleted-but-open data, snapshots, storage hidden by a container, quota rules, or arbitrary future writes. Changes after a verified observation can still invalidate an estimate. If complete coverage cannot be established independently, do not enable directory-mode admissions.

## Reservations and concurrency

SQLite `BEGIN IMMEDIATE` serializes QuotaGuard operations using one ledger; successful approval is emitted only after commit. The program uses full synchronous writes. Entries persist across process restarts and do not expire. A missing/corrupt ledger is an error, and initialization does not overwrite an existing file. Configuration changes require deliberate reconciliation instead of silently resetting accounting.

The ledger reserves full logical release sizes. It can conservatively double-count data that is already on disk. It does not automatically reconcile torrent completion, failed actions, pre-existing downloads, duplicate release announcements, or manual downloads. An operator's premature `release` can defeat pending-byte protection. Multiple state directories for the same pool, deletion/restoration of stale state, or unreliable filesystem locking can also defeat it.

Default checks generate a fresh random attempt ID, so accepted retries reserve again rather than reuse an earlier approval. A trusted direct CLI caller may supply an opaque `--request-id`; repeating a reserved explicit ID rejects. This option is not a reason to interpolate raw release data into Autobrr's argument field.

If checks are serialized but unrelated writers are not, those writers can still fill the account or filesystem after an approval. Keep a meaningful reserve and coordinate admissions across all relevant applications. A downloaded torrent's eventual storage can also exceed its reported payload through metadata, allocation slack, unpacking, copies, or later processing. Provision the reserve and surrounding workflow accordingly.

## Privacy and execution

Normal tool output includes measurements, decision reasons, reservation hashes and timestamps, but omits usernames, credentials, private paths and raw request IDs. Reservation IDs are SHA-256 hashes, which are identifiers rather than encryption; do not put secrets in request IDs. Exception diagnostics suppress raw command errors and paths. The configuration and SQLite state are private operational files and must not be committed.

The supported Autobrr argument template includes only static operator-controlled paths and the typed unsigned integer `{{ .Size }}` macro. Autobrr renders macros before splitting shell words; string macros can inject additional arguments through quotes or separators within that splitting grammar even without shell execution. Never put release names, torrent/indexer identifiers, URLs, or other untrusted string macros into the command. Duplicate occurrences of protected command options reject.

The diagnostic command checks only a requested path and the current user's quota. It never enumerates other users' storage. It does not test actual external-filter execution and explicitly reports that unverified state. Host diagnostics do not prove managed-container visibility. Do not share raw provider configuration, command output, API keys, passkeys, or access-bearing URLs with a bug report.

Run only trusted, reviewed code from an account-owned directory. No root permissions, privileged containers, Docker socket access, provider infrastructure modification, or remote-shell installation pipelines are required or justified by this project. An account owner can tamper with their own guard; this is not a security boundary against that account.

## Readiness

Synthetic tests, direct server checks, actual Autobrr external execution, actual torrent-client acceptance, managed-container tests, and long-running production use are distinct levels of evidence. Passing one does not establish the others. Public compatibility statements should identify the exact environment and validated behavior, without disclosing account identifiers.
