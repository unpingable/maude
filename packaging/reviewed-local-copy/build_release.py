#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline, reproducible release build of the reviewed-local-copy validator and executor.

The shipped programs are the closed ``.pyz`` archives that alpha.6 executed in
``reviewed-local-copy/v1`` (B004): the read-only plan validator and the
exclusive-create executor. Their Maude modules come from the pinned public source
commit ``SOURCE_COMMIT`` and must match the digests B004 executed; PyYAML's pure
Python modules come from a hash-pinned ``python3-yaml`` package and must match
the same executed digests. Only ``__main__.py`` (identity dispatch for
``--version`` and ``--build-info``) and the shebang (``/usr/bin/python3 -IS``: a Debian 12 host runs
it with its own interpreter, isolated and without ``site``, so no dist-packages
path or ``.pth`` hook is loaded) differ from B004.

Host mode builds twice, each time from a separate clean clone, in the pinned
Debian 12 builder image with ``--network none``, compares the two outputs byte
for byte and writes ``SHA256SUMS`` and the build receipt. ``--inside`` is the
container step; it uses only the standard library.

This package does not contain, and does not depend on, Maude's classic RPC
client, the TUI, or agent_governor. Supervised agent sessions are not supported
in this release.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

COMPONENT = "maude-reviewed-local-copy"
VERSION = "0.1.0"
SOURCE_REPOSITORY = "https://github.com/unpingable/maude"
SOURCE_COMMIT = "d0f1375245d7fbaa05b0c6da9b8f60c6c5d388f4"
SOURCE_TREE = "2349f0bb6f7ae6b76c8625c02b2efb2a5736439d"
SOURCE_DATE_EPOCH = "1700000000"
IMAGE_ID = "sha256:fb7a58d0482a24e269ba85636ce46cb06aaaef3aea0e868154ed0ae7c18fa379"
IMAGE_REPO_DIGEST = "rust@sha256:365468470075493dc4583f47387001854321c5a8583ea9604b297e67f01c5a4f"
IMAGE_PYTHON = "/usr/bin/python3"
YAML_DEB = "python3-yaml_6.0.1-2build2_amd64.deb"
YAML_DEB_SHA256 = "315e59500af855f23ee4e95525b99009bd798c4d2658af8eb4b2d66a8a91ec23"
YAML_DEB_ORIGIN = "http://archive.ubuntu.com/ubuntu/pool/main/p/pyyaml/" + YAML_DEB
SHEBANG = b"#!/usr/bin/python3 -IS\n"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
TOP = f"{COMPONENT}-{VERSION}"
TARBALL = f"{TOP}.tar.gz"
RECEIPT = "build-receipt.v1.json"
PACKAGING_FILES = ("packaging/reviewed-local-copy/build_release.py", "packaging/reviewed-local-copy/README.md")

# Continuity with what B004 executed (precaller-026/packages/*.pyz, built on the
# qualification host by tools/build_reviewed_local_copy_validator.py at SOURCE_COMMIT).
B004_ARCHIVES = {
    "validator": "sha256:aa4435951242067364778baa7482f182f31743d6f64a07bead6cd7777f5723d8",
    "executor": "sha256:937fcb837295b51523c169b0de6a68013f234097b6a8286fa10cff0cdfa54045",
}

