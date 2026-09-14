import importlib.util
import os
from pathlib import Path
import sys

import pytest

SOURCE = Path(__file__).parents[1] / "qualification/synthetic_cache/connected_cache_process.py"
SPEC = importlib.util.spec_from_file_location("connected_cache_process", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_retains_both_streams_and_nonzero_status_without_interpretation(tmp_path):
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    result = MODULE.run_bounded(
        [sys.executable, "-c", "import sys; print('out'); print('err',file=sys.stderr); raise SystemExit(7)"],
        stdout_path=stdout, stderr_path=stderr, timeout=2,
    )
    assert result.returncode == 7
    assert stdout.read_bytes() == b"out\n" and stderr.read_bytes() == b"err\n"
    assert not result.stdout_truncated and not result.stderr_truncated


def test_output_excess_is_bounded_uncertain_and_process_group_stopped(tmp_path):
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    with pytest.raises(MODULE.BoundedOutputExceeded) as caught:
        MODULE.run_bounded(
            [sys.executable, "-c", "import sys,time; sys.stdout.write('x'*4096); sys.stdout.flush(); time.sleep(10)"],
            stdout_path=stdout, stderr_path=stderr, timeout=3, max_stream_bytes=64,
        )
    assert caught.value.status == "uncertain"
    assert caught.value.result.stdout_truncated
    assert caught.value.result.stdout_bytes == 4096
    assert stdout.stat().st_size == 64


def test_timeout_retains_prefix_and_reports_uncertain(tmp_path):
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    with pytest.raises(MODULE.UncertainProcessTimeout) as caught:
        MODULE.run_bounded(
            [sys.executable, "-c", "import sys,time; print('before',flush=True); print('diagnostic',file=sys.stderr,flush=True); time.sleep(10)"],
            stdout_path=stdout, stderr_path=stderr, timeout=0.1,
        )
    assert caught.value.status == "uncertain"
    assert stdout.read_bytes() == b"before\n"
    assert stderr.read_bytes() == b"diagnostic\n"
    assert caught.value.result.returncode < 0


def test_preflight_refuses_existing_stream_before_start(tmp_path):
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    stdout.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh absolute"):
        MODULE.run_bounded(
            [sys.executable, "-c", "raise SystemExit(0)"],
            stdout_path=stdout, stderr_path=stderr, timeout=1,
        )
    assert stdout.read_bytes() == b"retained" and not stderr.exists()


def test_exited_parent_with_pipe_holding_child_is_cleaned_as_typed_uncertain(tmp_path):
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    child_code = "import os,time; print(os.getpid(),flush=True); time.sleep(30)"
    parent_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "raise SystemExit(0)"
    )
    with pytest.raises(MODULE.UncertainDrainLoss) as caught:
        MODULE.run_bounded(
            [sys.executable, "-c", parent_code],
            stdout_path=stdout, stderr_path=stderr, timeout=5,
        )
    assert caught.value.status == "uncertain"
    child_pid = int(stdout.read_text().strip())
    try:
        os.kill(child_pid, 0)
    except ProcessLookupError:
        pass
    else:
        stat = Path(f"/proc/{child_pid}/stat")
        assert stat.exists() and stat.read_text().split()[2] == "Z"
