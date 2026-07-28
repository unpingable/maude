#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze and validate real, offline Maude installation media.

The campaign's installed-state specimens must not inherit the developer
checkout, its editable virtual environment, a live sibling checkout, or a
package cache.  This preparation step therefore:

* archives exact Git objects for Maude and ``ag-shell-client``;
* copies an explicitly pinned set of wheel bodies already present in the
  local pip HTTP cache;
* builds the two first-party wheels in a sterile temporary virtual
  environment using only those frozen wheels; and
* writes a hash-locked runtime requirements file and complete provenance.

It performs no network operation.  Validation uses only the frozen packet
bytes and does not revisit either source repository or the host cache.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import shutil
import stat
import subprocess
import tarfile
import tempfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from campaign_common import (
    MANIFEST_PATH,
    PACKET_DIR,
    REPO_ROOT,
    SUT_COMMIT,
    CampaignError,
    file_record,
    inventory_files,
    sha256_bytes,
    sha256_file,
    write_json,
    write_text,
)


SCHEMA = "maude.synthetic-install-media.v1"
AG_COMMIT = "485e55783f9e359965e3b736e1d610c4568d45f1"
DEFAULT_AG_REPO = Path("/home/jbeck/git/agent_gov")
DEFAULT_PIP_CACHE = Path("/home/jbeck/.cache/pip/http-v2")
MEDIA_DIR = PACKET_DIR / "installation-media"
SOURCE_DIR = MEDIA_DIR / "sources"
WHEELHOUSE = MEDIA_DIR / "wheelhouse"
PROVENANCE_PATH = MEDIA_DIR / "provenance.json"
TRANSCRIPT_PATH = MEDIA_DIR / "build-transcript.json"
LOCK_PATH = MEDIA_DIR / "runtime-requirements.txt"
INSTALL_VALIDATION_PATH = MEDIA_DIR / "clean-install-validation.json"