PLAN_CLOSURE = (
    "checks.py", "compiler.py", "document.py", "envelope.py", "local_compose.py",
    "ration_containment.py", "reviewed_local_copy.py", "store.py",
)
# Frozen from the executed B004 package manifests; the build refuses any other bytes.
EXPECTED_SOURCE = {
    "LICENSE": "6e6a946858b44931794212711561f184464ea94484ab23b561535f421afdf685",
    "NOTICE": "357375558b6d3b55e81986b861857bdb99c486d87e702ffe85b2cbe09d4dccb6",
    "src/maude/__init__.py": "e928c0c61da3315d6e913be11d1babea406461393037d383010acc5d9263c298",
    "src/maude/plan/checks.py": "7584aca95e559f385e22b2003560637ae5c53a028b3eb30c0b5f17a8f8fe8338",
    "src/maude/plan/compiler.py": "26d06fbef4e652b1fb8618aa694d78fbee3abd699a03879d514ef1abd017274c",
    "src/maude/plan/document.py": "36a4f3f5f188ffb22832deeb35eeee9eeca308e9e27c9392ecb15228fb620207",
    "src/maude/plan/envelope.py": "dafd57d672438ae229fa8df2a6d4a4d551ab0113c52ebefd134bca0777f420dd",
    "src/maude/plan/local_compose.py": "0a74f80c2ff0db2e114fa3b9bcb84a268fe81bd058e090839d389abc1b621311",
    "src/maude/plan/ration_containment.py": "1a6e298eb66a224cac93eb400cb9bc4b177bcfe20fc3f37402ef44ad12dd6b54",
    "src/maude/plan/reviewed_local_copy.py": "657790fbde299619c01e88968ba819f4544d2b2365d486cdf1fb9c8898f20a6e",
    "src/maude/plan/store.py": "9f73c90ba816c0e4f190933402786c8ceefc9699096b358929055a6fbcf7358b",
    "src/maude/plan/reviewed_local_copy_executor.py": "0da44ac6797e465005f4c614d092709ca4c61813c61b7ec8f7f22f14810bde0d",
}
EXPECTED_YAML = {
    "__init__.py": "6e1974e6a49e3bed59c654918c6aef9769bd9eb5dbd67f7e1906ad4cdd0caea7",
    "composer.py": "fcaa37d16afa783594794a5ab94193dcb720f503c19ce3d59539c8311189f453",
    "constructor.py": "90d8247da78b524c10618fd0e857f54f3d97570fe91b5c5513d024ef3faf88b0",
    "cyaml.py": "e99ac01bd7c062f7557b614aff0d21997a06ed962ca185306a91bc0a20bbd87d",
    "dumper.py": "3cb72d66563064ba7b5e679477046ebf89d8399d940670c8532f3e94a7cb17ea",
    "emitter.py": "8e086d694ede170837d5b1b407b45979aff6f40762f422a65eafd08e04290a44",
    "error.py": "021f73fada072546c4f63f8cf18a7181244ce4280b09cc15cc980b2d1176171a",
    "events.py": "e74fd392c810884e2ea7e94aa3f57e9c1cbeb402319083d0c58e6a0e1282787c",
    "loader.py": "5156becc8aa6905482218abf3e04869b835226db4763645fff3438fdbd5f1cdd",
    "nodes.py": "80f28d8fca4a09d87677882bde021820d9cf39a3b11a12405226211919cf13ce",
    "parser.py": "8a55a9e6fbe0a07146cef3990c8b45a068c3e83e369e1959ad9ca30306b4a09a",
    "reader.py": "d1d9b38ab3a20c6e17a38d519ee412ecaf6b918df18c78956ac7c330d4ea08dc",
    "representer.py": "22e58ff9c016f6c1ca1274b4802a926bcf78935060e1c813c5a0f021c6d143e6",
    "resolver.py": "f4bf9561f9b89961f1503d558385fbae30d12bfed565de9bf76c33abb63620a6",
    "scanner.py": "60433788b652690c17710460da5d91e0c753d3318fd85f5e1e42862a71f25906",
    "serializer.py": "0a1b85826854d35863e31808f0668abfabdf33606e8f06bd8bb7761401e3edc0",
    "tokens.py": "953408cd2570f0c83dc2fe39f7e4e388e41eeb05738aa69196a5f6ffcf6ba79e",
}
EXPECTED_YAML_NOTICE = "45f2bd1337c3a154cc47b3e9dac295708f8eb8c919c8b821451a1214ad4e6ad1"
# Import roots permitted in the closed archives besides the standard library.
PACKAGED_ROOTS = {"maude", "yaml"}
FORBIDDEN_FRAGMENTS = ("ag_shell_client", "agent_gov", "governor", "classic", "textual", "pydantic")

