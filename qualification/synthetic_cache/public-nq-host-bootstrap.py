#!/usr/bin/env python3
import argparse, hashlib, json, os
from pathlib import Path

def q(v): return json.dumps(str(v))
def prepare(a):
    if not a.output.is_absolute() or a.output.exists() or not a.state_root.is_absolute() or a.state_root.exists(): raise ValueError("fresh absolute output and state root required")
    if not a.helper.is_absolute() or a.helper.is_symlink() or not a.helper.is_file(): raise ValueError("absolute regular helper required")
    if not a.working_directory.is_absolute() or not a.working_directory.is_dir(): raise ValueError("absolute working directory required")
    if not all((a.instance,a.execution_account,a.subject,a.scope_id)) or a.instance=="host-local": raise ValueError("explicit non-default watcher binding required")
    a.state_root.mkdir(mode=0o700,parents=True); admissions=a.state_root/"admissions"; runtime=a.state_root/"helpers"; admissions.mkdir(mode=0o700); runtime.mkdir(mode=0o700)
    rows=[
      'schema = "nq.config.v1"',f"database_path = {q(a.state_root/'nq.db')}",f"socket_path = {q(a.state_root/'nqd.sock')}",f"admissions_dir = {q(admissions)}",f"helper_runtime_dir = {q(runtime)}",'[[watchers]]',f"instance_id = {q(a.instance)}",'carrier = "stdio"',f"subject = {q(a.subject)}",'capability_ceiling = ["read_procfs", "read_system_info"]','checkpoint_policy = "disabled"','[watchers.command]',f"executable = {q(a.helper)}",'args = []','env = {}',f"execution_account = {q(a.execution_account)}",f"allow_same_identity_in_debug = {str(a.allow_same_identity_in_debug).lower()}",f"working_directory = {q(a.working_directory)}",'[watchers.profile]','id = "nq.host"','version = 1','[watchers.scope]','kind = "host"',f"value = {{ id = {q(a.scope_id)} }}",'[watchers.vantage]','kind = "local"','value = {}','[watchers.schedule]','interval_seconds = 300','jitter_seconds = 15','deadline_ms = 30000','retry_backoff_seconds = 10','max_retry_backoff_seconds = 300','[watchers.resources]','max_response_bytes = 1048576','max_stderr_bytes = 65536','max_observations = 1','max_address_space_bytes = 536870912','max_cpu_seconds = 60','max_processes = 32','max_open_files = 128','max_file_bytes = 67108864','']
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as f: f.write("\n".join(rows)); f.flush(); os.fsync(f.fileno())
    return {"nq_config":str(a.output),"helper_sha256":"sha256:"+hashlib.sha256(a.helper.read_bytes()).hexdigest(),"launch_admitted":False}
def parser():
    p=argparse.ArgumentParser()
    for n in ("output","state_root","helper","working_directory"): p.add_argument("--"+n.replace("_","-"),type=Path,required=True)
    for n in ("instance","execution_account","subject","scope_id"): p.add_argument("--"+n.replace("_","-"),required=True)
    p.add_argument("--allow-same-identity-in-debug",action="store_true"); return p
if __name__=="__main__": print(json.dumps(prepare(parser().parse_args()),sort_keys=True))
