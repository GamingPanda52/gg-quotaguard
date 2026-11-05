# Community drafts

These are preparation materials. They are not posted messages, an upstream pull request, or a claim of upstream acceptance. The project is being tested in a private repository; make the repository public only when the owner chooses to release it. Replace repository and validation placeholders using completed evidence before sending them.

## Discord draft

> I've been building **GG QuotaGuard**, a small open-source storage gate for Autobrr on shared seedboxes. The goal is to help where filesystem free space is misleading or quota tools are unavailable inside a managed app.
>
> It uses exact user quota when accessible, or an explicitly verified manual quota and complete directory scope. Unknown measurements and unknown release sizes reject. It also keeps pending-byte reservations so concurrent approvals cannot all reuse the same observed space. Reservations currently need manual reconciliation.
>
> This is experimental. All 59 synthetic tests passed on a nonroot HBD host under Python 3.9.2; local Windows testing passed 47 portable cases and skipped 12 Linux-specific cases. Nine checks through a separate native Autobrr 1.90.0 test instance produced the expected accept/reject results, and synthetic reservations survived its service restart before deliberate reconciliation. No real downloads were configured. The full suite and complete/partial bind-mount fixtures also passed in unprivileged Docker on GitHub Actions. This does not prove compatibility with HBD's managed Docker app. I still need sanitized reports and supported execution tests from additional HBD users, especially the managed-container setup.
>
> Source and instructions: **[insert verified repository URL]**. Bug reports with the tool version, sanitized diagnostic JSON, host/container placement and exit status would help. Please don't share credentials, passkeys, raw account configs or private paths.

## Possible community-scripts pull request

Suggested title: `feat: add GG QuotaGuard storage gate for shared seedboxes`

Suggested directory: `scripts/gg-quotaguard/`, containing the reviewed script, a self-contained README, MIT license notice and relevant example configuration or links to the source repository. Keep account-specific deployment artifacts out of the contribution.

Draft body:

> Adds an experimental Python-standard-library external filter for shared seedboxes. It matches exact current-user quota reporting to the download target, caps against filesystem availability, and rejects unsupported or unknown measurement conditions. An explicit manual-quota directory mode is available only when the operator has verified complete accounting scope.
>
> Each successful check durably reserves the incoming byte count in one shared SQLite ledger. Concurrent checks are serialized. Reservations do not expire, and manual reconciliation is required after completed/accounted or cancelled actions. This favors conservative rejection over automatic recovery of uncertain pending space.
>
> Integration uses `{{ .Size }}` and expected exit status `0`, with On Error set to Reject. Documentation covers missing sizes, startup obligations, managed-container visibility, and the limits of directory accounting.
>
> Validation: `python3 -m unittest discover -s tests -v` passed all 59 tests as a nonroot user on an HBD host running Python 3.9.2. Local Windows/Python 3.13 passed 47 portable cases and skipped 12 Linux-specific cases. Nine actual external-filter checks through a separate native Autobrr 1.90.0 test instance covered acceptance, random and explicit attempt IDs, duplicate IDs, oversized/zero/malformed sizes, missing configuration, and duplicate options. Synthetic reservations persisted across a service restart and were explicitly reconciled with no real downloading actions configured. See `docs/TESTING.md` for exact evidence and source checksum. Unprivileged Docker fixtures and the Python 3.9/3.13 Linux CI matrix passed. HBD's managed Docker execution environment and real torrent-client download acceptance remain unverified. This does not claim general HBD Docker compatibility or provider endorsement.

Recheck upstream contribution conventions before submitting. The inspected community-scripts README requests a new script directory and basic README; it does not imply automatic acceptance of an entire external project.