ROLES = {
    "validator": {
        "operations": ("validate",),
        "entry": "maude.plan.reviewed_local_copy",
        "refusal": "only the validate operation is available",
        "init": b"# Closed validator import package; exports intentionally omitted.\n",
        "closure": "maude.reviewed-local-copy-validator/imports-v1",
    },
    "executor": {
        "operations": ("plan-id", "execute", "reconcile"),
        "entry": "maude.plan.reviewed_local_copy_executor",
        "refusal": "only the plan-id, execute, and reconcile operations are available",
        "init": b"# Closed executor import package; exports intentionally omitted.\n",
        "closure": "maude.reviewed-local-copy-executor/imports-v1",
    },
}
LIMITATIONS = [
    "Supervised agent sessions are not supported in this release: no classic RPC client, "
    "no TUI and no agent_governor dependency is shipped or required.",
    "Only the reviewed-local-copy/v1 validator and executor are packaged; plan authoring, "
    "compilation and the plan CLI are not.",
    "The interpreter is the host's /usr/bin/python3 (3.11 or newer) with -IS (isolated, no site); it and its "
    "standard library remain deployment-trusted and must be enrolled by the installer.",
    "The executor performs exactly one exclusive create of result.txt under the plan's scratch "
    "root; it carries no authority of its own and relies on AG and Docket for admission.",
]


class Refusal(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------- inside
def main_source(role: str, build_info: str) -> bytes:
    spec = ROLES[role]
    operations = "{" + ", ".join(repr(op) for op in spec["operations"]) + "}"
    return (
        "import sys\n"
        f"BUILD_INFO = {build_info!r}\n"
        "if sys.argv[1:] == ['--build-info']:\n"
        "    sys.stdout.write(BUILD_INFO + '\\n')\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    import json\n"
        "    info = json.loads(BUILD_INFO)\n"
        "    print(f\"{info['component']} {info['version']} {info['source_commit']}\")\n"
        "    raise SystemExit(0)\n"
        f"from {spec['entry']} import main\n"
        f"if len(sys.argv) < 2 or sys.argv[1] not in {operations}:\n"
        f"    raise SystemExit({spec['refusal']!r})\n"
        "raise SystemExit(main(sys.argv[1:]))\n"
    ).encode("utf-8")


def zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    entry = zipfile.ZipInfo(name, ZIP_TIME)
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = 0o100644 << 16
    entry.create_system = 3
    archive.writestr(entry, data)


def import_audit(files: dict[str, bytes]) -> list[str]:
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    roots: set[str] = set()
    for name, data in files.items():
        if not name.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(data, filename=name)):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    outside = sorted(root for root in roots if root not in stdlib and root not in PACKAGED_ROOTS)
    if outside:
        raise Refusal(f"closed archive imports modules outside the closure: {outside}")
    for name, data in files.items():
        lowered = name.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS):
            raise Refusal(f"forbidden module in closure: {name}")
    return sorted(roots)


