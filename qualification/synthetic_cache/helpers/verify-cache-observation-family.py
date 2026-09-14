#!/usr/bin/env python3
"""Verify, never reconstruct, Nightshift's exact observation-family relation."""
import argparse
import json
import os
from pathlib import Path

MAX = 16 * 1024 * 1024


def load(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        raw = source.read(MAX + 1)
    if not raw or len(raw) > MAX:
        raise ValueError('request is empty or oversized')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('request must be one object')
    return value

FIELDS = ('policy_id', 'configuration_version', 'subject_id', 'scope_id', 'scheduler_clock_id')


def verify(predecessor, successor):
    for value in (predecessor, successor):
        if value.get('schema') != 'nightshift.canonical_cycle_request.v1':
            raise ValueError('unsupported request schema')
    before, after = predecessor['slot'], successor['slot']
    if any(before.get(key) != after.get(key) or before.get(key) is None for key in FIELDS):
        raise ValueError('successor is not in the exact governed observation family')
    if predecessor['policy'] != successor['policy']:
        raise ValueError('policy material differs despite claimed identity')
    if after['occurrence'] <= before['occurrence']:
        raise ValueError('a distinct later occurrence is required')
    return {'schema':'constellation.observation-family-check/v1', 'result':'exact_family',
            'family':{key:before[key] for key in FIELDS},
            'predecessor_request_id':predecessor['request_id'], 'successor_request_id':successor['request_id']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predecessor', type=Path, required=True)
    parser.add_argument('--successor', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(load(args.predecessor), load(args.successor)), sort_keys=True))
