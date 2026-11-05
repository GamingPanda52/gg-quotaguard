# Troubleshooting

| Symptom | Meaning and next step |
| --- | --- |
| `scope_confirmed` or `startup_pending_confirmed` rejection | Setup verification is incomplete. Follow the installation guide before changing these values. |
| Quota row format unsupported | Your quota-tools output differs from the supported `-w -p` layout. Capture a sanitized example for a report; do not strip unit suffixes or guess columns. |
| No finite user quota / missing quota row | A trustworthy account limit was not found. Do not substitute filesystem free space. |
| Target mount does not match configured device | Verify the actual download target, bind mount, and your account quota scope. Container mount names can differ from host names. |
| Directory scan rejects symlinks or special files | Complete accounting cannot be established by this scan policy. Use verified quota mode or correct the scope; do not add blind exclusions. |
| Missing/inaccessible path or observed tree change | Restore visibility or wait for storage activity to settle. The guard rejects uncertain measurements. |
| Scan exceeded a time/entry budget | The account is too large or too active for the current scan budget. Prefer exact quota reporting; avoid expensive per-release scans on shared disks. |
| Sufficient `df` space but rejection | Account quota, safety reserve, or pending reservations is the limiting factor. This is expected on shared storage. |
| Unknown/zero size | Set the Autobrr minimum size to `1` so it fetches a missing size. Confirm the argument is `{{ .Size }}`, not a formatted size string. |
| Request ID already reserved | A trusted direct CLI caller supplied an explicit ID that is already reserved. Inspect status and reconcile the original action rather than approving the same request again. The supported Autobrr template generates IDs internally. |
| Duplicate command options forbidden | The invocation repeats a protected option. Use the documented template with only the typed size macro; do not interpolate string release data. |
| Configuration changed since initialization | Pause admissions and reconcile all pending work before deliberately migrating configuration/state. Do not delete the ledger to bypass this check. |
| Ledger missing/corrupt or permissions unsafe | Stop admissions. Restore a verified current backup, or reconstruct pending obligations before a deliberate fresh initialization. State must be private and use reliable local locking. |
| Lock/state operation fails during a burst | Another check may hold the ledger longer than its lock wait. Rejection is conservative. Prefer faster measurements and test the pool's burst load. |
| Host command works but Autobrr cannot find it | Managed containers have separate executable paths and mount visibility. Verify from Autobrr's execution environment; do not change provider security controls. |
| Direct check works but downloads still bypass the guard | Verify every relevant filter uses `check`, expected exit `0`, and **On Error: Reject**. Operator commands such as `inspect` are not filter gates. |

For a sanitized report, include `gg-quotaguard --version`, Python version, the diagnostic JSON, the nonzero exit status, and a description of host/container placement. Replace private paths, usernames, devices if needed, release IDs and account-specific details with consistent placeholders. Do not include provider login details, torrent URLs, cookies, passkeys, or complete application configurations.
