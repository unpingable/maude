#!/usr/bin/env python3
"""Create authority-empty AG/Docket enrollment inputs for the synthetic cache example."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

SCHEMA = "maude.synthetic-cache-governance-bootstrap/v1"
MAX_CONFIG = 32 * 1024
MAX_FILE = 128 * 1024 * 1024
PROGRAM_NAMES = (
    "ag",
    "docket",
    "executor_adapter",
    "nightshift_observation_resolver",
    "ag_standing_resolver",
    "openssl",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_bounded(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("input must be a regular non-symlink file")
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("input is empty or oversized")
    return raw


def sha256(path: Path, limit: int = MAX_FILE) -> str:
    return hashlib.sha256(read_bounded(path, limit)).hexdigest()


def digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate(config: dict) -> dict:
    expected = {"schema", "output_root", "programs", "catalog", "identities", "limits"}
    if not isinstance(config, dict) or set(config) != expected or config.get("schema") != SCHEMA:
        raise ValueError("configuration fields or schema differ")
    output = Path(config["output_root"])
    if not output.is_absolute() or output.exists():
        raise ValueError("output_root must be an absent absolute path")
    programs = config["programs"]
    if not isinstance(programs, dict) or set(programs) != set(PROGRAM_NAMES):
        raise ValueError("closed program enrollment differs")
    for name, item in programs.items():
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError(f"program {name} fields differ")
        path = Path(item["path"])
        if not path.is_absolute() or path.name == "" or not digest(item["sha256"]):
            raise ValueError(f"program {name} coordinate differs")
    catalog = config["catalog"]
    if not isinstance(catalog, dict) or set(catalog) != {"path", "sha256"}:
        raise ValueError("catalog fields differ")
    if not Path(catalog["path"]).is_absolute() or not digest(catalog["sha256"]):
        raise ValueError("catalog coordinate differs")
    identities = config["identities"]
    identity_fields = {"profile_label", "observation_resolver_id", "standing_resolver_id",
                       "issuer_principal", "issuer_key_id"}
    if not isinstance(identities, dict) or set(identities) != identity_fields:
        raise ValueError("identity fields differ")
    if any(not isinstance(value, str) or not value or len(value) > 128
           or any(character.isspace() for character in value)
           for value in identities.values()):
        raise ValueError("identity value differs")
    limits = config["limits"]
    if not isinstance(limits, dict) or set(limits) != {
        "observation_ttl_ms", "standing_ttl_ms", "docket_standing_ttl_ms"
    } or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
             for value in limits.values()):
        raise ValueError("limit fields differ")
    return config


def write_new(path: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def shell_wrapper(program: str, arguments: list[str]) -> bytes:
    import shlex
    command = " ".join(shlex.quote(item) for item in [program, *arguments])
    return f"#!/bin/sh\nexec {command}\n".encode()


def run_checked(argv: list[str]) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=8, check=False)
        if stdout.tell() > 1024 * 1024 or stderr.tell() > 1024 * 1024:
            raise ValueError("key-generation output exceeded bound")
        stdout.seek(0)
        stderr.seek(0)
        output, error = stdout.read(), stderr.read()
    if result.returncode:
        raise ValueError(f"key generation refused with exit {result.returncode}: "
                         + error.decode("utf-8", "replace")[:256])
    return output


def build(config: dict) -> dict:
    validate(config)
    paths = {}
    for name, item in config["programs"].items():
        path = Path(item["path"])
        if sha256(path) != item["sha256"] or not os.access(path, os.X_OK):
            raise ValueError(f"program {name} bytes or executable mode differ")
        paths[name] = path
    catalog = Path(config["catalog"]["path"])
    if sha256(catalog) != config["catalog"]["sha256"]:
        raise ValueError("catalog bytes differ")

    root = Path(config["output_root"])
    root.mkdir(mode=0o700)
    (root / "docket-state").mkdir(mode=0o700)
    mandates = root / "synthetic-mandates.json"
    write_new(mandates, canonical({"mandates": [],
                                   "schema": "ag.governed-loop.standing-mandate-store/v1"}), 0o600)
    identities, limits = config["identities"], config["limits"]
    observation = root / "observation-resolver.sh"
    write_new(observation, shell_wrapper(str(paths["nightshift_observation_resolver"]), [
        "--store", str(root / "nightshift.sqlite"),
        "--resolver-id", identities["observation_resolver_id"],
        "--default-ttl-ms", str(limits["observation_ttl_ms"]),
    ]), 0o700)
    standing = root / "standing-resolver.sh"
    write_new(standing, shell_wrapper(str(paths["ag_standing_resolver"]), [
        "--mandate-store", str(mandates),
        "--resolver-id", identities["standing_resolver_id"],
        "--answer-ttl-ms", str(limits["standing_ttl_ms"]),
    ]), 0o700)
    docket_standing = root / "docket-standing.py"
    docket_script = f'''#!/usr/bin/python3
import hashlib
import json
import sys

request = json.load(sys.stdin)
issuance = request["issuance"]
def digest(label):
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()
identifier = issuance["issuance"]
result = {{
    "schema": "docket.governed-loop.execution-standing-resolution/v1",
    "resolution": digest("resolution:" + identifier),
    "currentness": digest("currentness:" + identifier),
    "execution_standing": digest("execution-standing:" + identifier),
    "issuance": identifier,
    "campaign": issuance["key"]["campaign"],
    "occurrence": issuance["key"]["occurrence"],
    "subject": issuance["subject"],
    "scope": issuance["scope"],
    "status": "current",
    "resolved_at_unix_ms": request["now_unix_ms"],
    "expires_at_unix_ms": request["now_unix_ms"] + {limits["docket_standing_ttl_ms"]},
}}
sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
'''.encode()
    write_new(docket_standing, docket_script, 0o700)

    openssl_key = root / "openssl-issuer.pk8"
    run_checked([str(paths["openssl"]), "genpkey", "-algorithm", "Ed25519",
                 "-outform", "DER", "-out", str(openssl_key)])
    os.chmod(openssl_key, 0o600)
    spki = run_checked([str(paths["openssl"]), "pkey", "-inform", "DER", "-in", str(openssl_key),
                        "-pubout", "-outform", "DER"])
    spki_prefix = bytes.fromhex("302a300506032b6570032100")
    private_v1 = read_bounded(openssl_key, 128)
    private_prefix = bytes.fromhex("302e020100300506032b657004220420")
    if (len(spki) != len(spki_prefix) + 32 or not spki.startswith(spki_prefix)
            or len(private_v1) != len(private_prefix) + 32
            or not private_v1.startswith(private_prefix)):
        raise ValueError("OpenSSL returned an unexpected Ed25519 public-key encoding")
    public_bytes = spki[len(spki_prefix):]
    # ring's accepted PKCS#8 v2 form includes the public key alongside the
    # OpenSSL-generated private seed. The conversion changes encoding only.
    key = root / "issuer.pk8"
    private_v2 = (bytes.fromhex("3051020101300506032b657004220420")
                  + private_v1[len(private_prefix):] + bytes.fromhex("812100") + public_bytes)
    write_new(key, private_v2, 0o600)
    os.unlink(openssl_key)
    public = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode()
    trust = root / "docket-trust.json"
    write_new(trust, canonical({"issuers": [{
        "issuer_principal": identities["issuer_principal"],
        "key_id": identities["issuer_key_id"], "public_key": public,
    }]}), 0o600)
    enrollment = root / "runtime-profile-enrollment.json"
    value = {
        "schema": "ag.governed-loop.runtime-profile-enrollment/v1",
        "profile_label": identities["profile_label"],
        "observation_resolver": str(observation),
        "observation_resolver_id": identities["observation_resolver_id"],
        "standing_resolver": str(standing),
        "standing_resolver_id": identities["standing_resolver_id"],
        "max_standing_ttl_ms": limits["standing_ttl_ms"],
        "exact_work_catalog": str(catalog), "controlling_review": None,
        "docket": {
            "schema": "ag.governed-loop.docket-root-enrollment/v1",
            "docket_program": str(paths["docket"]),
            "state_directory": str(root / "docket-state"), "trust_config": str(trust),
            "standing_resolver": str(docket_standing),
            "executor_adapter": str(paths["executor_adapter"]),
            "issuer_principal": identities["issuer_principal"],
            "issuer_key_id": identities["issuer_key_id"], "issuer_key": str(key),
        },
        "human_verifier": None,
    }
    write_new(enrollment, canonical(value), 0o600)
    return {"enrollment": str(enrollment), "authority": "none", "standing": "synthetic_fixture",
            "mandate_store_initially_empty": True}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    config = json.loads(read_bounded(args.config, MAX_CONFIG))
    print(json.dumps(build(config), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