def build_role(role: str, staging: pathlib.Path, request: dict) -> tuple[bytes, dict]:
    spec = ROLES[role]
    source = staging / "source"
    modules = ["__init__.py"] + [f"plan/{name}" for name in PLAN_CLOSURE]
    if role == "executor":
        modules.append("plan/reviewed_local_copy_executor.py")
    payload: list[tuple[str, bytes]] = []
    for module in modules:
        payload.append((f"maude/{module}", (source / "src/maude" / module).read_bytes()))
    for name in sorted(EXPECTED_YAML):
        payload.append((f"yaml/{name}", (staging / "yaml" / name).read_bytes()))
    payload.extend([
        ("LICENSE", (source / "LICENSE").read_bytes()),
        ("NOTICE", (source / "NOTICE").read_bytes()),
        ("THIRD_PARTY_NOTICES/PyYAML-Debian-copyright", (staging / "yaml-copyright").read_bytes()),
    ])
    # Reorder to B004's layout: maude/__init__ precedes the plan modules.
    module_digests = {name: f"sha256:{sha256_bytes(data)}" for name, data in payload}
    audit = import_audit(dict(payload))
    build_info = canonical({
        "schema": "maude.reviewed-local-copy-build-info/v1",
        "component": f"{COMPONENT}-{role}",
        "version": VERSION,
        "role": role,
        "operations": list(spec["operations"]),
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": request["source_commit"],
        "source_tree": request["source_tree"],
        "packaging_commit": request["packaging_commit"],
        "closure": spec["closure"],
        "entries": module_digests,
        "interpreter": {"path": "/usr/bin/python3", "flags": "-IS", "isolated_mode": True, "site": False, "minimum": "3.11",
                        "trust": "deployment-trusted; enroll its sha256 at install"},
        "supervised_agent_sessions": "unsupported",
        "b004_executed_archive": B004_ARCHIVES[role],
    })
    main = main_source(role, build_info)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        zip_entry(archive, "__main__.py", main)
        zip_entry(archive, "maude/plan/__init__.py", spec["init"])
        for name, data in payload:
            zip_entry(archive, name, data)
    archive_bytes = SHEBANG + buffer.getvalue()
    manifest = {
        "schema": "maude.reviewed-local-copy-release-package/v1",
        "component": f"{COMPONENT}-{role}",
        "version": VERSION,
        "source_commit": request["source_commit"],
        "source_tree": request["source_tree"],
        "packaging_commit": request["packaging_commit"],
        "closure": spec["closure"],
        "archive_sha256": f"sha256:{sha256_bytes(archive_bytes)}",
        "shebang": SHEBANG.decode().strip(),
        "interpreter": "/usr/bin/python3",
        "interpreter_sha256": None,
        "python_isolated_mode": True,
        "python_site_disabled": True,
        "stdlib_trust": "the host interpreter and its standard library remain deployment-trusted",
        "import_roots": audit,
        "entries": {
            "__main__.py": f"sha256:{sha256_bytes(main)}",
            "maude/plan/__init__.py": f"sha256:{sha256_bytes(spec['init'])}",
            **module_digests,
        },
        "b004_executed_archive": B004_ARCHIVES[role],
        "differs_from_b004_only_in": ["shebang", "__main__.py"],
    }
    return archive_bytes, manifest


def deterministic_tar(members: list[tuple[str, bytes, int]], epoch: int) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        directories = sorted({str(pathlib.PurePosixPath(name).parent) for name, _, _ in members} - {"."})
        expanded: set[str] = set()
        for directory in directories:
            parts = pathlib.PurePosixPath(directory).parts
            for index in range(1, len(parts) + 1):
                expanded.add("/".join(parts[:index]))
        for directory in sorted(expanded):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.mtime = epoch
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info)
        for name, data, mode in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            info.mtime = epoch
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, compresslevel=9, mtime=0) as handle:
        handle.write(raw.getvalue())
    return compressed.getvalue()


def inside(staging: pathlib.Path, out: pathlib.Path) -> int:
    request = json.loads((staging / "build-request.json").read_text())
    epoch = int(os.environ["SOURCE_DATE_EPOCH"])
    outputs: dict[str, bytes] = {}
    members: list[tuple[str, bytes, int]] = []
    infos = {}
    for role in ROLES:
        archive, manifest = build_role(role, staging, request)
        manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        outputs[f"{COMPONENT}-{role}-{VERSION}.pyz"] = archive
        outputs[f"{COMPONENT}-{role}-{VERSION}.manifest.json"] = manifest_bytes
        members.append((f"{TOP}/{role}.pyz", archive, 0o755))
        members.append((f"{TOP}/{role}.manifest.json", manifest_bytes, 0o644))
        infos[role] = {"archive_sha256": manifest["archive_sha256"], "component": manifest["component"]}
    source = staging / "source"
    members += [
        (f"{TOP}/README.md", (staging / "packaging/README.md").read_bytes(), 0o644),
        (f"{TOP}/LICENSE", (source / "LICENSE").read_bytes(), 0o644),
        (f"{TOP}/NOTICE", (source / "NOTICE").read_bytes(), 0o644),
        (f"{TOP}/THIRD_PARTY_NOTICES/PyYAML-Debian-copyright", (staging / "yaml-copyright").read_bytes(), 0o644),
    ]
    build_info = {
        "schema": "maude.reviewed-local-copy-release/v1",
        "component": COMPONENT,
        "version": VERSION,
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": request["source_commit"],
        "source_tree": request["source_tree"],
        "packaging_commit": request["packaging_commit"],
        "programs": infos,
        "limitations": LIMITATIONS,
    }
    members.append((f"{TOP}/BUILD-INFO.json", (json.dumps(build_info, sort_keys=True, indent=2) + "\n").encode(), 0o644))
    member_sums = "".join(
        f"{sha256_bytes(data)}  {name.removeprefix(TOP + '/')}\n" for name, data, _ in sorted(members)
    ).encode()
    members.append((f"{TOP}/SHA256SUMS", member_sums, 0o644))
    outputs[TARBALL] = deterministic_tar(members, epoch)
    outputs["SHA256SUMS"] = "".join(
        f"{sha256_bytes(data)}  {name}\n" for name, data in sorted(outputs.items())
    ).encode()
    for name, data in outputs.items():
        target = out / name
        target.write_bytes(data)
        target.chmod(0o755 if name.endswith(".pyz") else 0o644)
    print(json.dumps({name: sha256_bytes(data) for name, data in sorted(outputs.items())}, indent=2))
    return 0


