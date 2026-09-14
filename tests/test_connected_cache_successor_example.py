# SPDX-License-Identifier: Apache-2.0
"""Component tests for portable accepted-cache compilation glue."""

import importlib.util
from pathlib import Path
import sqlite3

import pytest

SOURCE = Path(__file__).parents[1] / "qualification" / "synthetic_cache" / "compile_accepted_cache_actions.py"
SPEC = importlib.util.spec_from_file_location("accepted_actions", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bounded_regular_reader_refuses_symlink_and_oversize(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"{}")
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    with pytest.raises(OSError):
        MODULE.read_regular(alias, 32)
    target.write_bytes(b"x" * 33)
    with pytest.raises(ValueError, match="bounded regular"):
        MODULE.read_regular(target, 32)


def test_pins_are_exact_lowercase_sha256():
    raw = b"accepted bytes"
    MODULE.require_pin(raw, MODULE.sha256(raw), "fixture")
    with pytest.raises(ValueError, match="lowercase"):
        MODULE.require_pin(raw, "A" * 64, "fixture")
    with pytest.raises(ValueError, match="differ"):
        MODULE.require_pin(raw, "0" * 64, "fixture")


def test_store_snapshot_is_fresh_and_source_remains_unchanged(tmp_path):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as database:
        database.execute("create table records(value text not null)")
        database.execute("insert into records values ('retained')")
    before = source.read_bytes()
    destination = tmp_path / "copy.sqlite"
    MODULE.snapshot_store(source, destination, MODULE.sha256(before))
    assert source.read_bytes() == before
    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as database:
        assert database.execute("select value from records").fetchone() == ("retained",)
    with pytest.raises(FileExistsError):
        MODULE.snapshot_store(source, destination, MODULE.sha256(before))
    Path(str(source) + "-wal").write_bytes(b"sidecar")
    with pytest.raises(ValueError, match="sidecar"):
        MODULE.snapshot_store(source, tmp_path / "second.sqlite", MODULE.sha256(before))


def test_cli_requires_all_explicit_path_and_identity_inputs():
    help_text = MODULE.parser().format_help()
    for option in ("--maude-source", "--maude-local-compose-sha256",
                   "--accepted-store", "--accepted-store-sha256",
                   "--bundle", "--bundle-sha256", "--compiler-input",
                   "--compiler-input-sha256", "--output"):
        assert option in help_text
    assert ".campaign-artifacts" not in SOURCE.read_text()
