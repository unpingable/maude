#!/usr/bin/python3.12
"""Build the closed, validate-only reviewed-local-copy validator artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path


INTERPRETER = Path("/usr/bin/python3.12")
PYAML_ROOT = Path("/usr/lib/python3/dist-packages/yaml")
SHEBANG = b"#!/usr/bin/python3.12\n"
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


def build(output: Path) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    maude_root = root / "src" / "maude"
    entries: list[tuple[str, Path]] = [("maude/__init__.py", maude_root / "__init__.py")]
    entries.extend(
        (f"maude/plan/{path.name}", path)
        for path in sorted((maude_root / "plan").glob("*.py"))
    )
    entries.extend((f"yaml/{path.name}", path) for path in sorted(PYAML_ROOT.glob("*.py")))
    missing = [str(path) for _, path in entries if not path.is_file()]
    if missing or not INTERPRETER.is_file():
        raise SystemExit(f"validator import closure is unavailable: {missing or INTERPRETER}")

    main = (
        b"import sys\n"
        b"from maude.plan.reviewed_local_copy import main\n"
        b"raise SystemExit(main(['validate', *sys.argv[1:]]))\n"
    )
    manifest: dict[str, str] = {"__main__.py": digest(main)}
    payload = output.with_suffix(output.suffix + ".zip")
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        entry = zipfile.ZipInfo("__main__.py", ZIP_TIME)
        entry.compress_type = zipfile.ZIP_STORED
        entry.external_attr = 0o100644 << 16
        archive.writestr(entry, main)
        for name, source in entries:
            add_file(archive, name, source, manifest)
    output.write_bytes(SHEBANG + payload.read_bytes())
    payload.unlink()
    output.chmod(0o755)
    return {
        "schema": "maude.reviewed-local-copy-validator-package/v1",
        "interpreter": str(INTERPRETER),
        "interpreter_sha256": digest(INTERPRETER.read_bytes()),
        "archive_sha256": digest(output.read_bytes()),
        "entries": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.manifest.exists():
        parser.error("output and manifest must be absent")
    record = build(args.output)
    args.manifest.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