# ----------------------------------------------------------------------- host
def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, capture_output=True, **kwargs)
    if completed.returncode != 0:
        raise Refusal(f"command failed ({completed.returncode}): {command}\n{completed.stderr[-2000:]!r}")
    return completed


def git(repo: pathlib.Path, *arguments: str) -> str:
    return run(["git", "-C", str(repo), *arguments], text=True).stdout.strip()


def image_facts() -> dict:
    record = json.loads(run(["docker", "image", "inspect", IMAGE_ID]).stdout)[0]
    if record.get("Id") != IMAGE_ID or IMAGE_REPO_DIGEST not in record.get("RepoDigests", []):
        raise Refusal("builder image identity differs from the pin")
    return {"image_id": IMAGE_ID, "repository_digest": IMAGE_REPO_DIGEST, "os": "Debian GNU/Linux 12 (bookworm)",
            "python": IMAGE_PYTHON, "network": "none", "pull": "never", "read_only_rootfs": True}


def stage(repo: pathlib.Path, yaml_deb: pathlib.Path, staging: pathlib.Path) -> dict:
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise Refusal(f"packaging clone is not clean: {repo}")
    if git(repo, "rev-parse", f"{SOURCE_COMMIT}^{{commit}}") != SOURCE_COMMIT:
        raise Refusal("source commit is absent")
    if git(repo, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}") != SOURCE_TREE:
        raise Refusal("source tree differs from the pin")
    reachable = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", SOURCE_COMMIT, "origin/main"])
    if reachable.returncode != 0:
        raise Refusal("source commit is not reachable from origin/main")
    source = staging / "source"
    source.mkdir(parents=True)
    raw = run(["git", "-C", str(repo), "archive", "--format=tar", SOURCE_COMMIT, "--", *EXPECTED_SOURCE]).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            if member.isfile():
                target = source / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    for name, expected in EXPECTED_SOURCE.items():
        if sha256_file(source / name) != expected:
            raise Refusal(f"source file differs from the executed B004 bytes: {name}")
    if sha256_file(yaml_deb) != YAML_DEB_SHA256:
        raise Refusal("python3-yaml package digest differs from the pin")
    fsys = run(["dpkg-deb", "--fsys-tarfile", str(yaml_deb)]).stdout
    (staging / "yaml").mkdir()
    with tarfile.open(fileobj=io.BytesIO(fsys)) as archive:
        for member in archive.getmembers():
            name = member.name.removeprefix("./")
            if name.startswith("usr/lib/python3/dist-packages/yaml/") and name.endswith(".py"):
                (staging / "yaml" / pathlib.PurePosixPath(name).name).write_bytes(archive.extractfile(member).read())
            elif name == "usr/share/doc/python3-yaml/copyright":
                (staging / "yaml-copyright").write_bytes(archive.extractfile(member).read())
    found = {path.name: sha256_file(path) for path in (staging / "yaml").iterdir()}
    if found != EXPECTED_YAML or sha256_file(staging / "yaml-copyright") != EXPECTED_YAML_NOTICE:
        raise Refusal("python3-yaml modules differ from the executed B004 bytes")
    (staging / "packaging").mkdir()
    for path in PACKAGING_FILES:
        data = run(["git", "-C", str(repo), "show", f"HEAD:{path}"]).stdout
        (staging / "packaging" / pathlib.PurePosixPath(path).name).write_bytes(data)
    request = {
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "packaging_commit": git(repo, "rev-parse", "HEAD"),
        "packaging_branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
    }
    (staging / "build-request.json").write_text(canonical(request) + "\n")
    for path in staging.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    staging.chmod(0o755)
    return request


