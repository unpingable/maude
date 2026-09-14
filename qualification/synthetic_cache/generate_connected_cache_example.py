#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Expand one pinned installation and profile into the existing setup config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import generate_connected_cache_setup_config as GENERATOR

SETUP = GENERATOR.SETUP
INSTALL_SCHEMA = "maude.connected-cache-example-install/v1"
PROFILE_SCHEMA = "maude.connected-cache-example-profile/v1"
SOURCE_NAMES = {"nq_cli", "nq_helpers", "nightshift", "ag", "docket", "pulse_integration"}


def read_json(path: Path) -> dict:
    value = json.loads(SETUP.read_regular(path, SETUP.MAX_CONFIG))
    if not isinstance(value, dict):
        raise ValueError("example input must be a JSON object")
    return value


def checked_source(source: Path, install: dict) -> None:
    result = subprocess.run(
        ["/usr/bin/git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
         "-C", str(source), "rev-parse", "HEAD"],
        env={"PATH": "/usr/bin:/bin", "GIT_OPTIONAL_LOCKS": "0"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=True,
    )
    if result.stdout.decode().strip() != install["maude_source_revision"]:
        raise ValueError("Maude checkout differs from the installation manifest")
    for name, relative in (("maude_build_plan_sha256", "qualification/synthetic_cache/build_plan.py"),
                           ("maude_executor_sha256", "qualification/synthetic_cache/local_compose_executor.py")):
        if SETUP.file_digest(source / relative) != install[name]:
            raise ValueError("Maude source file differs from the installation manifest")


def generate(args: argparse.Namespace) -> dict:
    install, profile = read_json(args.install_manifest), read_json(args.profile)
    install_fields = {"schema", "maude_source_revision", "maude_build_plan_sha256",
                      "maude_executor_sha256", "programs", "python_sha256",
                      "pulse_launcher_sealer_sha256", "source_revisions"}
    if set(install) != install_fields or install["schema"] != INSTALL_SCHEMA \
            or set(install["programs"]) != set(SETUP.PROGRAMS) - {"python"} \
            or set(install["source_revisions"]) != SOURCE_NAMES \
            or any(not isinstance(value, str) or len(value) != 40
                   or any(c not in "0123456789abcdef" for c in value)
                   for value in install["source_revisions"].values()):
        raise ValueError("installation manifest fields differ")
    if set(profile) != {"schema", "identities", "nq", "runtime", "governance"} \
            or profile["schema"] != PROFILE_SCHEMA:
        raise ValueError("example profile fields differ")
    if profile["governance"].get("profile_label") != "synthetic-standing-cache-example":
        raise ValueError("profile must retain the explicit synthetic Standing label")
    if not args.root.is_absolute() or args.root.exists():
        raise ValueError("root must be a fresh absolute path")
    if not args.program_dir.is_absolute() or not args.maude_source.is_absolute():
        raise ValueError("program directory and Maude source must be absolute")
    if not args.allow_same_identity_in_debug:
        raise ValueError("this single-account example requires explicit debug same-identity admission")
    checked_source(args.maude_source, install)
    programs = {}
    for name, item in install["programs"].items():
        if not isinstance(item, dict) or set(item) != {"filename", "sha256"} \
                or Path(item["filename"]).name != item["filename"]:
            raise ValueError("installed program coordinate differs")
        path = args.program_dir / item["filename"]
        if SETUP.file_digest(path) != item["sha256"]:
            raise ValueError("installed program bytes differ")
        programs[name] = path
    for path, pin, label in ((args.python, install["python_sha256"], "Python"),
                             (args.pulse_launcher_sealer,
                              install["pulse_launcher_sealer_sha256"], "Pulse sealer")):
        if not path.is_absolute() or path.is_symlink() or SETUP.file_digest(path) != pin:
            raise ValueError(f"{label} coordinate differs")
    if not args.root.parent.is_dir():
        raise ValueError("root parent must already exist")
    for path in {args.root.parent, Path("/data")}:
        if path.exists():
            state = os.statvfs(path)
            if state.f_bavail * state.f_frsize < 60 * 1024**3:
                raise ValueError("preparation would cross the documented 60 GiB host reserve")
    values = {**profile["identities"], **profile["runtime"], **profile["governance"]}
    values.update({"output": args.output, "root": args.root, "maude_source": args.maude_source,
                   "maude_source_revision": install["maude_source_revision"],
                   "pulse_launcher_sealer": args.pulse_launcher_sealer,
                   "python": args.python, "execution_account": args.execution_account,
                   "working_directory": args.root / "nq-work",
                   "allow_same_identity_in_debug": True, **profile["nq"], **programs})
    return GENERATOR.generate(SimpleNamespace(**values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("output", "root", "maude-source", "program-dir", "python",
                   "pulse-launcher-sealer", "install-manifest", "profile"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--execution-account", required=True)
    parser.add_argument("--allow-same-identity-in-debug", action="store_true")
    args = parser.parse_args()
    if not args.output.is_absolute():
        raise ValueError("output must be absolute")
    SETUP.write_new(args.output, SETUP.canonical(generate(args)))


if __name__ == "__main__":
    main()
