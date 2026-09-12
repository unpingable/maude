"""Packaging boundaries for core authoring and transitional classic RPC."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_classic_rpc_dependency_is_optional_and_pinned() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    assert not any(item.startswith("ag-shell-client") for item in dependencies)

    classic = project["project"]["optional-dependencies"]["classic-rpc"]
    assert len(classic) == 1
    assert classic[0].startswith("ag-shell-client @ git+https://github.com/")
    assert "agent_governor.git@df61549a5e9a0dcc63ebe21efc90bd8958f64123" in classic[0]
    assert classic[0].endswith("#subdirectory=libs/ag_shell_client")


def test_classic_entrypoint_explains_missing_optional_dependency(tmp_path: Path) -> None:
    (tmp_path / "ag_shell_client.py").write_text(
        "raise ModuleNotFoundError(\"blocked fixture\", name=\"ag_shell_client\")\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), str(ROOT / "src")]
    )
    result = subprocess.run(
        [sys.executable, "-c", "import maude.app"],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode != 0
    assert "pip install 'maude[classic-rpc]'" in result.stderr


def test_core_authoring_imports_without_classic_rpc(tmp_path: Path) -> None:
    (tmp_path / "ag_shell_client.py").write_text(
        "raise ModuleNotFoundError(\"blocked fixture\", name=\"ag_shell_client\")\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), str(ROOT / "src")]
    )
    result = subprocess.run(
        [sys.executable, "-c", "import maude.plan; import maude.custody"],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
