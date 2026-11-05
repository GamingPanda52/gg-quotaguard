**Remaining subtle fail-closed bugs (in priority order):**

### 1. `ledger()` context manager – critical SQLite locking / rollback race (fail-open)
**Function:** `ledger()`

```python
db = sqlite3.connect(..., isolation_level=None)
db.execute('BEGIN IMMEDIATE')
...
yield db
db.commit()
```

**Bug:** Using `isolation_level=None` (autocommit mode) + manual `BEGIN IMMEDIATE` means the `except BaseException: db.rollback()` does **nothing** on most exceptions (including `Block`, `OSError`, `sqlite3.Error`). The transaction was already auto-committed on the first write.

This turns many failure paths into partial commits → **fail-open** (reservations can be created without proper validation).

Also: `timeout=1` is too aggressive under load; can cause spurious `sqlite3.OperationalError` that gets turned into generic reject, but combined with the above is messy.

### 2. `scan_usage()` – symlink race / TOCTOU after `lstat()`
**Function:** `scan_usage()`

After `s = path.lstat()`, the code does:
```python
if stat.S_ISLNK(s.st_mode):
    raise Block(...)
```

Then later:
```python
if stat.S_ISDIR(s.st_mode):
    with os.scandir(path) as entries:   # <-- uses path again, not fd
```

Between `lstat()` and `scandir()`, an attacker with write access inside the measured tree can replace a directory with a symlink. This bypasses the symlink check and allows traversal outside the intended scope.

Also: `Path(entry.path)` + `stack.append()` re-introduces potential symlink following if the attacker races hardlinks/symlinks during the second phase.

### 3. `private_directory()` + `ledger()` initialization race (symlink attack)
**Functions:** `private_directory()`, `ledger()`

`mkdir(parents=True, exist_ok=True)` followed by later `resolve(strict=True)` + permission check is **not atomic**. An attacker can create a symlink between the two calls.

The `initialize=True` path using `O_CREAT|O_EXCL` on the DB is good, but the parent directory check is not race-free.

### 4. `check()` – pending reservation double-counting on exception after INSERT
**Function:** `check()`

```python
db.execute('INSERT INTO reservations...')
result.update(decision='accept'...)
# <- exception here (e.g. in final measure(), or OOM, or signal) 
#    → rollback happens, but the outer except Block path already returned accept
```

Because the `measure(c)` in the `release`/`status` paths and some exception paths can still raise after the INSERT, there is a window where the reservation is committed but the caller receives a reject. Next retry with same `--request-id` is then rejected as duplicate, but the reservation is already consumed.

### 5. Minor but real:
- `parse_quota()`: `integer(field.rstrip('*'), 'quota field')` – the `rstrip('*')` + regex allows `123*` but `integer()` accepts it. However, if the `*` is on the grace field (which the regex incorrectly permits), it silently corrupts the value.
- `diagnose()` calls `run(['quota'...)` and `parse_quota()` with the **first** device from `findmnt`, not the verified one from config. Can give misleading output.
- `request_hash()` accepts control characters after the first character (only checks `ord(c) < 32` in a loop, but the condition is wrong — should be `any(ord(c) < 32 or ord(c) > 126 for c in value)` or similar).
- No `PRAGMA journal_mode=WAL` → under high concurrency (many simultaneous checks) you get frequent `database is locked` errors turned into generic reject.

### Recommendations (concise):

- Fix `ledger()`: use `isolation_level='DEFERRED'` (default), keep `BEGIN IMMEDIATE`, and **never** rely on `rollback()` in `except BaseException` for autocommit mode.
- Change `scan_usage()` to use file descriptors (`os.open()` + `os.scandir(fd)`) or `Path` with `follow_symlinks=False` + `os.fstat()` consistently. Reject any symlink at any point.
- Move the final `measure(c)` in `release` **before** the `DELETE`.
- Increase SQLite timeout or implement retry loop on `OperationalError`.
- Add `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`.

The current code is already quite conservative, but the **ledger transaction model** and the **symlink race in scan_usage** are the two remaining issues that can actually cause incorrect approvals (fail-open). All others are mostly robustness/DoS vectors.