def docker_command(staging: pathlib.Path, out: pathlib.Path) -> list[str]:
    return [
        "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--user", f"{os.getuid()}:{os.getgid()}",
        "--env", f"SOURCE_DATE_EPOCH={SOURCE_DATE_EPOCH}", "--env", "LC_ALL=C.UTF-8", "--env", "TZ=UTC",
        "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONHASHSEED=0",
        "--volume", f"{staging}:/in:ro", "--volume", f"{out}:/out:rw",
        IMAGE_ID, IMAGE_PYTHON, "-I", "/in/packaging/build_release.py", "--inside", "/in", "/out",
    ]


def one_build(label: str, repo: pathlib.Path, yaml_deb: pathlib.Path, scratch: pathlib.Path) -> dict:
    staging = scratch / f"staging-{label}"
    out = scratch / f"build-{label}"
    out.mkdir(parents=True)
    request = stage(repo, yaml_deb, staging)
    command = docker_command(staging, out)
    completed = subprocess.run(command, capture_output=True, text=True)
    (scratch / f"build-{label}.log").write_text(
        f"$ {' '.join(command)}\nexit {completed.returncode}\n--- stdout\n{completed.stdout}\n--- stderr\n{completed.stderr}\n"
    )
    if completed.returncode != 0:
        raise Refusal(f"build {label} failed: {completed.stderr[-2000:]}")
    return {"label": label, "repo": str(repo), "request": request, "out": out,
            "digests": {path.name: sha256_file(path) for path in sorted(out.iterdir())},
            "normalized_docker_argv": [part.replace(str(staging), "<staging>").replace(str(out), "<out>")
                                       for part in command]}


