# Maude reviewed-local-copy artifacts 0.1.0

This package holds the Maude parts of the Constellation `reviewed-local-copy/v1`
profile. It targets Debian 12 and its `/usr/bin/python3.11`.

    lib/validator.pyz        closed plan validator (AG runs it)
    lib/executor.pyz         closed exclusive-create executor (Docket runs it)
    lib/maude-plan.pyz       importable plan library for plan preparation
    lib/*.manifest.json      archive and per-entry digests
    share/helpers/cache-host-bootstrap.py   host posture helper (construct, acquire, bind, support, cycle)
    share/helpers/prepare_pulse_support.py  fresh Pulse key, support config and sealed resolver launcher
    BUILD-INFO.json  SHA256SUMS  README.md  LICENSE  NOTICE  THIRD_PARTY_NOTICES/

## Programs

- `validator.pyz validate --config <validator-config.json> --binding <binding.json>`
  reads the plan store read-only and recompiles the bound plan.
  - On success it prints `{"result": "passed", ...}` and exits 0.
  - It refuses anything else with exit 2 and a JSON reason on stderr.
- `executor.pyz plan-id|execute|reconcile <executor-config.json>` speaks Docket's
  `gwr.executor-transport.v1` over stdin/stdout. The executor is only the effect
  mechanics and carries no authority of its own. It does nothing unless AG
  issues the work and Docket dispatches it.
  - `execute` creates `result.txt` once in the plan's scratch root, with an
    exclusive create, and keeps a durable attempt record under `state_root`.
  - Replaying an attempt returns its recorded outcome and does not write again.
  - `execute` refuses a second attempt against the same target, an existing
    target, a dispatch that differs from the sealed plan, and a tampered plan.
  - `reconcile` only reads the attempt record. It never copies.
- `maude-plan.pyz` is a library, not a program. Put it first on `sys.path` and
  import `maude.plan.document`, `maude.plan.store`, `maude.plan.reviewed_local_copy`
  (compiler, binding and validator) or `maude.plan.local_compose`. It bundles
  PyYAML. The kit's `prepare_plan.py` runs with it under `python3.11 -I -S`.
  Check `maude.__file__` and `yaml.__file__` start with the archive path.
  Its `__main__` answers only `--version` and `--build-info`.

## Source and identity

- The Maude modules and the helpers are byte-identical to public commit
  `d0f1375245d7fbaa05b0c6da9b8f60c6c5d388f4`. This is the commit that alpha.6
  executed (B004).
- PyYAML's pure Python modules come from `python3-yaml` 6.0.1-2build2.
- Only `__main__.py` and the shebang differ from the B004 validator and executor
  archives:
  - `__main__.py` adds identity dispatch;
  - the shebang is `#!/usr/bin/python3.11 -IS`, which runs isolated and
    without `site`.

Each archive answers these, run directly or as `python3.11 -I <pyz>`:

    lib/validator.pyz --version      # maude-reviewed-local-copy-validator 0.1.0 <40-hex commit>
    lib/validator.pyz --build-info   # JSON: component, version, source_commit, source_tree, packaging_commit, entry digests

The helpers do not answer `--version`. Their identity comes from `BUILD-INFO.json`
and `SHA256SUMS`.

## Install

The only requirement is Debian 12's `/usr/bin/python3.11`. The programs need no
venv, pip or network.

    sha256sum --check SHA256SUMS
    sudo install -d -m 0755 /usr/lib/maude-reviewed-local-copy
    sudo install -m 0755 lib/validator.pyz lib/executor.pyz /usr/lib/maude-reviewed-local-copy/

You can also extract the tarball to a root-owned prefix and use it in place.

The setup driver enrolls two things:

- the post-install sha256 of each `.pyz` (AG `plan_validator` and
  `executor_adapter`);
- the sha256 of `/usr/bin/python3.11`, because the interpreter and its standard
  library are trusted as part of the deployment.

`-IS` means `PYTHONPATH`, user and system site-packages, `.pth` hooks and
`sitecustomize` are never loaded. Every import resolves inside the archive or in
the standard library. Run the helpers as `python3.11 -I -S <helper> ...`. They
use only the standard library.

## Limitations

- **Supervised agent sessions are not supported in this release.** The package
  does not ship Maude's classic RPC client, the TUI or anything from
  agent_governor (`ag_shell_client`), and it does not depend on them. Do not
  install the `classic-rpc` extra for this profile.
- The plan CLI and the TUI are not packaged. Plan authoring is available only
  through `maude-plan.pyz`.
- The executor creates exactly one file, `result.txt`, in a plan-bound scratch
  directory. It has no overwrite mode, no command language and no retry.
- `prepare_pulse_support.py` accepts only the NQ `nq.host` profile semantic IDs
  that Pulse d91b214 enrolls (`sha256:f500ddf6…`, `sha256:fb7bce89…`).
  - NQ 0.2.0 emits a different ID, so the helper refuses its artifacts with
    "Pulse has not enrolled this exact NQ profile identity". Pulse d91b214
    pins the same two IDs.
  - Fixing this is a coordinated change: Pulse and this helper must enroll the
    new ID together.
- `cache-host-bootstrap.py acquire` calls `nq diagnostics execute`, `export`
  and `qualify` as whichever account runs the helper. Under NQ 0.2.0's release
  account model, `execute` must run as `nq` in the documented unit that holds
  the capabilities. A setup driver should call NQ directly in that unit rather
  than wrap this helper.
- Building needs Docker, the pinned Debian 12 builder image and the pinned
  `python3-yaml` package. The build is offline, and two clean builds are
  byte-equal. See `packaging/reviewed-local-copy/build_release.py` in the Maude
  repository.
