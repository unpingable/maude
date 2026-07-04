# SPDX-License-Identifier: Apache-2.0
"""File-based witness resolver (CD-4 wiring, v0).

Resolves governance citations against a directory of EXTERNALLY produced
artifacts — the AG conveyor's serialized objects (queue files, playbook
specs, ration cards, approval records). Maude reads bytes and hashes them;
it never interprets AG semantics (the digest either matches the citation or
it does not — see envelope.admit_for_execution).

Resolution rules (deliberately dumb):
- ``sha256:<hex>`` citations: scan the witness directory (non-recursive by
  default) for a file whose content hashes to the citation. Content
  addressing IS the lookup — filenames carry no authority.
- non-digest refs (e.g. ``approval_ref``): resolve ``<sanitized-ref>`` as a
  filename in the directory; the file's bytes are the recorded act. The
  RESOLVER only proves the record exists outside the plan; what the record
  means stays with its producer.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_SHA256_PREFIX = "sha256:"
_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_ref(ref: str) -> str:
    """A ref's on-disk witness filename: non-path-safe chars become ``_``."""
    return _SANITIZE.sub("_", ref)


def file_witness_resolver(witness_dir: str | Path, *, recursive: bool = False):
    """Build a :data:`~maude.plan.envelope.WitnessResolver` over a directory.

    Missing directory → every citation resolves to ``None`` (governed plans
    then refuse fail-closed, which is the point).
    """
    root = Path(witness_dir)

    def _iter_files():
        if not root.is_dir():
            return
        it = root.rglob("*") if recursive else root.glob("*")
        for p in sorted(it):
            if p.is_file():
                yield p

    def resolve(citation: str) -> bytes | None:
        if citation.startswith(_SHA256_PREFIX):
            for p in _iter_files():
                data = p.read_bytes()
                if _SHA256_PREFIX + hashlib.sha256(data).hexdigest() == citation:
                    return data
            return None
        candidate = root / sanitize_ref(citation)
        if candidate.is_file():
            return candidate.read_bytes()
        return None

    return resolve
