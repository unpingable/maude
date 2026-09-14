import copy
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "qualification/synthetic_cache/helpers/verify-cache-observation-family.py"
SPEC = importlib.util.spec_from_file_location("family", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def request():
    return {"schema": "nightshift.canonical_cycle_request.v1",
            "request_id": "sha256:" + "1" * 64,
            "slot": {"policy_id": "policy", "configuration_version": "config",
                     "subject_id": "subject", "scope_id": "scope",
                     "scheduler_clock_id": "clock", "occurrence": 1},
            "policy": {"closed": "material"}}


def test_same_family_requires_later_occurrence():
    before = request()
    after = copy.deepcopy(before)
    after["request_id"] = "sha256:" + "2" * 64
    after["slot"]["occurrence"] = 2
    assert MODULE.verify(before, after)["result"] == "exact_family"
    after["slot"]["occurrence"] = 1
    with pytest.raises(ValueError, match="later occurrence"):
        MODULE.verify(before, after)


@pytest.mark.parametrize("field", MODULE.FIELDS)
def test_every_family_coordinate_is_exact(field):
    before = request()
    after = copy.deepcopy(before)
    after["slot"]["occurrence"] = 2
    after["slot"][field] = "different"
    with pytest.raises(ValueError, match="exact governed observation family"):
        MODULE.verify(before, after)
