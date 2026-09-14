#!/usr/bin/env python3
"""Materialize the owner NQ config from one settled Docket inspection."""

import argparse, json, os
from pathlib import Path

DIGEST_LEN = 71

def fail(message): raise ValueError(message)
def digest(value): return isinstance(value,str) and len(value)==DIGEST_LEN and value.startswith("sha256:")
def load(path):
    if not path.is_absolute() or not path.is_file() or path.is_symlink(): fail(f"invalid input path: {path}")
    with path.open("rb") as stream: raw=stream.read(16*1024*1024+1)
    if not raw or len(raw)>16*1024*1024: fail("input empty or oversized")
    value=json.loads(raw)
    if not isinstance(value,dict): fail("input must be one JSON object")
    return value
def q(value): return json.dumps(str(value), ensure_ascii=False)

def main(a):
    inspection=load(a.docket_inspection); record=inspection.get("record",{})
    if inspection.get("schema")!="docket.governed-loop.inspection/v1" or record.get("status")!="settled": fail("Docket inspection is not settled")
    issuance=record.get("issuance",{}); custody=record.get("custody",{}); settlement=record.get("settlement",{})
    if issuance.get("work_schema")!="maude.local-compose-workflow/v1" or settlement.get("outcome")!="success": fail("not a successful closed local-Compose settlement")
    plan=load(a.executor_plan)
    workspace=Path(plan.get("workspace", ""))
    if not workspace.is_absolute() or record.get("executor_plan") != issuance.get("work"): fail("executor plan identity does not match issuance work")
    attempt=custody.get("attempt"); marker=custody.get("executor_marker")
    fields=(attempt, marker, issuance.get("subject"), issuance.get("scope"), issuance.get("work"), record.get("executor_program_digest"), settlement.get("settlement"), settlement.get("receipt"))
    if not all(map(digest,fields)) or attempt!=settlement.get("attempt") or marker!=settlement.get("executor_marker"): fail("Docket custody/settlement identities disagree")
    executor_record=workspace/"evidence"/"attempts"/(attempt.removeprefix("sha256:")+".json")
    evidence=load(executor_record)
    if evidence.get("dispatch",{}).get("attempt")!=attempt or evidence.get("docket_outcome",{}).get("receipt")!=settlement.get("receipt"): fail("executor record does not bind Docket attempt/receipt")
    for path in (a.nq_database.parent,a.nq_socket.parent,a.admissions_dir,a.helper_runtime_dir,a.helper_working_directory):
        if not path.is_absolute() or not path.is_dir(): fail(f"required result directory unavailable: {path}")
    if not a.helper.is_absolute() or not a.helper.is_file() or a.helper.name!="nq-synthetic-cache-result-helper": fail("invalid result helper")
    if a.output.exists(): fail("result config output must be fresh")
    values={"attempt":attempt,"marker":marker,"subject":issuance["subject"],"scope":issuance["scope"],"work":issuance["work"],"executor_plan":record["executor_plan"],"executor_program_digest":record["executor_program_digest"],"docket_database":str(a.docket_database),"executor_record":str(executor_record)}
    inline=", ".join(f"{k} = {q(v)}" for k,v in values.items())+', work_schema = "maude.local-compose-workflow/v1"'
    text=f'''schema = "nq.config.v1"
database_path = {q(a.nq_database)}
socket_path = {q(a.nq_socket)}
admissions_dir = {q(a.admissions_dir)}
helper_runtime_dir = {q(a.helper_runtime_dir)}
[[watchers]]
instance_id = "synthetic-cache-result"
carrier = "stdio"
subject = {q(issuance["subject"])}
capability_ceiling = ["read_settled_cache_result"]
checkpoint_policy = "disabled"
[watchers.command]
executable = {q(a.helper)}
args = []
env = {{}}
execution_account = {q(a.execution_account)}
allow_same_identity_in_debug = {str(a.allow_same_identity_in_debug).lower()}
working_directory = {q(a.helper_working_directory)}
[watchers.profile]
id = "nq.synthetic_cache_executor_result"
version = 1
[watchers.scope]
kind = "synthetic_cache_executor_attempt"
value = {{ {inline} }}
[watchers.vantage]
kind = "retained_docket_state"
value = {{}}
[watchers.schedule]
interval_seconds = 300
jitter_seconds = 0
deadline_ms = 30000
retry_backoff_seconds = 10
max_retry_backoff_seconds = 300
[watchers.resources]
max_response_bytes = 1048576
max_stderr_bytes = 65536
max_observations = 1
max_address_space_bytes = 536870912
max_cpu_seconds = 60
max_processes = 32
max_open_files = 128
max_file_bytes = 67108864
'''
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream: stream.write(text); stream.flush(); os.fsync(stream.fileno())

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("docket_inspection","executor_plan","docket_database","nq_database","nq_socket","admissions_dir","helper_runtime_dir","helper","helper_working_directory","output"):
        p.add_argument("--"+n.replace("_","-"),type=Path,required=True)
    p.add_argument("--execution-account",required=True)
    p.add_argument("--allow-same-identity-in-debug",action="store_true")
    return p
if __name__=="__main__": main(parser().parse_args())
