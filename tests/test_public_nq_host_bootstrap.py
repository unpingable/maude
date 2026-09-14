import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "qualification/synthetic_cache/public-nq-host-bootstrap.py"
spec = importlib.util.spec_from_file_location("bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec); spec.loader.exec_module(bootstrap)

def args(root, helper):
    class A: pass
    a=A(); a.output=root/"nq.toml"; a.state_root=root/"state"; a.helper=helper
    a.working_directory=root; a.instance="public-host-001"; a.execution_account="fixture"
    a.subject="host:fixture"; a.scope_id="fixture"; a.allow_same_identity_in_debug=True
    return a

def test_full_public_host_watcher_and_digest(tmp_path):
    helper=tmp_path/"nq-host-helper"; helper.write_text("fixture")
    value=bootstrap.prepare(args(tmp_path,helper)); text=(tmp_path/"nq.toml").read_text()
    assert value["helper_sha256"].startswith("sha256:")
    for field in ("[[watchers]]", 'id = "nq.host"', "read_procfs", "max_response_bytes"):
        assert field in text

def test_missing_helper_refuses_before_allocation(tmp_path):
    a=args(tmp_path,tmp_path/"missing")
    try: bootstrap.prepare(a)
    except ValueError: pass
    else: raise AssertionError("missing helper accepted")
    assert not a.output.exists() and not a.state_root.exists()
