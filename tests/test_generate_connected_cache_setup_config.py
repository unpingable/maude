import importlib.util
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "qualification/synthetic_cache/generate_connected_cache_setup_config.py"
SPEC = importlib.util.spec_from_file_location("generate_connected_cache_setup", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_generator_exposes_every_closed_prerequisite_and_identity():
    help_text = MODULE.parser().format_help()
    for name in MODULE.SETUP.PROGRAMS:
        assert "--" + name.replace("_", "-") in help_text
    for option in ("--pulse-launcher-sealer", "--maude-source-revision", "--nq-subject",
                   "--nq-scope-id", "--qualification-occurrence-id",
                   "--successor-occurrence-id", "--subject-digest", "--role-digest"):
        assert option in help_text
    assert ".campaign-artifacts" not in SOURCE.read_text()


def test_pinned_refuses_non_executable_before_hash(tmp_path):
    path = tmp_path / "plain"
    path.write_text("plain")
    try:
        MODULE.pinned(path)
    except ValueError as error:
        assert "requested mode" in str(error)
    else:
        raise AssertionError("non-executable prerequisite accepted")
