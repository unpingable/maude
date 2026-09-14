#!/usr/bin/env python3
"""Attach one accepted external-observation reference to a sealed successor."""
import argparse, hashlib, json, os
from pathlib import Path
MAX=16*1024*1024
def load(path):
    if not path.is_absolute() or not path.is_file() or path.is_symlink(): raise ValueError("input must be an absolute regular non-symlink file")
    with path.open("rb") as stream: raw=stream.read(MAX+1)
    if not raw or len(raw)>MAX: raise ValueError("input is empty or oversized")
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError("input must be one JSON object")
    return value
def canonical(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def main(a):
    request=load(a.request); acquisition=load(a.acquisition); profile=load(a.profile)
    if request.get("schema")!="nightshift.canonical_cycle_request.v1" or not isinstance(request.get("proposal"),dict) or request.get("external_evidence") is not None or request.get("decision_external_evidence") is not None: raise ValueError("request must be a sealed proposal-bearing request without external evidence")
    if "continuation" not in request["proposal"].get("mode",{}): raise ValueError("external evidence requires a distinct continuation proposal")
    if acquisition.get("schema")!="maude.external-evidence-acquisition-export/v1": raise ValueError("unsupported acquisition export")
    events=acquisition.get("events"); handoff=acquisition.get("evidence",{}).get("handoff")
    if not isinstance(events,list) or not events or events[-1].get("kind")!="custody_accepted" or not isinstance(handoff,dict): raise ValueError("acquisition lacks accepted custody")
    observation=handoff.get("observation",{}); custody=events[-1].get("custody_id")
    for value in (observation.get("observation_id"),custody,profile.get("profile_id")):
        if not isinstance(value,str) or not value.startswith("sha256:") or len(value)!=71: raise ValueError("external reference identity is malformed")
    request["external_evidence"]={"schema":"nightshift.external_evidence_reference.v1","source_observation_id":observation["observation_id"],"source_custody_id":custody,"profile_id":profile["profile_id"]}
    pre=dict(request); pre.pop("request_id",None)
    request["request_id"]="sha256:"+hashlib.sha256(canonical(pre)).hexdigest()
    if a.output.exists(): raise ValueError("output must be fresh")
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"wb") as stream: stream.write(canonical(request)); stream.flush(); os.fsync(stream.fileno())
def parser():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--request",type=Path,required=True); p.add_argument("--acquisition",type=Path,required=True); p.add_argument("--profile",type=Path,required=True); p.add_argument("--output",type=Path,required=True); return p
if __name__=="__main__": main(parser().parse_args())
