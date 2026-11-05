# Research and design evidence

Reviewed on 2026-11-05. These references support the design; they do not establish compatibility with an untested provider deployment. Repository snapshots used for inspection:

- Autobrr: `e2731fc72c0650098199885c8358a58380bcba53`.
- Autobrr community-scripts: `e611c203f0b67056d63aaeac4eaa711ce27fc9e0`.

## Autobrr execution contract

[Official external-filter documentation](https://autobrr.com/filters/external) describes script command, arguments, expected exit status and On Error behavior. External filters execute after built-in filtering. Expected exit `0` plus **On Error: Reject** is the integration used here.

The inspected [`internal/filter/service.go`](https://github.com/autobrr/autobrr/blob/e2731fc72c0650098199885c8358a58380bcba53/internal/filter/service.go) resolves the executable, renders argument macros, applies `shellquote.Split`, and executes `exec.Command(cmd, commandArgs...)`. This is a subprocess argument vector rather than a shell. That code does not add a special release-data environment; ordinary inherited process environment is not used as a release-size API by GG QuotaGuard. Exit statuses from exited scripts are returned for comparison. The inspected implementation does not give this script path a context-driven subprocess deadline, so QuotaGuard bounds its own measurement work and storage command calls.

The inspected [`internal/domain/macros.go`](https://github.com/autobrr/autobrr/blob/e2731fc72c0650098199885c8358a58380bcba53/internal/domain/macros.go) exposes `Size` as a `uint64` populated from the release. QuotaGuard accepts `{{ .Size }}` as unformatted integer bytes. Unsupported, empty and zero sizes reject. The supported template deliberately interpolates no string macros: template rendering happens before shell-word splitting, so quotes in a string value can alter arguments even without a shell. Attempt IDs are generated internally by default; explicit IDs are reserved for trusted direct CLI callers. Duplicate command options reject.

[Official general-filter documentation](https://autobrr.com/filters/general) recommends setting minimum size to `1` when an external check requires a size. A missing announced size otherwise may not trigger an out-of-band size fetch. Installed Autobrr versions and indexer behavior must be validated independently.

## Existing community approaches

The reviewed [community-scripts README](https://github.com/autobrr/community-scripts/blob/e611c203f0b67056d63aaeac4eaa711ce27fc9e0/README.md) asks contributors to add their script in a new `scripts/` directory with a README.

The reviewed [`freespace-hbd`](https://github.com/autobrr/community-scripts/blob/e611c203f0b67056d63aaeac4eaa711ce27fc9e0/scripts/freespace-hbd/freespace.sh) obtains human-formatted quota output and strips unit characters. That is not an exact conversion for values whose displayed units change. QuotaGuard instead requires a known unscaled format, validates every numeric field and matches the target device explicitly.

The reviewed [`freespace-ultra`](https://github.com/autobrr/community-scripts/blob/e611c203f0b67056d63aaeac4eaa711ce27fc9e0/scripts/freespace-ultra/freespace-ultra.sh) uses unscaled quota data, caps against filesystem availability, and handles absent release sizes. QuotaGuard uses the same underlying safety principle independently, while rejecting unknown sizes and keeping a persistent concurrency ledger. No upstream script was copied into the implementation.

The reviewed [`freespace-docker`](https://github.com/autobrr/community-scripts/blob/e611c203f0b67056d63aaeac4eaa711ce27fc9e0/scripts/freespace-docker/freespace.sh) checks a filesystem path. That approach cannot establish an individual account allowance on a quota-controlled shared filesystem. A container can see host-backed capacity without access to the user's effective quota.

## Linux storage semantics

[GNU Coreutils `du` documentation](https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html) distinguishes allocated space from apparent size, describes hardlink deduplication, and documents limitations of usage estimates. QuotaGuard does not blindly run `du`: it walks configured roots, tracks device/inode pairs globally, includes hidden entries, and uses the larger logical/allocated size. It rejects incomplete or unsupported traversal conditions. This is still an estimate of visible data, not proof of the provider's entire chargeable usage.

[`statvfs(3)`](https://man7.org/linux/man-pages/man3/statvfs.3.html) defines `f_bavail` as blocks available to unprivileged users. Multiplying it by the filesystem fragment size gives a filesystem ceiling, not a user quota. QuotaGuard always takes the smaller of account free bytes and that ceiling.

[Linux quota-control documentation](https://man7.org/linux/man-pages/man2/quotactl.2.html) distinguishes user, group and project quotas, with separate XFS operations. GG QuotaGuard deliberately uses the current user's existing quota-tools command and does not attempt to enable, modify or enumerate quota policies. A working user quota is not proof that no stricter group/project or provider limit exists; scope confirmation remains required.

[Mount namespace documentation](https://man7.org/linux/man-pages/man7/mount_namespaces.7.html) explains that processes can see different mount lists and directory hierarchies. A container bind mount may show only a subset of an account's billed data. Directory-mode coverage therefore cannot be inferred from a successful container traversal.

## HostingByDesign evidence and limits

[Official HBD Autobrr documentation](https://docs.hostingby.design/application-hosting/applications/autobrr) describes provider installation and service management. [Official dashboard documentation](https://docs.hostingby.design/application-hosting/getting-started/dashboard) identifies the dashboard as a place to view account quota. Those public pages do not establish every current managed-container mount, installed utility, or external execution capability.

Community screenshots supplied for this project describe difficulties accessing quota tools in a Docker-based application and discuss a user-space binary alternative. Those are useful context, not an API or infrastructure guarantee. Statements in that conversation about future per-user partitions or an updater are not implemented assumptions in this project.

Preliminary inspection on one authorized HBD account found an accessible exact user quota over SSH, while Docker daemon access was unavailable to that account. This establishes only host-side capability on that account. A separate user-space Autobrr test instance was authorized. Actual test results, when recorded, must distinguish host checks, user-space Autobrr execution, managed-container compatibility and torrent-client acceptance. See [TESTING.md](TESTING.md).

## Safest supported route

Use exact user quota in an environment that can query the relevant account filesystem. Use directory mode only when the operator can establish complete billing scope and a trustworthy configured limit. Refuse missing capability rather than substituting host free space. A complete user-space route is technically feasible when those observations are available; executing the tool inside an arbitrary managed Docker installation remains a separately validated integration requirement.
