#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Clean Debian 12 VM gate for the Maude reviewed-local-copy release artifacts.

This harness follows the style of NQ's release-closure harness. It boots one
disposable Debian 12 guest from the verified read-only base image:
- a qcow2 overlay and a cloud-init seed;
- user networking with restrict=on and one SSH hostfwd on 127.0.0.1;
- qemu -sandbox on.

It installs the programs from the release artifact only, using the guest's own
/usr/bin/python3. It then checks identity and closure and runs the validator and
executor on synthetic fixtures. Each case ends as PASS, FAIL or NOT_EXERCISED.

The guest receives:
- the release artifacts and the build receipt;
- the synthetic fixtures (make_fixtures.py);
- the guest closure probe.

No source tree, share or host PATH is exposed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import socket
import subprocess
import sys
import time
import traceback
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
HARNESS_FILES = ("run_vm_gate.py", "make_fixtures.py", "guest/closure_probe.py")
IMAGE = pathlib.Path(
    "/data/git/.campaign-artifacts/constellation-operator-beta-composed-m2-run-002/input/"
    "debian-12-genericcloud-amd64-20260903-2590.qcow2"
)
USER = "maudeacceptor"
HOME = f"/home/{USER}"
FX = f"{HOME}/fx"
PREFIX = "/usr/lib/maude-reviewed-local-copy"
VALIDATOR = f"{PREFIX}/validator.pyz"
EXECUTOR = f"{PREFIX}/executor.pyz"
VERSION = "0.1.0"
TOP = f"maude-reviewed-local-copy-{VERSION}"
TARBALL = f"{TOP}.tar.gz"
RECEIPT = "build-receipt.v1.json"
LOOSE = {
    "validator": f"maude-reviewed-local-copy-validator-{VERSION}.pyz",
    "executor": f"maude-reviewed-local-copy-executor-{VERSION}.pyz",
}
PROBE = f"{HOME}/bin/closure_probe.py"

CASES = [
    ("I-01", "guest: Debian 12, Debian python3 is the only interpreter used"),
    ("I-02", "artifact: sha256sum --check SHA256SUMS in the guest"),
    ("I-03", "install: from the tarball only; member sums verify; installed bytes equal the receipt"),
    ("I-04", "identity: --version and --build-info carry component, version and the 40-hex source commit"),
    ("I-05", "environment: no source tree, no Maude or classic library importable, no egress"),
    ("I-06", "docs: packaged README states supervised agent sessions are unsupported"),
    ("C-01", "closure: validator run loads only archive and stdlib modules, nothing from agent_gov/classic"),
    ("C-02", "closure: executor run loads only archive and stdlib modules, nothing from agent_gov/classic"),
    ("V-01", "validator: valid synthetic binding passes"),
    ("V-02", "validator: outer field tampered (stale binding_id) refused"),
    ("V-03", "validator: inner artifact substituted with recomputed outer identity refused"),
    ("V-04", "validator: non-canonical binding bytes refused"),
    ("V-05", "validator: binding against a different store refused"),
    ("V-06", "validator: operations other than validate refused"),
    ("V-07", "validator: PYTHONPATH/sitecustomize injection ignored"),
    ("E-01", "executor: plan-id equals the binding's exact work identity"),
    ("E-02", "executor: execute creates result.txt once with the exact reviewed bytes"),
    ("E-03", "executor: replay of the same attempt returns the recorded outcome and does not write"),
    ("E-04", "executor: a second attempt for the same plan is refused; target untouched"),
    ("E-05", "executor: an existing target is refused and not overwritten"),
    ("E-06", "executor: a dispatch that differs from the sealed plan is refused; nothing created"),
    ("E-07", "executor: a tampered sealed plan is refused"),
    ("E-08", "executor: reconcile never copies (absent evidence refused; success/indeterminate read back)"),
    ("E-09", "executor: operations other than plan-id/execute/reconcile refused"),
    ("P-01", "packaging: a corrupted tarball fails its checksum"),
]


class Refusal(Exception):
    pass


class CaseFail(Exception):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha(path: pathlib.Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, check: bool = True, timeout: float = 600) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    if check and completed.returncode != 0:
        raise Refusal(f"command failed ({completed.returncode}): {shlex.join(command)}\n"
                      f"{completed.stderr.decode(errors='replace')[-2000:]}")
    return completed


def text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFail(message)


