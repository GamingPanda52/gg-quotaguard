# Counterexamples: failure-output contract

Starting commit: `d5d368fdb2f8236acbc5067ddcdb4906f200b753`

## Random reservation ID generation

With `secrets.token_hex` replaced in a synthetic process by a function that
raises `RuntimeError("entropy unavailable")`, invoking:

```text
check --config CONFIG --size 1
```

raises `RuntimeError` out of `main()` instead of returning exit status `2` and
one JSON rejection object. This violates the documented fail-closed CLI
contract and can make an external filter observe no decision.

## Invalid command-line syntax

Invoking:

```text
check --config CONFIG --size 1 --request-id secret --bogus
```

raises `SystemExit(2)`, writes argparse usage/error text to stderr, and emits
no JSON object on stdout. The command contract promises JSON rejection output
for failures; an external filter must not have to infer rejection from a
missing result.
