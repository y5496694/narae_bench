"""Resume unfinished v2.1 cases with a Windows closed-stdin transport fix only."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import evaluate_native as original
OUT=ROOT/"evaluation"
REC=OUT/"recovery/narae2-pipe"
FOLDER=OUT/"runs/narae2"
PATCHED=Path(r"D:\Codex\workspaces\narae_bench\mock\evaluate.py")
dump,load,sha=original.dump,original.load,original.sha

def worker():
    spec=importlib.util.spec_from_file_location("pipe_fixed_bridge",REC/"runner.py")
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    bridge.PACKAGE=OUT/"benchmark"
    bridge.run(SimpleNamespace(base_url=original.native.BASE+"/v1",model=original.identity("narae2")["alias"],
        out=REC/"fresh-cases",format="schema",max_tokens=2048,request_timeout=600,
        case=load(REC/"plan.json")["restarted_cases"]))

def main():
    REC.mkdir(parents=True,exist_ok=False)
    for name in ["logs","serving","verification","tmp"]:(REC/name).mkdir()
    partial=load(FOLDER/"results.json")
    interrupted="NP-E-WXS-READ-06"
    before_entries=[json.loads(x) for x in (FOLDER/"model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    remaining=[r["case_id"] for r in partial["results"] if r["status"]=="NOT_RUN" or r["case_id"]==interrupted]
    preserved=[r["case_id"] for r in partial["results"] if r["status"] in ["PASS","FAIL"] and r["case_id"]!=interrupted]
    assert len(preserved)==15 and len(remaining)==21 and remaining[0]==interrupted
    shutil.copytree(FOLDER,REC/"interrupted-run")
    for path in [ROOT/"logs/evaluate-native.log",OUT/"logs/narae2-benchmark.log"]:
        shutil.copyfile(path,REC/path.name)
    shutil.copyfile(PATCHED,REC/"runner.py")
    record=original.identity("narae2")
    plan={"cause":"Windows EINVAL while writing/closing stdin after the CLI's real 360-second deadline",
          "preserved_cases":preserved,"restarted_cases":remaining,"partial_case_excluded":interrupted,
          "frozen_benchmark_source_unchanged":True,"weights_and_generation_settings_unchanged":True,
          "transport_change":"Treat EINVAL as a closed pipe only after the child exited successfully; consume its existing closed event. Live I/O failures still invalidate the run.",
          "recovery_source_sha256":sha(__file__),"patched_runner_sha256":sha(REC/"runner.py"),
          "original_runner_sha256":sha(OUT/"benchmark/mock/evaluate.py")}
    dump(REC/"plan.json",plan)
    original.native.ROOT=REC
    server=original.native.Server(record)
    try:
        assert load(REC/"serving/narae2.json")==load(OUT/"serving/narae2.json")
        with (REC/"logs/evaluation.log").open("wb") as log:
            child=subprocess.Popen([sys.executable,"-X","utf8",str(Path(__file__)),"--worker"],stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            while child.poll() is None:
                progress=(REC/"logs/evaluation.log").read_text(encoding="utf-8")
                dump(OUT/"status.json",{"stage":"benchmark-recovery","model":"narae2","completed":15+progress.count('"case_completed":'),"preserved":15})
                time.sleep(2)
            if child.returncode:raise RuntimeError("Recovery worker failed; inspect recovery logs")
        fresh=load(REC/"fresh-cases/results.json")
        for index,row in enumerate(partial["results"]):
            if row["case_id"] in remaining:
                new=next(r for r in fresh["results"] if r["case_id"]==row["case_id"])
                assert new["status"] in ["PASS","FAIL"]
                partial["results"][index]=new
        evidence_root=REC/"fresh-cases/evidence"
        for path in evidence_root.rglob("*"):
            if path.is_file():
                target=FOLDER/"evidence"/path.relative_to(evidence_root)
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        after_entries=[json.loads(x) for x in (REC/"fresh-cases/model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
        entries=[e for e in before_entries if e["case_id"] in preserved]+after_entries
        assert len({e["case_id"] for e in entries})==36
        (FOLDER/"model-transcript.jsonl").write_text("".join(json.dumps(e,ensure_ascii=False)+"\n" for e in entries),encoding="utf-8")
        profile=load(OUT/"frozen-profile.json")
        plan.update(complete=True,serving_manifest_identical=True,recovery_controller_profile=fresh["model_controller_profile"])
        partial.update(model_identity=record,v2_comparison_profile=profile,recovery=plan)
        dump(FOLDER/"results.json",partial)
        (FOLDER/"controller-error.json").replace(REC/"excluded-controller-error.json")
        subprocess.run([sys.executable,"-X","utf8",str(OUT/"benchmark/bench.py"),"grade",str(FOLDER/"results.json"),
                        "--out",str(FOLDER/"summary.json")],check=True)
        summary=load(FOLDER/"summary.json")
        assert summary["all_cases_completed"] and summary["not_run"]==0
        summary.update(model_identity=record,v2_comparison_profile=profile,recovery=plan)
        dump(FOLDER/"summary.json",summary);dump(REC/"verification.json",plan)
        dump(OUT/"status.json",{"stage":"complete","recovery":str(REC/"verification.json")})
        print(json.dumps({"model":"narae2","score":summary["strict_e2e_score"],"recovery_completed":True}),flush=True)
    finally:server.close()

if __name__=="__main__":
    worker() if "--worker" in sys.argv else main()
