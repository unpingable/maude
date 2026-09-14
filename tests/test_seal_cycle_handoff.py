"""CLI framing does not change a request identity or relax canonical input."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from maude.custody import _canonical

source = Path(__file__).parents[1] / "qualification/synthetic_cache/seal_cycle_handoff.py"
spec = importlib.util.spec_from_file_location("seal_cycle_handoff", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("suffix", [b"", b"\n"])
def test_canonical_cli_object_preserves_request_identity(suffix):
    request = {"request_id": "sha256:" + "a" * 64, "note": "exact request"}
    assert module.read_cycle_request(_canonical(request) + suffix) == request


@pytest.mark.parametrize("data", [
    b'{"request_id":"x"}\n\n',
    b'{"request_id":"x"}\r\n',
    b' {"request_id":"x"}',
    b'{"request_id": "x"}',
    b'{"request_id":"x","request_id":"x"}',
    b'{"z":0,"request_id":"x"}',
    b'{"request_id":null}',
    b'[]',
])
def test_noncanonical_or_ambiguous_input_refuses(data):
    with pytest.raises(ValueError):
        module.read_cycle_request(data)


def test_cli_framing_adapter_preserves_bytes_and_refuses_output_replacement(tmp_path):
    request = {"schema": "nightshift.canonical_cycle_request.v1",
               "request_id": "sha256:" + "b" * 64}
    original = _canonical(request)
    input_path, output = tmp_path / "cli.json", tmp_path / "request.json"
    input_path.write_bytes(original + b"\n")
    command = [sys.executable, str(source.with_name("canonicalize_cycle_request.py")),
               "--input", str(input_path), "--output", str(output)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert output.read_bytes() == original
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == original
