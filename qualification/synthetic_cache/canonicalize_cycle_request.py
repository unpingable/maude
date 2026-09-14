#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Remove optional CLI line framing from an exact Nightshift cycle request.

This adapter does not prepare, modify, admit, or authorize the request. It
preserves its existing identity and creates a new file for interfaces requiring
canonical file bytes rather than the CLI's newline-terminated object.
"""
import argparse
import os
from pathlib import Path

from seal_cycle_handoff import exact, read_cycle_request
from maude.custody import _canonical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = read_cycle_request(exact(args.input, 16 * 1024 * 1024))
    if request.get("schema") != "nightshift.canonical_cycle_request.v1":
        raise ValueError("unsupported cycle request schema")
    data = _canonical(request)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
