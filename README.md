# GG QuotaGuard

Conservative storage checks for [Autobrr](https://autobrr.com/), designed for shared seedboxes where filesystem free space is not the same as an account's remaining quota.

GG QuotaGuard runs without root, uses Python's standard library, rejects unknown storage conditions, and reserves each approved release's bytes in a local SQLite ledger. It does not change provider services, delete downloads, or bypass container restrictions.

**Status: experimental, version 0.1.0.** This is a testable implementation, not a claim of production readiness or general HostingByDesign Docker compatibility. Read the [limits](docs/SAFETY.md) before connecting it to a live filter. Current validation evidence belongs in [TESTING.md](docs/TESTING.md).

## How a check works

1. Obtain a finite account limit and its usage through one of two explicitly configured methods.
2. Cap account free space by the target filesystem's space available to unprivileged users.
3. Subtract every outstanding QuotaGuard reservation, the incoming release size, and the configured safety reserve.
4. Approve only if the result is sufficient and the new reservation has been committed successfully.

`quota` mode reads the current user's exact, unscaled Linux quota-tools report, matches it to a verified target mount device, and uses the smaller nonzero soft/hard limit. `directory` mode uses a manually verified quota and measures the complete configured billing scope. There is deliberately no filesystem-only approval mode.

The ledger serializes concurrent checks. Reservations never expire automatically and do not disappear when a download starts or finishes. Manual reconciliation is required; double-counting an existing download is conservative. [Manage reservations](docs/INSTALL.md#reconcile-reservations).

## Requirements

- Linux with Python 3.9 or newer, including `sqlite3` and POSIX filesystem accounting.
- A private local state directory shared by every QuotaGuard check for the same account storage pool.
- For quota mode: Linux `quota` supporting `-w -p`, and `findmnt` from util-linux.
- For directory mode: complete visibility of the billed scope, a verified byte limit, and a filesystem exposing allocated blocks.
- An Autobrr external Exec filter that can actually execute the tool in the environment that can measure storage. A host script path is not automatically accessible inside a managed container.

There are no pip dependencies. Windows can run portable unit tests, but is not a supported storage-measurement target.

## Install and configure

Review a local copy before installing it. From this repository on your Linux account:

```sh
mkdir -p "$HOME/.local/bin" "$HOME/.config/gg-quotaguard"
install -m 700 gg_quotaguard.py "$HOME/.local/bin/gg-quotaguard"
install -m 600 examples/quota.json "$HOME/.config/gg-quotaguard/config.json"
"$HOME/.local/bin/gg-quotaguard" --version
"$HOME/.local/bin/gg-quotaguard" diagnose --target "$HOME"
```

Edit your local configuration. Example configurations intentionally have their setup confirmations set to `false`, so they reject until you verify the scope and outstanding downloads. Replace placeholder paths with canonical absolute paths. JSON does not expand `~` or `$HOME`. Reserve values are bytes: 50 GB is `50000000000`; 50 GiB is `53687091200`.

Follow the [installation and integration guide](docs/INSTALL.md), then initialize the ledger exactly once:

```sh
"$HOME/.local/bin/gg-quotaguard" init --config "$HOME/.config/gg-quotaguard/config.json"
"$HOME/.local/bin/gg-quotaguard" inspect --config "$HOME/.config/gg-quotaguard/config.json"
```

Do not recreate or delete a ledger while approved downloads might still be outstanding.

## Autobrr external filter

Set the filter's minimum size to `1` as recommended by Autobrr for an external size check. Set **On Error: Reject** and **Expected exit status: 0**. Use an Exec external filter:

```text
Command: /home/YOUR_ACCOUNT/.local/bin/gg-quotaguard
Arguments: check --config /home/YOUR_ACCOUNT/.config/gg-quotaguard/config.json --size {{ .Size }}
```

Use the real paths for your account. The only dynamic argument is Autobrr's unsigned integer size. QuotaGuard generates a random attempt ID internally; every accepted retry reserves another full size conservatively. Do not interpolate string macros, including release names or torrent/indexer identifiers, into this command: rendered quotes can change how Autobrr splits arguments. Do not place download URLs, cookies, or passkeys in arguments.

Only `check` is a filter command. `diagnose`, `inspect`, `status`, and `init` are operator commands; their success does not approve or reserve a download. Test buttons can create real reservations when they call `check`, so use a dedicated test configuration and state directory.

## Commands and exit codes

| Command | Purpose |
| --- | --- |
| `diagnose --target PATH` | Read-only, sanitized capability report; never verifies external execution by itself. |
| `inspect --config FILE` | Measure configured storage without changing the ledger. |
| `init --config FILE` | Validate measurement and create a new private ledger once. |
| `check --config FILE --size BYTES [--request-id ID]` | Measure, decide, and durably reserve an accepted attempt; generates a random ID by default. |
| `status --config FILE` | List reservation hashes, sizes, and creation timestamps. |
| `release --config FILE --reservation HASH --confirmed-accounted-or-cancelled` | Remove one reservation after the operator verifies it is safe. |

Exit `0` from `check` means accepted and reserved; `1` means insufficient space; `2` means unknown/invalid conditions or another failure. All nonzero statuses must reject in Autobrr. Output is one JSON object with byte counts and a reason; private target paths, usernames, raw request IDs and credentials are not included in normal output.

`--request-id` is optional for a trusted direct CLI caller that needs an explicit opaque ID. Repeating an already reserved explicit ID rejects. Do not populate it with interpolated string macros in an Autobrr command. Duplicate command options are rejected.

## Development and contribution

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile gg_quotaguard.py
```

See [testing](docs/TESTING.md), [research and upstream references](docs/RESEARCH.md), [troubleshooting](docs/TROUBLESHOOTING.md), [security and operational limits](docs/SAFETY.md), and [contributing](CONTRIBUTING.md).

Community messages and a possible upstream pull request are prepared as [drafts](docs/COMMUNITY-DRAFTS.md). Publication and upstream acceptance are separate actions. GG QuotaGuard is an independent project and is not endorsed or supported by HostingByDesign or Autobrr.

MIT licensed. Copyright 2026 Giant Gamers contributors.