class Gate:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out: pathlib.Path = args.output
        self.state: pathlib.Path = args.state_dir
        self.results = {cid: {"id": cid, "title": title, "outcome": "NOT_EXERCISED", "reason": "not reached"}
                        for cid, title in CASES}
        self.current: str | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.command: list[str] = []
        self.key = self.state / "id_ed25519"
        self.facts: dict[str, Any] = {}

    # ------------------------------------------------------------ plumbing
    def log(self, message: str) -> None:
        line = f"[{utc_now()}] {message}"
        print(line, flush=True)
        with (self.out / "host.log").open("a") as handle:
            handle.write(line + "\n")

    def ssh_base(self) -> list[str]:
        return ["ssh", "-i", str(self.key), "-p", str(self.args.ssh_port), "-o", "IdentitiesOnly=yes",
                "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={self.state / 'known_hosts'}",
                "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR", f"{USER}@127.0.0.1"]

    def scp(self, sources: list[pathlib.Path], destination: str) -> None:
        run(["scp", "-q", "-i", str(self.key), "-P", str(self.args.ssh_port), "-o", "IdentitiesOnly=yes",
             "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={self.state / 'known_hosts'}",
             "-o", "LogLevel=ERROR", *[str(s) for s in sources], f"{USER}@127.0.0.1:{destination}"])

    def sh(self, command: str, *, stdin_file: str | None = None, timeout: float = 300,
           check: bool = False) -> subprocess.CompletedProcess[bytes]:
        full = command if stdin_file is None else f"{command} < {shlex.quote(stdin_file)}"
        started = time.monotonic()
        try:
            completed = run(self.ssh_base() + [full], check=False, timeout=timeout)
        except subprocess.TimeoutExpired:
            completed = subprocess.CompletedProcess(full, 124, b"", b"[timeout]")
        if self.current:
            with (self.out / "cases" / f"{self.current}.log").open("a") as handle:
                handle.write(f"\n$ {full}\n# exit {completed.returncode} in {time.monotonic() - started:.1f}s\n"
                             + (f"--- stdout\n{text(completed.stdout)}\n" if completed.stdout else "")
                             + (f"--- stderr\n{text(completed.stderr)}\n" if completed.stderr else ""))
        if check and completed.returncode != 0:
            raise CaseFail(f"exit {completed.returncode}: {full}: {text(completed.stderr)[-800:]}")
        return completed

    def case(self, cid: str, function, *args: Any) -> None:
        self.current = cid
        (self.out / "cases" / f"{cid}.log").write_text(f"# {cid}: {dict(CASES)[cid]}\n")
        try:
            observed = function(*args) or {}
            self.results[cid] = {"id": cid, "title": dict(CASES)[cid], "outcome": "PASS", "observed": observed}
        except CaseFail as error:
            self.results[cid] = {"id": cid, "title": dict(CASES)[cid], "outcome": "FAIL", "error": str(error)}
        except Exception as error:  # noqa: BLE001
            self.results[cid] = {"id": cid, "title": dict(CASES)[cid], "outcome": "FAIL",
                                 "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-2000:]}
        self.log(f"{cid} {self.results[cid]['outcome']}")
        self.current = None
        self.write()

    def write(self) -> None:
        summary = {o: sum(1 for r in self.results.values() if r["outcome"] == o) for o in ("PASS", "FAIL", "NOT_EXERCISED")}
        (self.out / "GATE-RESULT.json").write_text(json.dumps({
            "schema": "maude.reviewed-local-copy-vm-gate/v1", "facts": self.facts, "summary": summary,
            "qemu_command": self.command, "cases": list(self.results.values())}, indent=2, sort_keys=True) + "\n")

    # ------------------------------------------------------------ preflight
    def harness_identity(self) -> dict[str, Any]:
        def git(*arguments: str) -> str | None:
            done = subprocess.run(["git", "-C", str(HERE), *arguments], capture_output=True, text=True)
            return done.stdout.strip() if done.returncode == 0 else None
        return {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "dirty_paths": (git("status", "--porcelain", "--", ".") or "").splitlines(),
                "files": {name: sha(HERE / name) for name in HARNESS_FILES}}

    def preflight(self) -> None:
        for tool in ("qemu-img", "qemu-system-x86_64", "xorriso", "ssh", "scp", "ssh-keygen"):
            if shutil.which(tool) is None:
                raise Refusal(f"required tool absent: {tool}")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise Refusal("/dev/kvm is not accessible")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", self.args.ssh_port))
            except OSError as error:
                raise Refusal(f"port {self.args.ssh_port} is busy") from error
        if self.out.exists():
            raise Refusal(f"output exists: {self.out}")
        if self.state.exists():
            raise Refusal(f"state directory exists: {self.state}")
        (self.out / "cases").mkdir(parents=True)
        self.state.mkdir(parents=True, mode=0o700)
        candidate: pathlib.Path = self.args.candidate_dir
        checked = subprocess.run(["sha256sum", "--check", "--strict", "SHA256SUMS"], cwd=candidate, capture_output=True)
        if checked.returncode != 0:
            raise Refusal("candidate SHA256SUMS does not verify on the host")
        receipt = json.loads((candidate / RECEIPT).read_text())
        if not receipt.get("reproduction", {}).get("byte_equal"):
            raise Refusal("receipt does not record a byte-equal reproduction")
        fixtures: pathlib.Path = self.args.fixtures_dir
        expected = None
        for line in (IMAGE.parent / "SHA512SUMS").read_text().splitlines():
            digest, _, name = line.strip().partition("  ")
            if name == IMAGE.name:
                expected = digest
        actual = sha(IMAGE, "sha512")
        if expected != actual:
            raise Refusal("base image SHA-512 differs from SHA512SUMS")
        if os.access(IMAGE, os.W_OK):
            raise Refusal("base image must not be writable")
        self.receipt = receipt
        self.fixtures = json.loads((fixtures / "FIXTURES.json").read_text())
        self.facts = {
            "started": utc_now(),
            "harness": self.harness_identity(),
            "candidate": {"directory": str(candidate), "receipt_sha256": sha(candidate / RECEIPT),
                          "artifacts": receipt["artifacts"], "source_commit": receipt["source"]["commit"],
                          "packaging_commit": receipt["packaging"]["commit"]},
            "fixtures": {"directory": str(fixtures), "FIXTURES.json": sha(fixtures / "FIXTURES.json"),
                         "files": self.fixtures["files"]},
            "image": {"path": str(IMAGE), "sha512": actual},
            "ssh_port": self.args.ssh_port,
        }
        self.write()

    # ------------------------------------------------------------ guest
    def boot(self) -> None:
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "maude-vm-gate", "-f", str(self.key)])
        public = self.key.with_suffix(".pub").read_text().strip()
        (self.state / "meta-data").write_text("instance-id: maude-vm-gate\nlocal-hostname: maude-gate\n")
        (self.state / "user-data").write_text(f"""#cloud-config
disable_root: true
hostname: maude-gate
package_update: false
package_upgrade: false
ssh_pwauth: false
users:
  - name: {USER}
    groups: [sudo]
    lock_passwd: true
    shell: /bin/bash
    sudo: ["ALL=(ALL) NOPASSWD:ALL"]
    ssh_authorized_keys:
      - "{public}"
""")
        run(["xorriso", "-as", "mkisofs", "-quiet", "-output", str(self.state / "seed.iso"), "-volid", "cidata",
             "-joliet", "-rock", str(self.state / "user-data"), str(self.state / "meta-data")])
        run(["qemu-img", "create", "-q", "-f", "qcow2", "-b", str(IMAGE), "-F", "qcow2", str(self.state / "overlay.qcow2")])
        self.command = [
            "qemu-system-x86_64", "-name", "maude-vm-gate,process=maude-vm-gate", "-no-user-config", "-nodefaults",
            "-accel", "kvm", "-machine", "q35", "-cpu", "host", "-smp", "2", "-m", "2048",
            "-display", "none", "-monitor", "none", "-serial", f"file:{self.state / 'serial.log'}",
            "-drive", f"if=virtio,file={self.state / 'overlay.qcow2'},format=qcow2,cache=none,aio=threads",
            "-drive", f"if=virtio,file={self.state / 'seed.iso'},format=raw,readonly=on",
            "-netdev", f"user,id=mgmt,restrict=on,hostfwd=tcp:127.0.0.1:{self.args.ssh_port}-:22",
            "-device", "virtio-net-pci,netdev=mgmt,mac=52:54:00:9c:04:01",
            "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny",
        ]
        self.process = subprocess.Popen(self.command, stdout=(self.state / "qemu.stdout.log").open("wb"),
                                        stderr=(self.state / "qemu.stderr.log").open("wb"), start_new_session=True)
        self.log(f"started guest pid {self.process.pid} on 127.0.0.1:{self.args.ssh_port}")
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise Refusal("guest exited: " + (self.state / "qemu.stderr.log").read_text()[-800:])
            try:
                if run(self.ssh_base() + ["true"], check=False, timeout=30).returncode == 0:
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(3)
        else:
            raise Refusal("guest SSH not reachable")
        run(self.ssh_base() + ["cloud-init status --wait >/dev/null; cloud-init status"], check=False, timeout=900)
        run(self.ssh_base() + [f"mkdir -p {HOME}/bin {HOME}/candidate {HOME}/fx-src"])
        candidate: pathlib.Path = self.args.candidate_dir
        self.scp([candidate / name for name in (*self.receipt["artifacts"], RECEIPT)], f"{HOME}/candidate/")
        self.scp(sorted(p for p in self.args.fixtures_dir.iterdir() if p.is_file()), f"{HOME}/fx-src/")
        self.scp([HERE / "guest" / "closure_probe.py"], f"{HOME}/bin/")
        self.log("guest ready")

    def destroy(self) -> None:
        if self.process is not None and self.process.poll() is None:
            try:
                run(self.ssh_base() + ["sudo systemctl poweroff"], check=False, timeout=20)
            except subprocess.TimeoutExpired:
                pass
            deadline = time.monotonic() + 60
            while self.process.poll() is None and time.monotonic() < deadline:
                time.sleep(1)
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=30)
        for name in ("serial.log", "qemu.stdout.log", "qemu.stderr.log"):
            if (self.state / name).exists():
                shutil.copy2(self.state / name, self.out / f"guest-{name}")
        shutil.rmtree(self.state, ignore_errors=True)
        self.log("guest destroyed")

    # ------------------------------------------------------------ helpers
    def fresh_fixture_tree(self) -> None:
        self.sh(f"rm -rf {FX} && mkdir -p {FX}/state {FX}/scratch-main {FX}/scratch-existing {FX}/scratch-fresh"
                f" && cp {HOME}/fx-src/* {FX}/ && chmod 0700 {FX}/state", check=True)

    def json_out(self, completed: subprocess.CompletedProcess[bytes]) -> Any:
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise CaseFail(f"stdout is not JSON: {text(completed.stdout)[:400]!r}") from error

    def file_state(self, path: str) -> str:
        return text(self.sh(f"stat -c '%i %s %Y.%y %a' {path} 2>/dev/null && sha256sum {path} | cut -d' ' -f1 || echo absent").stdout).strip()

    # ------------------------------------------------------------ cases
    def i01(self) -> dict:
        osr = text(self.sh('. /etc/os-release; printf "%s:%s" "$ID" "$VERSION_ID"', check=True).stdout)
        expect(osr == "debian:12", f"not Debian 12: {osr}")
        version = text(self.sh("/usr/bin/python3 -V", check=True).stdout).strip()
        real = text(self.sh("readlink -f /usr/bin/python3", check=True).stdout).strip()
        owner = text(self.sh(f"dpkg -S {real}", check=True).stdout).strip()
        digest = text(self.sh(f"sha256sum {real}", check=True).stdout).split()[0]
        expect(version.startswith("Python 3.11"), f"unexpected interpreter {version}")
        expect(owner.startswith("python3.11-minimal"), f"interpreter not from Debian: {owner}")
        others = text(self.sh("ls /usr/local/bin/python* 2>/dev/null; true").stdout).strip()
        expect(not others, f"non-Debian interpreters present: {others}")
        self.facts["guest_interpreter"] = {"path": real, "version": version, "package": owner, "sha256": digest}
        return {"os": osr, "python": version, "interpreter": real, "package": owner, "sha256": digest}

    def i02(self) -> dict:
        done = self.sh(f"cd {HOME}/candidate && sha256sum --check --strict SHA256SUMS", check=True)
        return {"check": text(done.stdout).strip().splitlines()}

    def i03(self) -> dict:
        self.sh(f"rm -rf {HOME}/unpack && mkdir {HOME}/unpack && tar -xzf {HOME}/candidate/{TARBALL} -C {HOME}/unpack", check=True)
        members = self.sh(f"cd {HOME}/unpack/{TOP} && sha256sum --check --strict SHA256SUMS", check=True)
        self.sh(f"sudo install -d -m 0755 {PREFIX} && sudo install -m 0755 -o root -g root "
                f"{HOME}/unpack/{TOP}/validator.pyz {HOME}/unpack/{TOP}/executor.pyz {PREFIX}/", check=True)
        listing = text(self.sh(f"stat -c '%a %U:%G %n' {PREFIX} {VALIDATOR} {EXECUTOR}", check=True).stdout)
        installed = {role: text(self.sh(f"sha256sum {path}", check=True).stdout).split()[0]
                     for role, path in (("validator", VALIDATOR), ("executor", EXECUTOR))}
        for role, digest in installed.items():
            expect(f"sha256:{digest}" == self.receipt["artifacts"][LOOSE[role]],
                   f"installed {role} differs from the receipt: {digest}")
        head = text(self.sh(f"head -c 32 {VALIDATOR} | head -1", check=True).stdout).strip()
        expect(head == "#!/usr/bin/python3 -IS", f"unexpected shebang {head!r}")
        self.facts["installed"] = installed
        return {"member_check": text(members.stdout).strip().splitlines(), "modes": listing.strip().splitlines(),
                "installed_sha256": installed, "shebang": head}

    def i04(self) -> dict:
        commit = self.receipt["source"]["commit"]
        expect(len(commit) == 40, "receipt commit is not 40-hex")
        observed = {}
        for role, path in (("validator", VALIDATOR), ("executor", EXECUTOR)):
            version = text(self.sh(f"{path} --version", check=True).stdout).strip()
            expect(version == f"maude-reviewed-local-copy-{role} {VERSION} {commit}", f"{role} --version: {version!r}")
            info = self.json_out(self.sh(f"{path} --build-info", check=True))
            expect(info["source_commit"] == commit and info["version"] == VERSION
                   and info["component"] == f"maude-reviewed-local-copy-{role}", f"{role} build-info identity")
            expect(info["packaging_commit"] == self.receipt["packaging"]["commit"], f"{role} packaging commit")
            expect(info["supervised_agent_sessions"] == "unsupported", f"{role} sessions field")
            manifest = json.loads(text(self.sh(f"cat {HOME}/unpack/{TOP}/{role}.manifest.json", check=True).stdout))
            for name, digest in info["entries"].items():
                expect(manifest["entries"].get(name) == digest, f"{role} entry {name} differs from manifest")
            observed[role] = {"version": version, "source_commit": info["source_commit"],
                              "source_tree": info["source_tree"], "packaging_commit": info["packaging_commit"]}
        return observed

    def i05(self) -> dict:
        checks = {
            "no /data": "test ! -e /data",
            "no maude source": "! find / -xdev \\( -path /proc -o -path /sys \\) -prune -o \\( -name 'build_reviewed_local_copy_validator.py' -o -name 'reviewed_local_copy.py' \\) -print 2>/dev/null | grep -q .",
            "no agent_gov or ag_shell_client on disk": "! find / -xdev \\( -path /proc -o -path /sys \\) -prune -o \\( -iname '*agent_gov*' -o -iname '*ag_shell_client*' -o -iname 'agent_governor*' \\) -print 2>/dev/null | grep -q .",
            "maude not importable": "! /usr/bin/python3 -c 'import maude' 2>/dev/null",
            "ag_shell_client not importable": "! /usr/bin/python3 -c 'import ag_shell_client' 2>/dev/null",
            "no egress": "! timeout 8 /usr/bin/python3 -c \"import socket; socket.create_connection(('1.1.1.1', 443), 5)\" 2>/dev/null",
        }
        observed = {}
        for label, command in checks.items():
            done = self.sh(command, timeout=120)
            observed[label] = done.returncode == 0
            expect(done.returncode == 0, f"environment check failed: {label}")
        yaml = text(self.sh("dpkg -s python3-yaml 2>/dev/null | grep -E '^(Status|Version)'; true").stdout).strip()
        observed["guest python3-yaml (cloud-init dependency; not used by the archives, see C-01)"] = yaml
        return observed

    def i06(self) -> dict:
        readme = text(self.sh(f"cat {HOME}/unpack/{TOP}/README.md", check=True).stdout)
        expect("Supervised agent sessions are not supported in this release" in readme, "README limitation absent")
        info = json.loads(text(self.sh(f"cat {HOME}/unpack/{TOP}/BUILD-INFO.json", check=True).stdout))
        expect(any("Supervised agent sessions are not supported" in item for item in info["limitations"]),
               "BUILD-INFO limitation absent")
        return {"readme_line": next(l for l in readme.splitlines() if "Supervised agent sessions" in l)}

    def probe(self, report: str, program: str, arguments: str, stdin_file: str | None = None) -> dict:
        self.sh(f"cd {FX} && /usr/bin/python3 -I -S {PROBE} {report} {program} {arguments}", stdin_file=stdin_file)
        data = json.loads(text(self.sh(f"cat {report}", check=True).stdout))
        expect(data["isolated"] and data["no_site"], "probe not isolated/no-site")
        expect(not data["modules"]["outside"], f"modules outside the closure: {data['modules']['outside']}")
        expect(not data["startup_outside"], f"startup modules outside stdlib: {data['startup_outside']}")
        expect(not data["forbidden_loaded"], f"forbidden modules loaded: {data['forbidden_loaded']}")
        return {"exit": data["exit"], "archive_modules": data["modules"]["archive"],
                "stdlib_module_count": len(data["modules"]["stdlib"]), "outside": data["modules"]["outside"],
                "forbidden_loaded": data["forbidden_loaded"]}

    def c01(self) -> dict:
        self.fresh_fixture_tree()
        result = self.probe(f"{HOME}/probe-validator.json", VALIDATOR,
                            "validate --config validator-config.json --binding binding.json")
        expect(result["exit"] == 0, "probed validation did not pass")
        expect("maude.plan.reviewed_local_copy" in result["archive_modules"], "validator module not from archive")
        expect("yaml" in result["archive_modules"], "yaml not from archive")
        return result

    def c02(self) -> dict:
        result = self.probe(f"{HOME}/probe-executor.json", EXECUTOR, "reconcile executor-config-fresh.json",
                            stdin_file=f"{FX}/dispatch-fresh.json")
        expect("maude.plan.reviewed_local_copy_executor" in result["archive_modules"], "executor module not from archive")
        expect(self.sh(f"ls -A {FX}/scratch-fresh").stdout == b"", "reconcile probe created files")
        return result

    def validate(self, binding: str, config: str = "validator-config.json") -> subprocess.CompletedProcess[bytes]:
        return self.sh(f"cd {FX} && {VALIDATOR} validate --config {config} --binding {binding}")

    def refused(self, done: subprocess.CompletedProcess[bytes], reason: str) -> dict:
        expect(done.returncode == 2, f"expected exit 2, got {done.returncode}")
        body = json.loads(done.stderr)
        expect(body == {"reason": reason, "result": "refused"}, f"unexpected refusal {body}")
        expect(done.stdout == b"", "refusal wrote to stdout")
        return {"exit": done.returncode, "stderr": body}

    def v01(self) -> dict:
        done = self.validate("binding.json")
        expect(done.returncode == 0, f"exit {done.returncode}: {text(done.stderr)}")
        body = self.json_out(done)
        expect(body["result"] == "passed" and body["binding_id"] == self.fixtures["binding_id"], f"unexpected {body}")
        return {"exit": 0, "stdout": body}

    def v02(self) -> dict:
        return self.refused(self.validate("binding-outer-tampered.json"), "binding identity does not bind its outer fields")

    def v03(self) -> dict:
        return self.refused(self.validate("binding-inner-tampered.json"), "executor plan differs from compiler inputs")

    def v04(self) -> dict:
        return self.refused(self.validate("binding-noncanonical.json"), "binding must use canonical JSON bytes")

    def v05(self) -> dict:
        return self.refused(self.validate("binding.json", "validator-config-other-store.json"),
                            "locked revision is not the selected current revision")

    def v06(self) -> dict:
        observed = {}
        for arguments in ("compile --store plans.sqlite --draft-id x --inputs a --output b", "", "--help"):
            done = self.sh(f"cd {FX} && {VALIDATOR} {arguments}")
            expect(done.returncode != 0 and b"only the validate operation is available" in done.stderr,
                   f"{arguments!r} not refused: {done.returncode}")
            observed[arguments or "<none>"] = {"exit": done.returncode, "stderr": text(done.stderr).strip()}
        return observed

    def v07(self) -> dict:
        self.sh(f"mkdir -p {HOME}/inject && printf 'import pathlib; pathlib.Path(\"{HOME}/inject/ran\").write_text(\"x\")\\n' > {HOME}/inject/sitecustomize.py"
                f" && cp {HOME}/inject/sitecustomize.py {HOME}/inject/usercustomize.py", check=True)
        done = self.sh(f"cd {FX} && PYTHONPATH={HOME}/inject PYTHONSTARTUP={HOME}/inject/sitecustomize.py {VALIDATOR} validate --config validator-config.json --binding binding.json")
        expect(done.returncode == 0, "validation failed under injection")
        marker = self.sh(f"test -e {HOME}/inject/ran")
        expect(marker.returncode != 0, "injected sitecustomize ran")
        return {"exit": done.returncode, "marker_created": False}

    def e01(self) -> dict:
        done = self.sh(f"cd {FX} && {EXECUTOR} plan-id executor-config-main.json", check=True)
        work = text(done.stdout).strip()
        expect(work == self.fixtures["works"]["main"], f"plan-id {work} differs")
        return {"plan_id": work}

    def e02(self) -> dict:
        before = self.sh(f"ls -A {FX}/scratch-main").stdout
        expect(before == b"", "scratch not empty before execute")
        done = self.sh(f"cd {FX} && {EXECUTOR} execute executor-config-main.json", stdin_file=f"{FX}/dispatch-main-a.json")
        expect(done.returncode == 0, f"execute exit {done.returncode}: {text(done.stderr)}")
        outcome = self.json_out(done)
        expect(outcome["outcome"] == "success", f"outcome {outcome}")
        digest = text(self.sh(f"sha256sum {FX}/scratch-main/result.txt", check=True).stdout).split()[0]
        expect(digest == self.fixtures["reviewed_text_sha256"], "result.txt bytes differ from reviewed text")
        mode = text(self.sh(f"stat -c %a {FX}/scratch-main/result.txt", check=True).stdout).strip()
        expect(mode == "600", f"result mode {mode}")
        listing = text(self.sh(f"ls -A {FX}/scratch-main", check=True).stdout).split()
        expect(listing == ["result.txt"], f"scratch contains {listing}")
        record = json.loads(text(self.sh(f"cat {FX}/state/*/record.json", check=True).stdout))
        expect(record["state"] == "success", f"record {record['state']}")
        self.result_state = self.file_state(f"{FX}/scratch-main/result.txt")
        self.success_outcome = outcome
        return {"outcome": outcome, "result_sha256": digest, "mode": mode, "record_state": record["state"],
                "result_state": self.result_state}

    def e03(self) -> dict:
        done = self.sh(f"cd {FX} && {EXECUTOR} execute executor-config-main.json", stdin_file=f"{FX}/dispatch-main-a.json")
        expect(done.returncode == 0, f"replay exit {done.returncode}")
        expect(self.json_out(done) == self.success_outcome, "replay outcome differs from the recorded success")
        after = self.file_state(f"{FX}/scratch-main/result.txt")
        expect(after == self.result_state, f"result.txt changed on replay: {after}")
        return {"outcome": self.json_out(done), "result_state_unchanged": after}

    def e04(self) -> dict:
        done = self.sh(f"cd {FX} && {EXECUTOR} execute executor-config-main.json", stdin_file=f"{FX}/dispatch-main-b.json")
        expect(done.returncode == 2 and text(done.stderr).strip() == "result.txt already exists; effect not retried",
               f"second attempt not refused: {done.returncode} {text(done.stderr)}")
        after = self.file_state(f"{FX}/scratch-main/result.txt")
        expect(after == self.result_state, "result.txt changed by the second attempt")
        records = text(self.sh(f"for f in {FX}/state/*/record.json; do cat $f; echo; done", check=True).stdout)
        states = [json.loads(line)["state"] for line in records.splitlines() if line.strip()]
        expect(sorted(states) == ["indeterminate", "success"], f"attempt records {states}")
        return {"exit": 2, "stderr": text(done.stderr).strip(), "result_state_unchanged": after, "record_states": sorted(states)}

    def e05(self) -> dict:
        self.sh(f"printf 'pre-existing target\\n' > {FX}/scratch-existing/result.txt", check=True)
        before = self.file_state(f"{FX}/scratch-existing/result.txt")
        done = self.sh(f"cd {FX} && {EXECUTOR} execute executor-config-existing.json", stdin_file=f"{FX}/dispatch-existing.json")
        expect(done.returncode == 2 and text(done.stderr).strip() == "result.txt already exists; effect not retried",
               f"existing target not refused: {done.returncode} {text(done.stderr)}")
        after = self.file_state(f"{FX}/scratch-existing/result.txt")
        expect(after == before, "existing target was modified")
        content = text(self.sh(f"cat {FX}/scratch-existing/result.txt").stdout)
        return {"exit": 2, "stderr": text(done.stderr).strip(), "content_after": content, "unchanged": True}

    def e06(self) -> dict:
        attempts_before = text(self.sh(f"ls {FX}/state").stdout).split()
        done = self.sh(f"cd {FX} && {EXECUTOR} execute executor-config-fresh.json", stdin_file=f"{FX}/dispatch-mismatch.json")
        expect(done.returncode == 2 and text(done.stderr).strip() == "dispatch differs from sealed executor plan",
               f"mismatch not refused: {done.returncode} {text(done.stderr)}")
        expect(self.sh(f"ls -A {FX}/scratch-fresh").stdout == b"", "mismatched dispatch created a file")
        expect(text(self.sh(f"ls {FX}/state").stdout).split() == attempts_before, "mismatched dispatch created attempt state")
        return {"exit": 2, "stderr": text(done.stderr).strip(), "scratch_fresh": "empty", "attempts_unchanged": True}

    def e07(self) -> dict:
        observed = {}
        for operation in ("plan-id", "execute"):
            done = self.sh(f"cd {FX} && {EXECUTOR} {operation} executor-config-tampered.json",
                           stdin_file=f"{FX}/dispatch-main-a.json")
            expect(done.returncode == 2 and text(done.stderr).strip() == "sealed text identity mismatch",
                   f"tampered plan not refused on {operation}: {done.returncode} {text(done.stderr)}")
            observed[operation] = {"exit": 2, "stderr": text(done.stderr).strip()}
        expect(self.file_state(f"{FX}/scratch-main/result.txt") == self.result_state, "result.txt changed")
        return observed

    def e08(self) -> dict:
        observed = {}
        done = self.sh(f"cd {FX} && {EXECUTOR} reconcile executor-config-fresh.json", stdin_file=f"{FX}/dispatch-fresh.json")
        expect(done.returncode == 2 and text(done.stderr).strip() == "attempt evidence is absent", "absent evidence not refused")
        expect(self.sh(f"ls -A {FX}/scratch-fresh").stdout == b"", "reconcile created a file")
        observed["no_evidence"] = {"exit": 2, "stderr": text(done.stderr).strip(), "scratch_fresh": "empty"}
        done = self.sh(f"cd {FX} && {EXECUTOR} reconcile executor-config-main.json", stdin_file=f"{FX}/dispatch-main-a.json")
        expect(done.returncode == 0 and self.json_out(done) == self.success_outcome, "reconcile of success differs")
        observed["success"] = self.json_out(done)
        done = self.sh(f"cd {FX} && {EXECUTOR} reconcile executor-config-main.json", stdin_file=f"{FX}/dispatch-main-b.json")
        expect(done.returncode == 0 and self.json_out(done)["outcome"] == "indeterminate", "reconcile of refused attempt")
        observed["second_attempt"] = self.json_out(done)
        # A reconcile on a removed target must not restore it.
        self.sh(f"mv {FX}/scratch-main/result.txt {FX}/moved-result.txt", check=True)
        done = self.sh(f"cd {FX} && {EXECUTOR} reconcile executor-config-main.json", stdin_file=f"{FX}/dispatch-main-a.json")
        expect(done.returncode == 0, "reconcile after target removal failed")
        expect(self.sh(f"ls -A {FX}/scratch-main").stdout == b"", "reconcile recreated result.txt")
        observed["after_target_removed"] = {"outcome": self.json_out(done)["outcome"], "scratch_main": "empty"}
        self.sh(f"mv {FX}/moved-result.txt {FX}/scratch-main/result.txt", check=True)
        return observed

    def e09(self) -> dict:
        observed = {}
        for arguments in ("copy executor-config-main.json", "", "--help", "validate --config x --binding y"):
            done = self.sh(f"cd {FX} && {EXECUTOR} {arguments}")
            expect(done.returncode != 0 and b"only the plan-id, execute, and reconcile operations are available" in done.stderr,
                   f"{arguments!r} not refused")
            observed[arguments or "<none>"] = {"exit": done.returncode}
        return observed

    def p01(self) -> dict:
        done = self.sh(f"cp -r {HOME}/candidate {HOME}/corrupt && cd {HOME}/corrupt && "
                       f"printf 'X' | dd of={TARBALL} bs=1 seek=4096 conv=notrunc status=none && "
                       f"sha256sum --check --strict SHA256SUMS")
        expect(done.returncode != 0 and f"{TARBALL}: FAILED".encode() in done.stdout, "corruption not detected")
        return {"exit": done.returncode, "stdout": text(done.stdout).strip().splitlines()}

    # ------------------------------------------------------------ main
    def main(self) -> int:
        try:
            self.preflight()
        except Refusal as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        status = 0
        try:
            self.boot()
            for cid, fn in (("I-01", self.i01), ("I-02", self.i02), ("I-03", self.i03), ("I-04", self.i04),
                            ("I-05", self.i05), ("I-06", self.i06)):
                self.case(cid, fn)
            if self.results["I-03"]["outcome"] != "PASS":
                raise Refusal("install failed; later cases not exercised")
            for cid, fn in (("C-01", self.c01), ("C-02", self.c02), ("V-01", self.v01), ("V-02", self.v02),
                            ("V-03", self.v03), ("V-04", self.v04), ("V-05", self.v05), ("V-06", self.v06),
                            ("V-07", self.v07), ("E-01", self.e01), ("E-02", self.e02)):
                self.case(cid, fn)
            if self.results["E-02"]["outcome"] == "PASS":
                for cid, fn in (("E-03", self.e03), ("E-04", self.e04), ("E-05", self.e05), ("E-06", self.e06),
                                ("E-07", self.e07), ("E-08", self.e08)):
                    self.case(cid, fn)
            self.case("E-09", self.e09)
            self.case("P-01", self.p01)
        except Exception as error:  # noqa: BLE001
            self.log(f"aborted: {error}")
            for entry in self.results.values():
                if entry["outcome"] == "NOT_EXERCISED":
                    entry["reason"] = f"aborted: {error}"[:400]
            status = 1
        finally:
            self.destroy()
            self.facts["finished"] = utc_now()
            self.write()
        summary = {o: sum(1 for r in self.results.values() if r["outcome"] == o) for o in ("PASS", "FAIL", "NOT_EXERCISED")}
        self.log(f"done: {summary}")
        return 0 if status == 0 and summary["FAIL"] == 0 and summary["NOT_EXERCISED"] == 0 else 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--candidate-dir", type=pathlib.Path, required=True)
    p.add_argument("--fixtures-dir", type=pathlib.Path, required=True)
    p.add_argument("--output", type=pathlib.Path, required=True)
    p.add_argument("--state-dir", type=pathlib.Path, required=True)
    p.add_argument("--ssh-port", type=int, default=23401)
    return p


if __name__ == "__main__":
    sys.exit(Gate(parser().parse_args()).main())