# Exact locally cached wheel bodies selected before campaign execution.  These
# are preparation inputs, never a resolver suggestion.  Each copied wheel is
# subsequently checked from its embedded METADATA, WHEEL, and RECORD.
CACHE_WHEELS: tuple[dict[str, str], ...] = (
    {
        "filename": "annotated_types-0.7.0-py3-none-any.whl",
        "name": "annotated-types",
        "version": "0.7.0",
        "sha256": "1f02e8b43a8fbbc3f3e0d4f0f4bfc8131bcb4eebe8849b8e5c773f3a1c582a53",
    },
    {
        "filename": "hatchling-1.29.0-py3-none-any.whl",
        "name": "hatchling",
        "version": "1.29.0",
        "sha256": "50af9343281f34785fab12da82e445ed987a6efb34fd8c2fc0f6e6630dbcc1b0",
    },
    {
        "filename": "linkify_it_py-2.1.0-py3-none-any.whl",
        "name": "linkify-it-py",
        "version": "2.1.0",
        "sha256": "0d252c1594ecba2ecedc444053db5d3a9b7ec1b0dd929c8f1d74dce89f86c05e",
    },
    {
        "filename": "markdown_it_py-4.2.0-py3-none-any.whl",
        "name": "markdown-it-py",
        "version": "4.2.0",
        "sha256": "9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a",
    },
    {
        "filename": "mdit_py_plugins-0.6.1-py3-none-any.whl",
        "name": "mdit-py-plugins",
        "version": "0.6.1",
        "sha256": "214c82fb2ac524472ab6a5bcab1de80f73b50443e187f401bfd77efbc7c6481d",
    },
    {
        "filename": "mdurl-0.1.2-py3-none-any.whl",
        "name": "mdurl",
        "version": "0.1.2",
        "sha256": "84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8",
    },
    {
        "filename": "packaging-26.2-py3-none-any.whl",
        "name": "packaging",
        "version": "26.2",
        "sha256": "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
    },
    {
        "filename": "pathspec-1.0.4-py3-none-any.whl",
        "name": "pathspec",
        "version": "1.0.4",
        "sha256": "fb6ae2fd4e7c921a165808a552060e722767cfa526f99ca5156ed2ce45a5c723",
    },
    {
        "filename": "platformdirs-4.10.0-py3-none-any.whl",
        "name": "platformdirs",
        "version": "4.10.0",
        "sha256": "fb516cdb12eb0d857d0cd85a7c57cea4d060bee4578d6cf5a14dfdf8cbf8784a",
    },
    {
        "filename": "pluggy-1.6.0-py3-none-any.whl",
        "name": "pluggy",
        "version": "1.6.0",
        "sha256": "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
    },
    {
        "filename": "pydantic-2.13.4-py3-none-any.whl",
        "name": "pydantic",
        "version": "2.13.4",
        "sha256": "45a282cde31d808236fd7ea9d919b128653c8b38b393d1c4ab335c62924d9aba",
    },
    {
        "filename": (
            "pydantic_core-2.46.4-cp312-cp312-"
            "manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        ),
        "name": "pydantic-core",
        "version": "2.46.4",
        "sha256": "926c9541b14b12b1681dca8a0b75feb510b06c6341b70a8e500c2fdcff837cce",
    },
    {
        "filename": "pygments-2.20.0-py3-none-any.whl",
        "name": "Pygments",
        "version": "2.20.0",
        "sha256": "81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176",
    },
    {
        "filename": (
            "pyyaml-6.0.3-cp312-cp312-"
            "manylinux_2_17_x86_64.manylinux2014_x86_64."
            "manylinux_2_28_x86_64.whl"
        ),
        "name": "PyYAML",
        "version": "6.0.3",
        "sha256": "ba1cc08a7ccde2d2ec775841541641e4548226580ab850948cbfda66a1befcdc",
    },
    {
        "filename": "rich-15.0.0-py3-none-any.whl",
        "name": "rich",
        "version": "15.0.0",
        "sha256": "33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb",
    },
    {
        "filename": "textual-8.2.8-py3-none-any.whl",
        "name": "textual",
        "version": "8.2.8",
        "sha256": "267375fd402dc8d981457212efa71f0e3365fd17bba144ba9bb3ed7563cb374a",
    },
    {
        "filename": "trove_classifiers-2026.4.28.13-py3-none-any.whl",
        "name": "trove-classifiers",
        "version": "2026.4.28.13",
        "sha256": "8f4b1eb4e16296b57d612965444f87a83861cc989a0451ac97fe4265ddef03b8",
    },
    {
        "filename": "typing_inspection-0.4.2-py3-none-any.whl",
        "name": "typing-inspection",
        "version": "0.4.2",
        "sha256": "4ed1cacbdc298c220f1bd249ed5287caa16f34d44ef4e9c3d0cbad5b521545e7",
    },
    {
        "filename": "typing_extensions-4.16.0-py3-none-any.whl",
        "name": "typing-extensions",
        "version": "4.16.0",
        "sha256": "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    },
    {
        "filename": "uc_micro_py-2.0.0-py3-none-any.whl",
        "name": "uc-micro-py",
        "version": "2.0.0",
        "sha256": "3603a3859af53e5a39bc7677713c78ea6589ff188d70f4fee165db88e22b242c",
    },
)

RUNTIME_PACKAGES = (
    "maude",
    "ag-shell-client",
    "textual",
    "pydantic",
    "PyYAML",
    "markdown-it-py",
    "mdit-py-plugins",
    "platformdirs",
    "Pygments",
    "rich",
    "linkify-it-py",
    "uc-micro-py",
    "mdurl",
    "typing-extensions",
    "typing-inspection",
    "annotated-types",
    "pydantic-core",
)


def _norm_name(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def _command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    result = {
        "argv": argv,
        "cwd": str(cwd) if cwd else None,
        "environment": {
            key: env[key]
            for key in ("PATH", "HOME", "SOURCE_DATE_EPOCH")
            if env is not None and key in env
        },
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", errors="replace"),
        "stderr": completed.stderr.decode("utf-8", errors="replace"),
    }
    if completed.returncode != 0:
        raise CampaignError(
            f"installation-media command failed: {argv!r}\n{result['stderr']}"
        )
    return result


def _wheel_metadata(path: Path) -> dict[str, Any]:
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise CampaignError(f"{path.name}: duplicate ZIP member path")
            for info in archive.infolist():
                member = Path(info.filename)
                unix_mode = info.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or "\\" in info.filename
                    or (
                        file_type
                        and not stat.S_ISREG(unix_mode)
                        and not stat.S_ISDIR(unix_mode)
                    )
                ):
                    raise CampaignError(
                        f"{path.name}: unsafe ZIP member {info.filename!r}"
                    )
            regular_names = [
                name
                for name in names
                if not name.endswith("/") and not archive.getinfo(name).is_dir()
            ]
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            wheel_names = [
                name for name in names if name.endswith(".dist-info/WHEEL")
            ]
            record_names = [
                name for name in names if name.endswith(".dist-info/RECORD")
            ]
            if not (
                len(metadata_names) == len(wheel_names) == len(record_names) == 1
            ):
                raise CampaignError(
                    f"{path.name}: wheel metadata file cardinality is invalid"
                )
            metadata = BytesParser().parsebytes(
                archive.read(metadata_names[0])
            )
            wheel = BytesParser().parsebytes(archive.read(wheel_names[0]))
            record_rows = list(
                csv.reader(
                    archive.read(record_names[0])
                    .decode("utf-8")
                    .splitlines()
                )
            )
            if any(len(row) != 3 for row in record_rows):
                raise CampaignError(f"{path.name}: malformed RECORD row")
            record_paths = [row[0] for row in record_rows]
            if len(record_paths) != len(set(record_paths)):
                raise CampaignError(f"{path.name}: duplicate RECORD path")
            if any(
                Path(name).is_absolute()
                or ".." in Path(name).parts
                or "\\" in name
                for name in record_paths
            ):
                raise CampaignError(f"{path.name}: unsafe RECORD path")
            indexed = {row[0]: row for row in record_rows if len(row) == 3}
            if set(indexed) != set(regular_names):
                raise CampaignError(
                    f"{path.name}: RECORD path set differs from archive members"
                )
            for name in regular_names:
                digest_field = indexed[name][1]
                size_field = indexed[name][2]
                if not digest_field and name == record_names[0]:
                    continue
                if not digest_field.startswith("sha256=") or not size_field:
                    raise CampaignError(
                        f"{path.name}: unhashed RECORD entry: {name}"
                    )
                data = archive.read(name)
                encoded = base64.urlsafe_b64encode(
                    hashlib.sha256(data).digest()
                ).rstrip(b"=").decode("ascii")
                if digest_field != f"sha256={encoded}":
                    raise CampaignError(
                        f"{path.name}: RECORD digest mismatch: {name}"
                    )
                if int(size_field) != len(data):
                    raise CampaignError(
                        f"{path.name}: RECORD size mismatch: {name}"
                    )
            result = {
                "name": metadata.get("Name"),
                "version": metadata.get("Version"),
                "requires_dist": metadata.get_all("Requires-Dist") or [],
                "tags": wheel.get_all("Tag") or [],
                "root_is_purelib": wheel.get("Root-Is-Purelib"),
                "record_entries": len(record_rows),
            }
            stem = path.name.removesuffix(".whl")
            parts = stem.rsplit("-", 4)
            if len(parts) != 5:
                raise CampaignError(
                    f"{path.name}: unsupported or malformed wheel filename"
                )
            filename_name, filename_version, python_tags, abi_tags, platform_tags = (
                parts
            )
            if (
                _norm_name(filename_name) != _norm_name(str(result["name"]))
                or filename_version != result["version"]
            ):
                raise CampaignError(
                    f"{path.name}: filename and embedded distribution differ"
                )
            advertised_tags = {
                f"{python_tag}-{abi_tag}-{platform_tag}"
                for python_tag in python_tags.split(".")
                for abi_tag in abi_tags.split(".")
                for platform_tag in platform_tags.split(".")
            }
            embedded_tags = set(result["tags"])
            if not advertised_tags or not advertised_tags.issubset(embedded_tags):
                raise CampaignError(
                    f"{path.name}: filename tags are not embedded WHEEL tags"
                )
            result["filename_tags"] = sorted(advertised_tags)
            return result
    except BadZipFile as exc:
        raise CampaignError(f"invalid wheel ZIP: {path}") from exc


def _archive_commit(path: Path) -> str:
    command = _command(
        ["git", "get-tar-commit-id"],
        input_bytes=path.read_bytes(),
    )
    return command["stdout"].strip()


def _source_epoch(repo: Path, commit: str) -> str:
    return _command(
        ["git", "show", "-s", "--format=%ct", commit], cwd=repo
    )["stdout"].strip()


def _copy_cache_wheels(cache_root: Path) -> list[dict[str, Any]]:
    expected_hashes = {item["sha256"] for item in CACHE_WHEELS}
    matches: dict[str, list[Path]] = {
        digest: [] for digest in expected_hashes
    }
    for path in cache_root.rglob("*.body"):
        if not path.is_file():
            continue
        digest = sha256_file(path)
        if digest in matches:
            matches[digest].append(path)
    records: list[dict[str, Any]] = []
    for declared in CACHE_WHEELS:
        candidates = matches[declared["sha256"]]
        if len(candidates) != 1:
            raise CampaignError(
                "expected exactly one cached body for "
                f"{declared['sha256']}; found {len(candidates)}"
            )
        source = candidates[0]
        target = WHEELHOUSE / declared["filename"]
        shutil.copyfile(source, target)
        target.chmod(0o644)
        actual = _wheel_metadata(target)
        if (
            _norm_name(str(actual["name"])) != _norm_name(declared["name"])
            or actual["version"] != declared["version"]
            or sha256_file(target) != declared["sha256"]
        ):
            raise CampaignError(
                f"cached wheel identity mismatch: {declared['filename']}"
            )
        sidecar = source.with_suffix("")
        records.append(
            {
                **file_record(target),
                "distribution": actual,
                "origin": "pre-existing local pip HTTP cache body",
                "cache_key": source.stem,
                "cache_body_sha256": declared["sha256"],
                "cache_metadata_sha256": (
                    sha256_file(sidecar) if sidecar.is_file() else None
                ),
                "network_used_during_packet_copy": False,
            }
        )
    return records


def _create_sources(
    maude_repo: Path, agent_governor_repo: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transcript: list[dict[str, Any]] = []
    maude_archive = SOURCE_DIR / "maude-2.4.0.tar"
    ag_archive = SOURCE_DIR / "ag-shell-client-0.1.0.tar"
    transcript.append(
        _command(
            [
                "git",
                "archive",
                "--format=tar",
                "--prefix=maude-2.4.0/",
                f"--output={maude_archive}",
                SUT_COMMIT,
                "LICENSE",
                "README.md",
                "pyproject.toml",
                "src/maude",
            ],
            cwd=maude_repo,
        )
    )
    transcript.append(
        _command(
            [
                "git",
                "archive",
                "--format=tar",
                "--prefix=agent-governor-485e557/",
                f"--output={ag_archive}",
                AG_COMMIT,
                "libs/ag_shell_client",
            ],
            cwd=agent_governor_repo,
        )
    )
    sources = []
    for path, commit, purpose, operator_visible in (
        (
            maude_archive,
            SUT_COMMIT,
            (
                "filtered installable Maude archive from the exact baseline "
                "Git commit and first-party wheel input"
            ),
            True,
        ),
        (
            ag_archive,
            AG_COMMIT,
            "exact ag-shell-client first-party wheel input",
            False,
        ),
    ):
        observed_commit = _archive_commit(path)
        if observed_commit != commit:
            raise CampaignError(
                f"{path.name}: archive commit {observed_commit!r} != {commit!r}"
            )
        with tarfile.open(path, "r") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if any(
                member.name.startswith("/")
                or ".." in Path(member.name).parts
                or ".git" in Path(member.name).parts
                or member.issym()
                or member.islnk()
                or member.isdev()
                or not (member.isfile() or member.isdir())
                for member in members
            ) or len(names) != len(set(names)):
                raise CampaignError(f"{path.name}: unsafe source archive member")
            if operator_visible and any(
                "tests" in Path(member.name).parts
                or "architecture" in member.name.lower()
                for member in members
            ):
                raise CampaignError(
                    f"{path.name}: operator source archive includes withheld material"
                )
        sources.append(
            {
                **file_record(path),
                "git_commit": commit,
                "git_get_tar_commit_id": observed_commit,
                "purpose": purpose,
                "operator_visible": operator_visible,
            }
        )
    return sources, transcript


def _extract_source(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r") as handle:
        members = handle.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise CampaignError(f"{archive.name}: duplicate extraction member")
        destination_resolved = destination.resolve()
        for member in members:
            member_path = Path(member.name)
            target = (destination / member_path).resolve()
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or member.issym()
                or member.islnk()
                or member.isdev()
                or not (member.isfile() or member.isdir())
                or (
                    target != destination_resolved
                    and destination_resolved not in target.parents
                )
            ):
                raise CampaignError(
                    f"{archive.name}: unsafe extraction member {member.name!r}"
                )
        roots = {Path(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1:
            raise CampaignError(f"{archive.name}: expected one archive root")
        handle.extractall(destination, members=members, filter="data")
    return destination / next(iter(roots))


def _build_first_party_wheels(
    maude_repo: Path,
    agent_governor_repo: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transcript: list[dict[str, Any]] = []
    rebuild_hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="maude-install-media-build-") as raw:
        temporary = Path(raw)
        home = temporary / "home"
        home.mkdir()
        builder = temporary / "builder"
        transcript.append(
            _command(["/usr/bin/python3", "-m", "venv", str(builder)])
        )
        python = builder / "bin" / "python"
        env = {
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": f"{builder / 'bin'}:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": _source_epoch(maude_repo, SUT_COMMIT),
        }
        build_requirements = [
            "hatchling==1.29.0",
            "packaging==26.2",
            "pathspec==1.0.4",
            "pluggy==1.6.0",
            "trove-classifiers==2026.4.28.13",
        ]
        transcript.append(
            _command(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links",
                    str(WHEELHOUSE),
                    *build_requirements,
                ],
                env=env,
            )
        )
        source_root = temporary / "source"
        source_root.mkdir()
        maude_source = _extract_source(
            SOURCE_DIR / "maude-2.4.0.tar", source_root
        )
        ag_source_root = _extract_source(
            SOURCE_DIR / "ag-shell-client-0.1.0.tar", source_root
        )
        ag_source = ag_source_root / "libs" / "ag_shell_client"
        rebuild_dir = temporary / "rebuild"
        rebuild_dir.mkdir()
        for source, commit, expected in (
            (ag_source, AG_COMMIT, "ag_shell_client-0.1.0-py3-none-any.whl"),
            (maude_source, SUT_COMMIT, "maude-2.4.0-py3-none-any.whl"),
        ):
            env["SOURCE_DATE_EPOCH"] = _source_epoch(
                agent_governor_repo if commit == AG_COMMIT else maude_repo,
                commit,
            )
            transcript.append(
                _command(
                    [
                        str(python),
                        "-m",
                        "pip",
                        "wheel",
                        "--no-deps",
                        "--no-index",
                        "--no-build-isolation",
                        "--wheel-dir",
                        str(WHEELHOUSE),
                        str(source),
                    ],
                    env=env,
                )
            )
            if not (WHEELHOUSE / expected).is_file():
                raise CampaignError(f"first-party wheel was not produced: {expected}")
            transcript.append(
                _command(
                    [
                        str(python),
                        "-m",
                        "pip",
                        "wheel",
                        "--no-deps",
                        "--no-index",
                        "--no-build-isolation",
                        "--wheel-dir",
                        str(rebuild_dir),
                        str(source),
                    ],
                    env=env,
                )
            )
            rebuilt = rebuild_dir / expected
            if not rebuilt.is_file():
                raise CampaignError(
                    f"first-party reproducibility rebuild absent: {expected}"
                )
            original_hash = sha256_file(WHEELHOUSE / expected)
            rebuild_hash = sha256_file(rebuilt)
            if original_hash != rebuild_hash:
                raise CampaignError(
                    f"first-party wheel is not byte-reproducible: {expected}"
                )
            rebuild_hashes[expected] = rebuild_hash
        transcript.append(
            _command(
                [str(python), "-m", "pip", "freeze", "--all"], env=env
            )
        )

    records = []
    for filename, name, version, commit in (
        (
            "ag_shell_client-0.1.0-py3-none-any.whl",
            "ag-shell-client",
            "0.1.0",
            AG_COMMIT,
        ),
        ("maude-2.4.0-py3-none-any.whl", "maude", "2.4.0", SUT_COMMIT),
    ):
        path = WHEELHOUSE / filename
        metadata = _wheel_metadata(path)
        if (
            _norm_name(str(metadata["name"])) != _norm_name(name)
            or metadata["version"] != version
        ):
            raise CampaignError(f"built wheel identity mismatch: {filename}")
        records.append(
            {
                **file_record(path),
                "distribution": metadata,
                "origin": "sterile offline build from exact frozen Git archive",
                "source_commit": commit,
                "pip_no_index": True,
                "intentional_network_operations": 0,
                "os_network_namespace_enforced": False,
                "editable": False,
                "double_build_byte_reproducible": True,
                "rebuild_sha256": rebuild_hashes[filename],
            }
        )
    return records, transcript


def _lock_text(wheels: list[dict[str, Any]]) -> str:
    by_name: dict[str, dict[str, Any]] = {}
    for record in wheels:
        name = _norm_name(str(record["distribution"]["name"]))
        if name in by_name:
            raise CampaignError(f"duplicate normalized wheel distribution: {name}")
        by_name[name] = record
    lines = [
        "# Frozen runtime closure for clean-room Maude 2.4.0 installation.",
        "# Generated from packet wheel bytes; use with pip --require-hashes.",
    ]
    for name in RUNTIME_PACKAGES:
        record = by_name.get(_norm_name(name))
        if record is None:
            raise CampaignError(f"runtime wheel closure is missing {name}")
        distribution = record["distribution"]
        lines.append(
            f"{distribution['name']}=={distribution['version']} "
            f"--hash=sha256:{record['sha256']}"
        )
    return "\n".join(lines) + "\n"


def _write_lock(wheels: list[dict[str, Any]]) -> None:
    write_text(LOCK_PATH, _lock_text(wheels))


def _verify_clean_install(
    wheels: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Prove the frozen closure creates one ordinary, non-editable install."""

    commands: list[dict[str, Any]] = []
    expected = {
        _norm_name(str(record["distribution"]["name"])): str(
            record["distribution"]["version"]
        )
        for record in wheels
        if _norm_name(str(record["distribution"]["name"]))
        in {_norm_name(name) for name in RUNTIME_PACKAGES}
    }
    if set(expected) != {_norm_name(name) for name in RUNTIME_PACKAGES}:
        raise CampaignError("runtime validation closure differs from lock")

    with tempfile.TemporaryDirectory(prefix="maude-install-media-verify-") as raw:
        temporary = Path(raw)
        home = temporary / "home"
        home.mkdir()
        environment = temporary / "venv"
        commands.append(
            _command(["/usr/bin/python3", "-m", "venv", str(environment)])
        )
        python = environment / "bin" / "python"
        env = {
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": f"{environment / 'bin'}:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        pip_config = _command(
            [str(python), "-m", "pip", "config", "debug"], env=env
        )
        commands.append(pip_config)
        if "exists: True" in pip_config["stdout"]:
            raise CampaignError(
                "sterile verifier inherited a pip configuration file"
            )
        pip_install = _command(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--no-index",
                "--find-links",
                str(WHEELHOUSE),
                "--require-hashes",
                "--requirement",
                str(LOCK_PATH),
            ],
            env=env,
        )
        commands.append(pip_install)
        pip_check = _command(
            [str(python), "-m", "pip", "check"], env=env
        )
        commands.append(pip_check)
        pip_freeze = _command(
            [str(python), "-m", "pip", "freeze", "--all"], env=env
        )
        commands.append(pip_freeze)
        pip_inspect = _command(
            [str(python), "-m", "pip", "inspect", "--local"], env=env
        )
        commands.append(pip_inspect)
        probe_source = """\
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import pathlib
import platform
import site
import sys
import sysconfig
from pip._vendor.packaging.tags import sys_tags

import ag_shell_client
import maude.app
import maude.plan.envelope
import pydantic_core
import textual
import yaml

prefix = pathlib.Path(sys.prefix).resolve()
site_packages = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()
spec = importlib.util.find_spec("maude")
module = pathlib.Path(spec.origin).resolve() if spec and spec.origin else None
distribution = metadata.distribution("maude")
entry_points = [
    {"name": item.name, "group": item.group, "value": item.value}
    for item in distribution.entry_points
]
script = (prefix / "bin" / "maude").resolve()
packages = {
    dist.metadata["Name"]: dist.version
    for dist in metadata.distributions()
    if dist.metadata.get("Name")
}
direct_urls = sorted(str(path.relative_to(prefix)) for path in prefix.rglob("direct_url.json"))
egg_links = sorted(str(path.relative_to(prefix)) for path in prefix.rglob("*.egg-link"))
pth = []
host_path_hits = []
installer_records = {}
needles = (
    b"/home/jbeck",
    b"agent_gov_ui",
    b"/agent_gov/",
    b"site-packages/maude.egg-link",
)
for path in sorted(prefix.rglob("*")):
    if not path.is_file():
        continue
    if path.suffix == ".pth":
        data = path.read_bytes()
        pth.append({
            "path": str(path.relative_to(prefix)),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    elif ".dist-info" in path.parts or path.name == "RECORD":
        data = path.read_bytes()
    else:
        continue
    for needle in needles:
        if needle in data:
            host_path_hits.append({
                "path": str(path.relative_to(prefix)),
                "needle": needle.decode("ascii"),
            })
for dist in metadata.distributions():
    name = dist.metadata.get("Name")
    if not name:
        continue
    installers = [
        item for item in (dist.files or [])
        if pathlib.Path(str(item)).name == "INSTALLER"
    ]
    installer_records[name] = (
        dist.locate_file(installers[0]).read_text(encoding="utf-8").strip()
        if len(installers) == 1
        else None
    )
python_executable = pathlib.Path(sys.executable).resolve()
script_bytes = script.read_bytes() if script.is_file() else b""
script_first_line = (
    script_bytes.splitlines()[0].decode("utf-8", errors="replace")
    if script_bytes
    else None
)
result = {
    "prefix": str(prefix),
    "site_packages": str(site_packages),
    "maude_version": distribution.version,
    "maude_module": str(module) if module else None,
    "maude_module_inside_prefix": bool(module and prefix in module.parents),
    "entry_points": entry_points,
    "console_script": str(script),
    "console_script_exists": script.is_file(),
    "console_script_executable": os.access(script, os.X_OK),
    "console_script_inside_prefix": prefix in script.parents,
    "console_script_sha256": hashlib.sha256(script_bytes).hexdigest() if script_bytes else None,
    "console_script_first_line": script_first_line,
    "python_executable": str(python_executable),
    "python_executable_sha256": hashlib.sha256(python_executable.read_bytes()).hexdigest(),
    "python_version": sys.version,
    "python_cache_tag": sys.implementation.cache_tag,
    "sysconfig_platform": sysconfig.get_platform(),
    "libc": platform.libc_ver(),
    "compatible_tags": [str(tag) for _, tag in zip(range(40), sys_tags())],
    "packages": packages,
    "direct_url_files": direct_urls,
    "egg_link_files": egg_links,
    "pth_files": pth,
    "installer_records": installer_records,
    "host_or_sibling_path_hits": host_path_hits,
    "sys_path": sys.path,
    "user_site": site.getusersitepackages(),
    "user_site_enabled": site.ENABLE_USER_SITE,
    "imported_modules": [
        "maude.app",
        "maude.plan.envelope",
        "ag_shell_client",
        "pydantic_core",
        "yaml",
        "textual",
    ],
}
print(json.dumps(result, sort_keys=True))
"""
        probe = _command([str(python), "-c", probe_source], env=env)
        commands.append(probe)
        maude_help = _command(
            [str(environment / "bin" / "maude"), "--help"], env=env
        )
        commands.append(maude_help)
        try:
            observed = json.loads(probe["stdout"])
        except json.JSONDecodeError as exc:
            raise CampaignError(
                "clean installation probe did not return JSON"
            ) from exc
        installed = {
            _norm_name(name): version
            for name, version in observed.get("packages", {}).items()
        }
        failures: list[str] = []
        unexpected = set(installed) - set(expected) - {"pip"}
        if unexpected:
            failures.append(
                f"unexpected installed distributions: {sorted(unexpected)!r}"
            )
        for name, version in expected.items():
            if installed.get(name) != version:
                failures.append(
                    f"{name}: installed {installed.get(name)!r}, expected {version!r}"
                )
        expected_entry = {
            "name": "maude",
            "group": "console_scripts",
            "value": "maude.app:main",
        }
        if observed.get("maude_version") != "2.4.0":
            failures.append("importlib metadata does not report Maude 2.4.0")
        if not observed.get("maude_module_inside_prefix"):
            failures.append("Maude module does not resolve inside verifier venv")
        if expected_entry not in observed.get("entry_points", []):
            failures.append("Maude console entry point metadata is absent or wrong")
        if (
            not observed.get("console_script_exists")
            or not observed.get("console_script_executable")
            or not observed.get("console_script_inside_prefix")
        ):
            failures.append("Maude console script is absent, non-executable, or external")
        if observed.get("console_script_first_line") != f"#!{python}":
            failures.append("Maude console-script shebang does not name verifier Python")
        if observed.get("direct_url_files"):
            failures.append("direct_url.json exposes an editable/path install")
        if observed.get("egg_link_files"):
            failures.append("egg-link exposes an editable/path install")
        if observed.get("pth_files"):
            failures.append("unexpected .pth file in installed runtime")
        if observed.get("host_or_sibling_path_hits"):
            failures.append("installed metadata contains a host or sibling path")
        installers = {
            _norm_name(name): value
            for name, value in observed.get("installer_records", {}).items()
        }
        wrong_installers = {
            name: installers.get(name)
            for name in expected
            if installers.get(name) != "pip"
        }
        if wrong_installers:
            failures.append(
                f"runtime distributions lack pip INSTALLER evidence: {wrong_installers!r}"
            )
        if any(
            marker in entry
            for entry in observed.get("sys_path", [])
            for marker in ("/home/jbeck", "agent_gov_ui", "/agent_gov/")
        ):
            failures.append("Python sys.path contains a host source/sibling path")
        if "Maude - Governor TUI" not in maude_help["stdout"]:
            failures.append("installed Maude --help did not expose its public parser")
        if failures:
            raise CampaignError(
                "clean installation validation failed:\n" + "\n".join(failures)
            )
        result = {
            "schema": "maude.synthetic-install-media.clean-install-validation.v1",
            "result": "passed",
            "authority_effect": "none",
            "runtime_requirements_sha256": sha256_file(LOCK_PATH),
            "wheelhouse": [
                {
                    "path": Path(record["path"]).name,
                    "bytes": record["bytes"],
                    "sha256": record["sha256"],
                }
                for record in wheels
            ],
            "pip_config": pip_config,
            "pip_check": pip_check,
            "pip_freeze": pip_freeze,
            "pip_inspect_sha256": sha256_bytes(
                pip_inspect["stdout"].encode("utf-8")
            ),
            "maude_help": maude_help,
            "observed": observed,
            "expected_runtime_distributions": expected,
            "editable_or_path_install_detected": False,
            "existing_editable_environment_used": False,
            "copied_site_packages_used": False,
            "pythonpath_injection_used": False,
            "pip_network_configuration": (
                "--no-index and --no-cache-dir; no intentional network "
                "operation (this verifier does not claim OS-level network "
                "namespace enforcement)"
            ),
            "environment_keys": sorted(env),
            "pip_environment_variables": [],
        }
        return result, commands


def _validate_source_archive(
    path: Path,
    *,
    expected_commit: str,
    operator_visible: bool,
) -> list[str]:
    errors: list[str] = []
    try:
        if _archive_commit(path) != expected_commit:
            errors.append(f"source archive commit changed: {path}")
        with tarfile.open(path, "r") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)):
                errors.append(f"{path.name}: duplicate source archive member")
            for member in members:
                member_path = Path(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or ".git" in member_path.parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or not (member.isfile() or member.isdir())
                ):
                    errors.append(
                        f"{path.name}: unsafe source archive member "
                        f"{member.name!r}"
                    )
            if operator_visible and any(
                "tests" in Path(member.name).parts
                or "architecture" in member.name.lower()
                for member in members
            ):
                errors.append(
                    f"{path.name}: operator source archive includes withheld "
                    "material"
                )
    except (CampaignError, OSError, tarfile.TarError) as exc:
        errors.append(str(exc))
    return errors


def _expected_media_paths() -> set[str]:
    wheel_names = {item["filename"] for item in CACHE_WHEELS} | {
        "ag_shell_client-0.1.0-py3-none-any.whl",
        "maude-2.4.0-py3-none-any.whl",
    }
    return {
        "sources/maude-2.4.0.tar",
        "sources/ag-shell-client-0.1.0.tar",
        *(f"wheelhouse/{name}" for name in wheel_names),
        "runtime-requirements.txt",
        "build-transcript.json",
        "clean-install-validation.json",
    }


def _validate_frozen(*, replay_install: bool = True) -> list[str]:
    errors: list[str] = []
    if not PROVENANCE_PATH.is_file():
        return [f"installation-media provenance missing: {PROVENANCE_PATH}"]
    try:
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"cannot load installation-media provenance: {exc}"]
    if provenance.get("schema") != SCHEMA:
        errors.append("installation-media provenance schema mismatch")
    if provenance.get("system_under_test_commit") != SUT_COMMIT:
        errors.append("installation-media system-under-test commit mismatch")
    if provenance.get("ag_shell_client_commit") != AG_COMMIT:
        errors.append("installation-media ag-shell-client commit mismatch")
    if provenance.get("authority_effect") != "none":
        errors.append("installation-media authority effect is not none")

    sources = provenance.get("sources")
    wheels = provenance.get("wheels")
    if not isinstance(sources, list):
        errors.append("installation-media sources are not an array")
        sources = []
    if not isinstance(wheels, list):
        errors.append("installation-media wheels are not an array")
        wheels = []

    expected_source_records = {
        str((SOURCE_DIR / "maude-2.4.0.tar").relative_to(REPO_ROOT)): {
            "commit": SUT_COMMIT,
            "operator_visible": True,
        },
        str(
            (SOURCE_DIR / "ag-shell-client-0.1.0.tar").relative_to(REPO_ROOT)
        ): {
            "commit": AG_COMMIT,
            "operator_visible": False,
        },
    }
    expected_cached = {
        str((WHEELHOUSE / item["filename"]).relative_to(REPO_ROOT)): item
        for item in CACHE_WHEELS
    }
    expected_built = {
        str(
            (
                WHEELHOUSE / "ag_shell_client-0.1.0-py3-none-any.whl"
            ).relative_to(REPO_ROOT)
        ): {
            "name": "ag-shell-client",
            "version": "0.1.0",
            "commit": AG_COMMIT,
        },
        str(
            (WHEELHOUSE / "maude-2.4.0-py3-none-any.whl").relative_to(
                REPO_ROOT
            )
        ): {
            "name": "maude",
            "version": "2.4.0",
            "commit": SUT_COMMIT,
        },
    }
    source_paths = [str(record.get("path", "")) for record in sources]
    wheel_paths = [str(record.get("path", "")) for record in wheels]
    if len(source_paths) != len(set(source_paths)):
        errors.append("installation-media provenance has duplicate source paths")
    if len(wheel_paths) != len(set(wheel_paths)):
        errors.append("installation-media provenance has duplicate wheel paths")
    if set(source_paths) != set(expected_source_records):
        errors.append("installation-media source path set mismatch")
    if set(wheel_paths) != set(expected_cached) | set(expected_built):
        errors.append("installation-media wheel path set mismatch")

    wheel_distributions: set[str] = set()
    for record in sources + wheels:
        record_path = str(record.get("path", ""))
        if record_path not in (
            set(expected_source_records) | set(expected_cached) | set(expected_built)
        ):
            continue
        path = REPO_ROOT / record_path
        try:
            path.relative_to(MEDIA_DIR)
        except ValueError:
            errors.append(f"installation-media path escapes packet: {path}")
            continue
        if not path.is_file():
            errors.append(f"installation-media artifact missing: {path}")
            continue
        if (
            path.stat().st_size != record.get("bytes")
            or sha256_file(path) != record.get("sha256")
        ):
            errors.append(f"installation-media artifact digest mismatch: {path}")
            continue
        if path.suffix == ".whl":
            try:
                actual = _wheel_metadata(path)
            except CampaignError as exc:
                errors.append(str(exc))
                continue
            expected = record.get("distribution") or {}
            if (
                _norm_name(str(actual.get("name")))
                != _norm_name(str(expected.get("name")))
                or actual.get("version") != expected.get("version")
                or actual.get("tags") != expected.get("tags")
            ):
                errors.append(f"wheel metadata changed: {path}")
            normalized = _norm_name(str(actual.get("name")))
            if normalized in wheel_distributions:
                errors.append(
                    f"duplicate normalized wheel distribution: {normalized}"
                )
            wheel_distributions.add(normalized)
            if record_path in expected_cached:
                declared = expected_cached[record_path]
                if (
                    actual.get("version") != declared["version"]
                    or normalized != _norm_name(declared["name"])
                    or record.get("sha256") != declared["sha256"]
                    or record.get("cache_body_sha256") != declared["sha256"]
                    or record.get("origin")
                    != "pre-existing local pip HTTP cache body"
                    or record.get("network_used_during_packet_copy") is not False
                ):
                    errors.append(f"cached wheel provenance changed: {path}")
            elif record_path in expected_built:
                declared = expected_built[record_path]
                if (
                    actual.get("version") != declared["version"]
                    or normalized != _norm_name(declared["name"])
                    or record.get("source_commit") != declared["commit"]
                    or record.get("origin")
                    != "sterile offline build from exact frozen Git archive"
                    or record.get("double_build_byte_reproducible") is not True
                    or record.get("rebuild_sha256") != record.get("sha256")
                    or record.get("editable") is not False
                ):
                    errors.append(f"first-party wheel provenance changed: {path}")
        elif path.suffix == ".tar" and record_path in expected_source_records:
            declared = expected_source_records[record_path]
            if (
                record.get("git_commit") != declared["commit"]
                or record.get("git_get_tar_commit_id") != declared["commit"]
                or record.get("operator_visible") is not declared["operator_visible"]
            ):
                errors.append(f"source archive provenance changed: {path}")
            errors.extend(
                _validate_source_archive(
                    path,
                    expected_commit=declared["commit"],
                    operator_visible=declared["operator_visible"],
                )
            )

    if wheel_distributions != {
        _norm_name(item["name"]) for item in CACHE_WHEELS
    } | {"maude", "ag-shell-client"}:
        errors.append("installation-media wheel distribution set mismatch")

    expected_auxiliary = {
        "runtime_requirements": LOCK_PATH,
        "build_transcript": TRANSCRIPT_PATH,
        "clean_install_validation": INSTALL_VALIDATION_PATH,
        "operator_visible_source_archive": SOURCE_DIR / "maude-2.4.0.tar",
    }
    for key, path in expected_auxiliary.items():
        try:
            if provenance.get(key) != file_record(path):
                errors.append(f"installation-media {key} record mismatch")
        except OSError as exc:
            errors.append(f"cannot inspect installation-media {key}: {exc}")

    if LOCK_PATH.is_file():
        try:
            expected_lock = _lock_text(wheels)
            if LOCK_PATH.read_text(encoding="utf-8") != expected_lock:
                errors.append(
                    "installation-media runtime lock differs from wheel records"
                )
        except (CampaignError, OSError, UnicodeDecodeError, KeyError) as exc:
            errors.append(f"cannot validate installation-media lock: {exc}")

    for path, schema in (
        (
            TRANSCRIPT_PATH,
            "maude.synthetic-install-media.build-transcript.v1",
        ),
        (
            INSTALL_VALIDATION_PATH,
            "maude.synthetic-install-media.clean-install-validation.v1",
        ),
    ):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("schema") != schema:
                errors.append(f"installation-media schema mismatch: {path}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load installation-media JSON {path}: {exc}")

    tree_paths: set[str] = set()
    if MEDIA_DIR.is_dir():
        for path in MEDIA_DIR.rglob("*"):
            relative = path.relative_to(MEDIA_DIR).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (
                stat.S_ISREG(mode) or stat.S_ISDIR(mode)
            ):
                errors.append(
                    f"installation-media contains non-regular path: {relative}"
                )
            if stat.S_ISREG(mode) and relative != "provenance.json":
                tree_paths.add(relative)
    if tree_paths != _expected_media_paths():
        errors.append(
            "installation-media file set differs from the exact expected closure"
        )

    inventory = provenance.get("media_inventory")
    actual_inventory = inventory_files(MEDIA_DIR)
    actual_without_provenance = [
        item for item in actual_inventory if item["path"] != "provenance.json"
    ]
    if inventory != actual_without_provenance:
        errors.append("installation-media inventory differs from provenance")
    if not errors and replay_install:
        try:
            replay, _commands = _verify_clean_install(wheels)
            if (
                replay.get("result") != "passed"
                or replay.get("runtime_requirements_sha256")
                != sha256_file(LOCK_PATH)
            ):
                errors.append("installation-media replay did not validate")
        except (CampaignError, OSError, ValueError, KeyError) as exc:
            errors.append(f"installation-media replay failed: {exc}")
    return errors


def prepare(
    *,
    pip_cache: Path,
    agent_governor_repo: Path,
) -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        raise CampaignError(
            "campaign manifest already exists; installation media is immutable"
        )
    if MEDIA_DIR.exists():
        raise CampaignError(
            f"refusing to overwrite installation media: {MEDIA_DIR}"
        )
    if not pip_cache.is_dir():
        raise CampaignError(f"pip HTTP cache absent: {pip_cache}")
    if not (agent_governor_repo / ".git").exists():
        raise CampaignError(
            f"Agent Governor Git object source absent: {agent_governor_repo}"
        )
    SOURCE_DIR.mkdir(parents=True)
    WHEELHOUSE.mkdir(parents=True)
    transcript: list[dict[str, Any]] = []
    try:
        sources, archive_transcript = _create_sources(
            REPO_ROOT, agent_governor_repo
        )
        transcript.extend(archive_transcript)
        cached = _copy_cache_wheels(pip_cache)
        built, build_transcript = _build_first_party_wheels(
            REPO_ROOT, agent_governor_repo
        )
        transcript.extend(build_transcript)
        wheels = sorted(
            cached + built, key=lambda item: str(item["path"])
        )
        _write_lock(wheels)
        install_validation, validation_transcript = _verify_clean_install(
            wheels
        )
        transcript.extend(validation_transcript)
        write_json(INSTALL_VALIDATION_PATH, install_validation)
        write_json(
            TRANSCRIPT_PATH,
            {
                "schema": "maude.synthetic-install-media.build-transcript.v1",
                "source_repositories_used_only_during_packet_preparation": True,
                "existing_editable_environment_used": False,
                "live_sibling_checkout_required_after_freeze": False,
                "network_controls": (
                    "all pip preparation commands used --no-index; no "
                    "intentional network operation occurred; preparation did "
                    "not run in a separate OS network namespace"
                ),
                "commands": transcript,
            },
        )
        provenance = {
            "schema": SCHEMA,
            "authority_effect": "none",
            "system_under_test_commit": SUT_COMMIT,
            "ag_shell_client_commit": AG_COMMIT,
            "python": _command(["/usr/bin/python3", "--version"]),
            "source_repository_use": (
                "exact Git objects were read only during packet preparation; "
                "the campaign materializer and model sessions use only these "
                "frozen archives and wheels"
            ),
            "cache_provenance": (
                "each third-party body was already present in the local pip "
                "HTTP cache and selected by an exact predeclared SHA-256; no "
                "resolver or intentional network fetch populated the packet. "
                "The self-describing wheel bytes and cache-sidecar hashes are "
                "not an authenticated upstream index, signature, or TUF proof."
            ),
            "sources": sources,
            "wheels": wheels,
            "runtime_requirements": file_record(LOCK_PATH),
            "build_transcript": file_record(TRANSCRIPT_PATH),
            "clean_install_validation": file_record(
                INSTALL_VALIDATION_PATH
            ),
            "operator_visible_source_archive": file_record(
                SOURCE_DIR / "maude-2.4.0.tar"
            ),
            "operator_visible_wheelhouse": False,
            "network_controls": (
                "pip used --no-index and the preparation made no intentional "
                "network operation; no OS-level network namespace was imposed"
            ),
            "editable_install_used": False,
            "copied_site_packages_used": False,
            "pythonpath_injection_used": False,
            "reproducibility_scope": (
                "the two first-party wheel byte streams were rebuilt twice "
                "under the same frozen inputs and compared. Temporary build "
                "and verifier path strings in transcripts are evidence, not "
                "claimed reproducible packet bytes."
            ),
        }
        provenance["media_inventory"] = [
            item
            for item in inventory_files(MEDIA_DIR)
            if item["path"] != "provenance.json"
        ]
        write_json(PROVENANCE_PATH, provenance)
        errors = _validate_frozen(replay_install=False)
        if errors:
            raise CampaignError("\n".join(errors))
        return provenance
    except Exception:
        # This directory is not a frozen packet until provenance validates.
        # Leave failed bytes for diagnosis under /tmp, never as plausible media.
        diagnostic = Path(tempfile.mkdtemp(prefix="maude-install-media-failed-"))
        if MEDIA_DIR.exists():
            shutil.move(str(MEDIA_DIR), diagnostic / "installation-media")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="prepare or validate frozen offline installation media"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--pip-cache", type=Path, default=DEFAULT_PIP_CACHE
    )
    parser.add_argument(
        "--agent-governor-repo", type=Path, default=DEFAULT_AG_REPO
    )
    args = parser.parse_args()
    try:
        if args.validate:
            errors = _validate_frozen()
            if errors:
                print(json.dumps({"ok": False, "errors": errors}, indent=2))
                return 1
            print(
                json.dumps(
                    {
                        "ok": True,
                        "provenance_sha256": sha256_file(PROVENANCE_PATH),
                        "wheel_count": len(
                            list(WHEELHOUSE.glob("*.whl"))
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        result = prepare(
            pip_cache=args.pip_cache,
            agent_governor_repo=args.agent_governor_repo,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "sources": len(result["sources"]),
                    "wheels": len(result["wheels"]),
                    "provenance_sha256": sha256_file(PROVENANCE_PATH),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (CampaignError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
