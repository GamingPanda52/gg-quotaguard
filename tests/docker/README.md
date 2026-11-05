# Unprivileged container fixtures

From the repository root, run each service separately so a failure is visible:

```sh
docker compose -f tests/docker/compose.yaml build
docker compose -f tests/docker/compose.yaml run --rm unit-and-linux
docker compose -f tests/docker/compose.yaml run --rm complete-view
docker compose -f tests/docker/compose.yaml run --rm partial-view
```

The containers run as UID/GID 65534, drop all capabilities, deny new privileges,
have no network, and use a read-only root filesystem. Tests create synthetic
files only under a size-limited `/tmp` mount. Fixtures are read-only bind mounts.
No host Docker socket, device, real download directory, or quota administration
is exposed to a container.

`complete-view` measures both configured billed directories. `partial-view`
mounts only one and verifies that the missing configured directory causes a
failure. This illustrates why a Docker-visible subtree is not proof of complete
account coverage. A program cannot discover a billed directory that an operator
omits from configuration; `scope_confirmed` remains an operator responsibility.

The unit suite mocks quota command output for edge cases. These fixtures do not
create a kernel quota filesystem or prove HBD container compatibility. Real
quota behavior requires an authorized quota-enabled Linux account, and the same
diagnostic must be run in Autobrr's actual execution namespace.