def b004_continuity(repo: pathlib.Path, scratch: pathlib.Path) -> dict:
    """Rebuild the executed B004 archives with the original builder at SOURCE_COMMIT (qualification host only)."""
    tree = scratch / "b004-source"
    run(["git", "-C", str(repo), "worktree", "add", "--detach", str(tree), SOURCE_COMMIT])
    try:
        results = {}
        for role in ROLES:
            output = scratch / f"b004-{role}.pyz"
            run(["/usr/bin/python3.12", "-I", str(tree / "tools/build_reviewed_local_copy_validator.py"), "--role", role,
                 "--source-revision", SOURCE_COMMIT, "--output", str(output), "--manifest", str(scratch / f"b004-{role}.json")])
            actual = f"sha256:{sha256_file(output)}"
            results[role] = {"rebuilt": actual, "executed": B004_ARCHIVES[role], "byte_equal": actual == B004_ARCHIVES[role]}
        return {"host_interpreter": "/usr/bin/python3.12", "host_interpreter_sha256": sha256_file(pathlib.Path("/usr/bin/python3.12")),
                "builder": f"{SOURCE_COMMIT}:tools/build_reviewed_local_copy_validator.py", "roles": results}
    finally:
        run(["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)])


def host(args: argparse.Namespace) -> int:
    out: pathlib.Path = args.out
    if out.exists():
        raise Refusal(f"output directory already exists: {out}")
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="maude-rlc-build-", dir=args.scratch))
    builder = image_facts()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    a = one_build("a", args.repo.resolve(), args.yaml_deb, scratch)
    b = one_build("b", args.repro_repo.resolve(), args.yaml_deb, scratch)
    if a["request"] != b["request"]:
        raise Refusal("the two clones are not at the same packaging commit")
    equal = a["digests"] == b["digests"] and all(
        (a["out"] / name).read_bytes() == (b["out"] / name).read_bytes() for name in a["digests"])
    if not equal:
        raise Refusal(f"builds differ: {a['digests']} vs {b['digests']}")
    continuity = b004_continuity(args.repo.resolve(), scratch) if args.b004_continuity else None
    out.mkdir(parents=True)
    for name in a["digests"]:
        shutil.copy2(a["out"] / name, out / name)
    if run(["sha256sum", "--check", "--strict", "SHA256SUMS"], cwd=out).returncode != 0:
        raise Refusal("SHA256SUMS does not verify")
    request = a["request"]
    receipt = {
        "schema": "maude.reviewed-local-copy-build-receipt/v1",
        "component": COMPONENT,
        "version": VERSION,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "commit": SOURCE_COMMIT,
            "tree": SOURCE_TREE,
            "reachable_from": "origin/main",
            "files": {name: f"sha256:{digest}" for name, digest in EXPECTED_SOURCE.items()},
            "pin_resolution": (
                "The executed B004 validator.pyz and executor.pyz state source_revision d0f1375 and rebuild "
                "byte-equal from it. c1fce17 (site source-pins.json) changes reviewed_local_copy_executor.py, so "
                "the executor cannot come from it; the validator closure is identical at d0f1375, c1fce17 and "
                "26ae43d."
            ),
        },
        "packaging": {"branch": request["packaging_branch"], "commit": request["packaging_commit"],
                      "files": list(PACKAGING_FILES)},
        "inputs": {
            "python3_yaml_deb": {"name": YAML_DEB, "sha256": YAML_DEB_SHA256, "origin": YAML_DEB_ORIGIN,
                                 "modules": {name: f"sha256:{digest}" for name, digest in EXPECTED_YAML.items()},
                                 "copyright": f"sha256:{EXPECTED_YAML_NOTICE}"},
        },
        "builder": {**builder, "identity": f"{os.environ.get('USER', 'unknown')}@{os.uname().nodename}",
                    "driver": "packaging/reviewed-local-copy/build_release.py (host mode)",
                    "environment": {"SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH, "LC_ALL": "C.UTF-8", "TZ": "UTC",
                                    "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"},
                    "normalized_docker_argv": a["normalized_docker_argv"]},
        "artifacts": {name: f"sha256:{digest}" for name, digest in a["digests"].items()},
        "reproduction": {
            "builds": [{"label": item["label"], "clone": item["repo"], "digests": item["digests"]} for item in (a, b)],
            "byte_equal": equal,
            "method": "two separate clean clones at the same packaging commit, each staged and built in its own "
                      "--network none container run; every output compared byte for byte",
        },
        "b004_continuity": continuity,
        "started_at": started,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "limitations": LIMITATIONS,
    }
    (out / RECEIPT).write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    shutil.copy2(scratch / "build-a.log", out / "build-a.log")
    shutil.copy2(scratch / "build-b.log", out / "build-b.log")
    print(json.dumps({"out": str(out), "artifacts": receipt["artifacts"], "byte_equal": equal,
                      "b004_continuity": continuity}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inside", nargs=2, metavar=("STAGING", "OUT"), type=pathlib.Path)
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2])
    parser.add_argument("--repro-repo", type=pathlib.Path)
    parser.add_argument("--yaml-deb", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--scratch", type=pathlib.Path, default=pathlib.Path(tempfile.gettempdir()))
    parser.add_argument("--b004-continuity", action="store_true",
                        help="also rebuild the executed B004 archives with the original builder (needs /usr/bin/python3.12 and the host PyYAML)")
    args = parser.parse_args()
    try:
        if args.inside:
            return inside(*args.inside)
        if not (args.repro_repo and args.yaml_deb and args.out):
            parser.error("host mode needs --repro-repo, --yaml-deb and --out")
        return host(args)
    except Refusal as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
