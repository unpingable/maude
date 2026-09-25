# Maude reviewed-local-copy validator and executor 0.1.0

This package holds the two Maude programs that the Constellation
`reviewed-local-copy/v1` profile runs:

- `validator.pyz`: the closed plan validator. AG calls it as
  `validator.pyz validate --config <validator-config.json> --binding <binding.json>`.
  It reads the plan store read-only, recompiles the bound plan, and prints
  `{"result": "passed", ...}` with exit 0. It refuses anything else with exit 2
  and a JSON reason on stderr.
- `executor.pyz`: the executor, which is only the effect mechanics and carries
  no authority of its own. Docket calls it over its `gwr.executor-transport.v1`
  stdin/stdout transport as
  `executor.pyz plan-id|execute|reconcile <executor-config.json>`.
  `execute` creates `result.txt` in the plan's scratch root once, with an
  exclusive create, and keeps a durable attempt record under `state_root`.
  It refuses these cases:
  - a second attempt against an existing target;
  - a dispatch that differs from the sealed plan;
  - a tampered plan.

  `reconcile` only reads the attempt record. It never copies.

Admission belongs to AG and Docket. The executor does nothing unless AG issues
the work and Docket dispatches it.

## Source and identity

The Maude modules are byte-identical to what alpha.6 executed (B004). They come
from public commit `d0f1375245d7fbaa05b0c6da9b8f60c6c5d388f4`. PyYAML's pure
Python modules come from `python3-yaml` 6.0.1-2build2. Only `__main__.py` and
the shebang differ from the B004 archives:

- `__main__.py` adds identity dispatch;
- the shebang is `#!/usr/bin/python3 -IS`, which runs isolated and without
  `site`.

Each program answers:

    validator.pyz --version      # maude-reviewed-local-copy-validator 0.1.0 <40-hex commit>
    validator.pyz --build-info   # JSON: component, version, source_commit, source_tree, packaging_commit, entry digests

`SHA256SUMS` lists every file in this directory. `*.manifest.json` records the
digest of each archive and of each entry in it.

## Install

The only requirement is Debian 12's `python3` (3.11) or newer, at
`/usr/bin/python3`. Nothing else is installed, and the programs need no network.

    sha256sum --check SHA256SUMS
    sudo install -d -m 0755 /usr/lib/maude-reviewed-local-copy
    sudo install -m 0755 validator.pyz executor.pyz /usr/lib/maude-reviewed-local-copy/

The setup driver enrolls two things:

- the post-install sha256 of each `.pyz` (AG `plan_validator` and
  `executor_adapter`);
- the sha256 of the host interpreter, because the interpreter and its standard
  library are trusted as part of the deployment.

The programs run isolated and without `site` (`-IS`). `PYTHONPATH`, user and
system site-packages, `.pth` hooks and `sitecustomize` are therefore never
loaded, and every import resolves either inside the archive or in the
standard library.

## Limitations

- **Supervised agent sessions are not supported in this release.** The package
  does not ship Maude's classic RPC client, the TUI or anything from
  agent_governor (`ag_shell_client`), and it does not depend on them. Do not
  install the `classic-rpc` extra for this profile.
- Only the reviewed-local-copy/v1 validator and executor are packaged. Plan
  authoring, compilation (`prepare_plan`) and the plan CLI are not. The setup
  driver compiles plans from the pinned source.
- The executor creates exactly one file, `result.txt`, in a plan-bound scratch
  directory. It has no overwrite mode, no command language and no retry.
- Building needs Docker, the pinned Debian 12 builder image and the pinned
  `python3-yaml` package. The build is offline, and two clean builds are
  byte-equal. See `build_release.py` in the Maude repository.
