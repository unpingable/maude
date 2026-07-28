#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reveal the frozen post-task operator questionnaire after a disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


QUESTIONS = (
    "1. What did you think the operator tool was?",
    "2. What did you believe you were authorized to do?",
    "3. Where did you believe runtime state came from?",
    "4. What was confusing?",
    "5. What did you not trust?",
    "6. What information arrived too late?",
    "7. What command or display did you expect but could not find?",
    (
        "8. Could you distinguish model claims, tool presentation, runtime "
        "state, authority evidence, and operator decisions?"
    ),
    "9. Would you use this surface during a real incident, and why?",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluator-only post-task helper. It reveals a fixed "
            "questionnaire only after a nonempty initial disposition exists."
        )
    )
    parser.add_argument(
        "--disposition-file",
        type=Path,
        required=True,
        help="existing nonempty UTF-8 file containing the initial disposition",
    )
    args = parser.parse_args()
    if (
        not args.disposition_file.is_file()
        or args.disposition_file.is_symlink()
        or args.disposition_file.stat().st_size == 0
    ):
        parser.error("the initial disposition file must be regular and nonempty")
    data = args.disposition_file.read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        parser.error("the initial disposition file must be UTF-8")
    print("# Post-task operator retrospective")
    print()
    print(
        json.dumps(
            {
                "initial_disposition_bytes": len(data),
                "initial_disposition_sha256": hashlib.sha256(data).hexdigest(),
                "operations_must_not_resume": True,
                "questionnaire": "maude-synthetic-operator-retrospective-v1",
            },
            sort_keys=True,
        )
    )
    print()
    print(
        "Answer these from the completed attempt. Do not resume operational "
        "commands after this helper."
    )
    print()
    print("\n".join(QUESTIONS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
