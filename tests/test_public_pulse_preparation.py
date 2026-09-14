import copy
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / 'qualification/synthetic_cache/prepare_pulse_support.py'
spec = importlib.util.spec_from_file_location('public_pulse_preparation', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    artifact = {'schema': 'nq.diagnostic_execution.v2', **module.IDENTITIES,
                'profile_semantic_id': sorted(module.SUPPORTED_SEMANTICS)[0],
                'artifact_id': 'sha256:' + '1' * 64,
                'subject': {'id': 'host:disposable-demo', 'scope': {'digest': 'sha256:' + '2' * 64}},
                'vantage': {'id': 'local:fixture'}, 'outcome': {'condition': 'explicitly_absent'}}
    request = {'schema': 'nightshift.canonical_cycle_request.v1', 'proposal': None,
               'inputs': {'inputs_id': 'sha256:' + '3' * 64, 'inputs': [{'artifact': artifact}]}}
    return artifact, request


def test_exact_observation_config_shape_only():
    artifact, request = fixture()
    module.validate_observation(artifact, request)


@pytest.mark.parametrize('change', ['profile', 'unresolved', 'request_artifact', 'proposal', 'digest'])
def test_substitution_or_unresolved_observation_refuses(change):
    artifact, request = copy.deepcopy(fixture())
    if change == 'profile': artifact['profile_semantic_id'] = 'sha256:' + '4' * 64
    elif change == 'unresolved': artifact['outcome']['condition'] = 'unknown'
    elif change == 'request_artifact': request['inputs']['inputs'] = []
    elif change == 'proposal': request['proposal'] = {'not': 'posture-only'}
    elif change == 'digest': request['inputs']['inputs_id'] = 'not-a-digest'
    with pytest.raises(ValueError): module.validate_observation(artifact, request)


def test_read_refuses_symlink_and_bounded_input(tmp_path):
    source = tmp_path / 'input.json'
    source.write_bytes(b'12345')
    linked = tmp_path / 'link'
    linked.symlink_to(source)
    with pytest.raises(OSError): module.read(linked)
    with pytest.raises(ValueError): module.read(source, 4)
