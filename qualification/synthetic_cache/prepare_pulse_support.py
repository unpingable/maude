#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare fresh Pulse credentials, exact host support config and closed resolver.

No measurement, receipt, support judgment or permission is created. The caller
must separately invoke Pulse produce/ingest and inspect its result. Field names
and supported identities follow the public Pulse host-load v1 source contract.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess

HERE = Path(__file__).resolve().parent
SUPPORTED_SEMANTICS = {
    'sha256:f500ddf6bf3b61e5e65bcec8fbf8bfa2b38728fa9949c9406480b6941a0cbec0',
    'sha256:fb7bce89e23f88174e87309002b78a9fc78e45db748252cc76aff0ecade79490',
}
IDENTITIES = {
    'question': {'id': 'nq.host.load_pressure', 'version': '1',
                 'digest': 'sha256:7de797da3d9d3a6ae8e21e5d77b95095453336cd38f606ffb3eb29ff6a32e2cf'},
    'profile': {'id': 'nq.host', 'version': '1',
                'digest': 'sha256:c8c10fed1cc5598d953b4defbc98e8c106fc59e035c249d43681698a5c7b4ff9'},
    'threshold_policy': {'id': 'nq.host.load_pressure.threshold_policy', 'version': '1',
                         'digest': 'sha256:52b815509d26878fad1f88c6352bcd17537452f704072e56664e18434fee855e'},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def read(path, maximum=8 * 1024 * 1024):
    if not path.is_absolute():
        raise ValueError('absolute input path required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular input required')
        raw = stream.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise ValueError('empty or oversized input')
    return raw


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def pin(path, expected, executable=False):
    raw = read(path, 128 * 1024 * 1024)
    if digest(raw) != expected or (executable and not os.access(path, os.X_OK)):
        raise ValueError('input pin or executable mode differs')
    return raw


def write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def validate_observation(artifact, request):
    if artifact.get('schema') != 'nq.diagnostic_execution.v2':
        raise ValueError('NQ diagnostic execution v2 required')
    if artifact.get('profile_semantic_id') not in SUPPORTED_SEMANTICS:
        raise ValueError('Pulse has not enrolled this exact NQ profile identity')
    for name, identity in IDENTITIES.items():
        if artifact.get(name) != identity:
            raise ValueError('unsupported exact ' + name)
    if artifact.get('outcome', {}).get('condition') not in ('present', 'explicitly_absent'):
        raise ValueError('unresolved host diagnostic cannot supply determinate support')
    if request.get('schema') != 'nightshift.canonical_cycle_request.v1' or request.get('proposal') is not None:
        raise ValueError('posture-only Nightshift request required')
    inputs = request.get('inputs', {})
    rows = inputs.get('inputs', [])
    if len(rows) != 1 or rows[0].get('artifact') != artifact:
        raise ValueError('request must contain this exact acquired diagnostic')
    for value in (artifact.get('artifact_id'), inputs.get('inputs_id'), artifact.get('subject', {}).get('scope', {}).get('digest')):
        if not isinstance(value, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
            raise ValueError('invalid diagnostic, input or scope identity')


def build(args):
    artifact_bytes, request_bytes = read(args.artifact), read(args.posture_request)
    artifact, request = json.loads(artifact_bytes), json.loads(request_bytes)
    validate_observation(artifact, request)
    for token in (args.authority_id, args.producer_id):
        if not token or len(token) > 256 or any(c.isspace() for c in token):
            raise ValueError('explicit bounded producer and custody authority identities required')
    pin(args.pulse, args.pulse_sha256, True)
    pin(args.python, args.python_sha256, True)
    pin(args.openssl, args.openssl_sha256, True)
    pin(args.sealer, args.sealer_sha256)
    root = args.output
    if not root.is_absolute() or root.exists() or root.is_symlink() or not root.parent.is_dir():
        raise ValueError('fresh absolute output below an existing owned directory required')
    root.mkdir(mode=0o700)
    for name in ('outgoing', 'receipts'):
        (root / name).mkdir(mode=0o700)
    # Only this freshly generated demo key is read. No application credentials
    # or provider settings are searched, imported, printed or embedded in JSON.
    key = root / 'producer.pk8'
    subprocess.run([str(args.openssl), 'genpkey', '-algorithm', 'ED25519', '-outform', 'DER', '-out', str(key)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=8, check=True)
    os.chmod(key, 0o600)
    private = read(key, 128)
    if len(private) != 48 or private[:16] != bytes.fromhex('302e020100300506032b657004220420'):
        raise ValueError('unexpected Ed25519 PKCS8 representation')
    public = subprocess.run([str(args.openssl), 'pkey', '-inform', 'DER', '-in', str(key), '-pubout', '-outform', 'DER'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=True).stdout
    if len(public) != 44 or public[:12] != bytes.fromhex('302a300506032b6570032100'):
        raise ValueError('unexpected Ed25519 public key representation')
    write(root / 'producer.hex', private[16:].hex().encode())
    public_key = public[12:]
    config = {
        'schema': 'pulse.nq_host_load_pressure_support_config.v1',
        'authority_id': args.authority_id, 'support_family': 'pulse.nq_host_load_pressure.v1',
        'producer_id': args.producer_id, 'producer_key_id': 'pulse-key:' + digest(public_key),
        'producer_public_key_hex': public_key.hex(), 'producer_private_key_path': str(root / 'producer.hex'),
        'subject_id': artifact['subject']['id'], 'scope_id': artifact['subject']['scope']['digest'],
        'vantage_id': artifact['vantage']['id'], **IDENTITIES,
        'profile_semantic_id': artifact['profile_semantic_id'],
        'outgoing_directory': str(root / 'outgoing'), 'receipt_directory': str(root / 'receipts'),
        'expected_diagnostic': {'diagnostic_inputs_id': request['inputs']['inputs_id'],
                                'artifact_ids': [artifact['artifact_id']],
                                'expected_state': artifact['outcome']['condition']},
    }
    config_path = root / 'config.json'
    write(config_path, canonical(config))
    enrollment = {'schema': 'pulse.nq_host_load_pressure.closed_resolver_launcher_enrollment.v1',
                  'resolver_program': str(args.pulse), 'resolver_sha256': args.pulse_sha256,
                  'config_path': str(config_path), 'config_sha256': digest(canonical(config)),
                  'python_interpreter': str(args.python), 'python_sha256': args.python_sha256}
    enrollment_path = root / 'launcher-enrollment.json'
    write(enrollment_path, canonical(enrollment))
    spec = importlib.util.spec_from_file_location('public_pulse_launcher', args.sealer)
    sealer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sealer)
    admitted = sealer.load_enrollment(enrollment_path)
    sealer.exclusive(root / 'pulse-support-resolver', sealer.launcher_bytes(admitted), 0o700)
    result = {'schema': 'maude.public-pulse-support-preparation/v1',
              'artifact_sha256': digest(artifact_bytes), 'request_sha256': digest(request_bytes),
              'config': str(config_path), 'config_sha256': enrollment['config_sha256'],
              'resolver': str(root / 'pulse-support-resolver'),
              'measurements_created': 0, 'receipts_created': 0, 'runtime_permission': False,
              'next': 'invoke Pulse produce and ingest once; inspect original records before any retry'}
    write(root / 'preparation.json', canonical(result))
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('artifact', 'posture-request', 'output', 'pulse', 'python', 'openssl', 'sealer'):
        p.add_argument('--' + name, type=Path, required=True)
    for name in ('pulse-sha256', 'python-sha256', 'openssl-sha256', 'sealer-sha256', 'authority-id', 'producer-id'):
        p.add_argument('--' + name, required=True)
    return p


if __name__ == '__main__':
    print(json.dumps(build(parser().parse_args()), sort_keys=True))
