# Independent acceptance oracle

For each synthetic case, calculate the expected result without using the
implementation's helper functions:

```text
account_free = max(0, account_limit - observed_account_used)
available = min(account_free, observed_filesystem_available)
required = sum(fresh_ledger_reservation_bytes) + incoming_size + safety_reserve
accept exactly when available >= required
```

The durable invariant is stronger than the arithmetic result:

```text
if exit == 0:
    a fresh database connection must observe one new reservation for the
    accepted incoming size, and the total reservation sum must remain within
    the supported integer range.
```

Unknown measurements, malformed state, ambiguous configuration, lock/storage
errors, and interrupted commits are rejection conditions, not zero-capacity
approximations.
