#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build or verify the qualification-results byte inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = QUALIFICATION_DIR / "results"
MANIFEST = RESULTS_DIR / "results-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _members() -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(RESULTS_DIR).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(RESULTS_DIR.rglob("*"))
        if path.is_file() and path != MANIFEST
    ]


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def build() -> dict[str, Any]:
    members = _members()
    return {
        "schema": (
            "maude.synthetic-operator."
            "grader-qualification-results-manifest.v1"
        ),
        "members": members,
        "file_count": len(members),
        "total_bytes": sum(value["bytes"] for value in members),
        "self_exclusion": (
            "results-manifest.json is excluded to avoid a recursive digest"
        ),
        "generation_four_artifacts_included": False,
        "generation_five_campaign_artifacts_included": False,
        "authority_effect": "none",
    }


def write() -> None:
    value = build()
    temporary = MANIFEST.with_name(f".{MANIFEST.name}.tmp")
    temporary.write_bytes(_canonical_bytes(value))
    temporary.replace(MANIFEST)


def verify() -> list[str]:
    try:
        observed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"cannot load results manifest: {exc}"]
    expected = build()
    return [] if observed == expected else ["results manifest differs"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    if arguments.write:
        write()
    errors = verify()
    print(
        json.dumps(
            {
                "errors": errors,
                "file_count": build()["file_count"],
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
