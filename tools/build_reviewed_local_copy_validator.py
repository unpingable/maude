#!/usr/bin/python3.12
"""Build the closed, validate-only reviewed-local-copy validator artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path


INTERPRETER = Path("/usr/bin/python3.12")
PYAML_ROOT = Path("/usr/lib/python3/dist-packages/yaml")
PYAML_NOTICE = Path("/usr/share/doc/python3-yaml/copyright")
SHEBANG = b"#!/usr/bin/python3.12 -I\n"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def add_file(archive: zipfile.ZipFile, name: str, source: Path, manifest: dict[str, str]) -> None:
    data = source.read_bytes()
    entry = zipfile.ZipInfo(name, ZIP_TIME)
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, data)
    manifest[name] = digest(data)


def add_bytes(archive: zipfile.ZipFile, name: str, data: bytes, manifest: dict[str, str]) -> None:
    entry = zipfile.ZipInfo(name, ZIP_TIME)
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, data)
    manifest[name] = digest(data)


def source_revision(root: Path) -> str:
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    if dirty:
        raise SystemExit("validator package requires a clean source revision")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def build(output: Path, expected_revision: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    actual_revision = source_revision(root)
    if expected_revision != actual_revision:
        raise SystemExit("source revision does not match the checked-out validator source")
    if not output.is_absolute() or output.exists():
        raise SystemExit("validator output must be an absent absolute path")
    maude_root = root / "src" / "maude"
    entries: list[tuple[str, Path]] = [("maude/__init__.py", maude_root / "__init__.py")]
    closure = [
        "checks.py", "compiler.py", "document.py", "envelope.py", "local_compose.py",
        "ration_containment.py", "reviewed_local_copy.py", "store.py",
    ]
    entries.extend((f"maude/plan/{name}", maude_root / "plan" / name) for name in closure)
    entries.extend((f"yaml/{path.name}", path) for path in sorted(PYAML_ROOT.glob("*.py")))
    entries.extend([
        ("LICENSE", root / "LICENSE"),
        ("NOTICE", root / "NOTICE"),
        ("THIRD_PARTY_NOTICES/PyYAML-Debian-copyright", PYAML_NOTICE),
    ])
    missing = [str(path) for _, path in entries if not path.is_file()]
    if missing or not INTERPRETER.is_file():
        raise SystemExit(f"validator import closure is unavailable: {missing or INTERPRETER}")

    main = (
        b"import sys\n"
        b"from maude.plan.reviewed_local_copy import main\n"
        b"if len(sys.argv) < 2 or sys.argv[1] != 'validate':\n"
        b"    raise SystemExit('only the validate operation is available')\n"
        b"raise SystemExit(main(sys.argv[1:]))\n"
    )
    package_init = b"# Closed validator import package; exports intentionally omitted.\n"
    manifest: dict[str, str] = {
        "__main__.py": digest(main),
        "maude/plan/__init__.py": digest(package_init),
    }
    payload_fd, payload_name = tempfile.mkstemp(prefix=".reviewed-local-copy-validator-", dir=output.parent)
    os.close(payload_fd)
    payload = Path(payload_name)
    output_fd, output_name = tempfile.mkstemp(prefix=".reviewed-local-copy-validator-", dir=output.parent)
    os.close(output_fd)
    temporary_output = Path(output_name)
    try:
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
            add_bytes(archive, "__main__.py", main, manifest)
            add_bytes(archive, "maude/plan/__init__.py", package_init, manifest)
            for name, source in entries:
                add_file(archive, name, source, manifest)
        temporary_output.write_bytes(SHEBANG + payload.read_bytes())
        temporary_output.chmod(0o755)
        os.link(temporary_output, output)
    finally:
        payload.unlink(missing_ok=True)
        temporary_output.unlink(missing_ok=True)
    return {
        "schema": "maude.reviewed-local-copy-validator-package/v1",
        "interpreter": str(INTERPRETER),
        "interpreter_sha256": digest(INTERPRETER.read_bytes()),
        "python_isolated_mode": True,
        "stdlib_trust": "the fixed interpreter and its standard library remain deployment-trusted",
        "source_revision": actual_revision,
        "closure": "maude.reviewed-local-copy-validator/imports-v1",
        "archive_sha256": digest(output.read_bytes()),
        "entries": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    if args.output.exists() or args.manifest.exists():
        parser.error("output and manifest must be absent")
    record = build(args.output, args.source_revision)
    args.manifest.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
