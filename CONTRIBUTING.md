# Contributing

GG QuotaGuard is experimental. Contributions should improve conservative accounting, compatibility evidence, and understandable diagnostics without adding provider privileges or weakening rejection of unknown conditions.

Before changing behavior, describe a reproducible case using temporary directories and synthetic files. Add meaningful unit or integration coverage, run `python3 -m unittest discover -s tests -v`, and compile the module with `python3 -m py_compile gg_quotaguard.py`. Preserve Python 3.9 compatibility and standard-library-only runtime dependencies.

Never use real downloads as test fixtures, delete existing account data, query other users' files, or require privileged containers on shared hosting. Test permission failures under a nonroot account. Document skipped tests and infrastructure limitations. A mock quota parser test is not evidence of a working kernel quota or HBD managed container.

Keep raw account configs, credentials, private paths, quota output identifying users, SQLite databases, and operator connection helpers out of commits. Use placeholder configurations with setup confirmations disabled. Share sanitized diagnostic JSON and command exit codes when reporting failures.

Discuss changes to reservation expiry, automatic reconciliation, quota interpretation, or scope confirmation before implementation: these can change admission safety. Timeout-based expiry must not silently free bytes still owed to slow or paused downloads.

For a possible contribution to [autobrr/community-scripts](https://github.com/autobrr/community-scripts), follow that repository's current conventions. Its reviewed README requests a new directory under `scripts/` containing the script and a README with usage instructions. Prepare an appropriately scoped directory and validate the copied script. Do not claim upstream inclusion before a pull request is accepted. See [draft community materials](docs/COMMUNITY-DRAFTS.md).

By contributing, you agree that your contribution may be distributed under this project's MIT license.
