"""Audit the two new model runs against unchanged old benchmark prompts and calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"evaluation"
OLD=Path(r"D:\Codex\benchmarks\narae-compare-v21-20261019")
sys.path.insert(0,str(ROOT/"scripts"))
from tool_corpus import World, dumps

def load(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

for filename in [ROOT/"frozen-training-profile.json",OUT/"plan.json"]:
    for name,digest in load(filename)["source_sha256"].items(): assert sha(ROOT/name)==digest,name
for name,digest in load(ROOT/"training-kernel-amendment.json")["source_sha256"].items(): assert sha(ROOT/name)==digest,name
for name,digest in load(OUT/"snapshot.json")["files_sha256"].items(): assert sha(OUT/"benchmark"/name)==digest,name
spec=importlib.util.spec_from_file_location("bridge",OUT/"benchmark/mock/evaluate.py")
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
verified=[]
recoveries={}
for tag in ["narae1","narae2"]:
    folder=OUT/"runs"/tag
    result,summary=load(folder/"results.json"),load(folder/"summary.json")
    assert summary["all_cases_completed"] and summary["not_run"]==0 and not (folder/"controller-error.json").exists()
    assert sum(r["status"]=="BLOCKED" for r in result["results"])==9
    serving=load(OUT/"serving"/(tag+".json"))
    before_serving=load(OLD/"serving"/(tag+".json"))
    training=load(ROOT/"outputs"/serving["identity"]["alias"]/"training-report.json")
    assert training["initial_adapter_file_sha256"]==before_serving["identity"]["adapter"]["source_sha256"]
    assert training["adapter_file_sha256"]==serving["identity"]["adapter"]["source_sha256"]
    assert training["optimizer_steps"]==104 and len(training["adapter_parameter_l2_changes"])==24
    assert all(v>0 for v in training["adapter_parameter_l2_changes"].values())
    if tag=="narae2":
        assert training["attention_backend"]=="sdpa"
        assert 0<=training["attention_backend_equivalence_absolute_error"]<=2e-4
    assert serving["identity"]["file"]==before_serving["identity"]["file"]
    assert serving["identity"]["sha256"]==before_serving["identity"]["sha256"]
    assert serving["executable_sha256"]==before_serving["executable_sha256"]
    if "recovery" in result:
        recovery=result["recovery"]
        rec=OUT/"recovery/narae2-pipe"
        assert tag=="narae2" and recovery==load(rec/"verification.json")==summary["recovery"]
        assert recovery["complete"] and recovery["serving_manifest_identical"]
        assert recovery["recovery_source_sha256"]==sha(ROOT/"scripts/recover_narae2.py")
        assert recovery["patched_runner_sha256"]==sha(rec/"runner.py")
        assert recovery["original_runner_sha256"]==sha(OUT/"benchmark/mock/evaluate.py")
        assert load(rec/"serving/narae2.json")==serving
        assert load(rec/"excluded-controller-error.json")["score_valid"] is False
        preserved,restarted=recovery["preserved_cases"],recovery["restarted_cases"]
        assert len(preserved)==15 and len(restarted)==21 and not set(preserved)&set(restarted)
        assert recovery["partial_case_excluded"]=="NP-E-WXS-READ-06" and restarted[0]=="NP-E-WXS-READ-06"
        interrupted=load(rec/"interrupted-run/results.json")
        fresh=load(rec/"fresh-cases/results.json")
        assert fresh["model_controller_profile"]["script_sha256"]==recovery["patched_runner_sha256"]
        for case_id in [*preserved,*restarted]:
            source=rec/("interrupted-run" if case_id in preserved else "fresh-cases")
            source_result=interrupted if case_id in preserved else fresh
            assert next(r for r in result["results"] if r["case_id"]==case_id)==next(r for r in source_result["results"] if r["case_id"]==case_id)
            assert sha(folder/"evidence"/(case_id+".json"))==sha(source/"evidence"/(case_id+".json"))
        final_entries=[json.loads(x) for x in (folder/"model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
        for selected,source in [(preserved,rec/"interrupted-run"),(restarted,rec/"fresh-cases")]:
            original_entries=[json.loads(x) for x in (source/"model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
            assert [e for e in final_entries if e["case_id"] in selected]==[e for e in original_entries if e["case_id"] in selected]
        recoveries[tag]={"preserved":15,"restarted":21,"partial_case_excluded":recovery["partial_case_excluded"],
            "same_weights_prompts_grading_and_budgets":True,"transport_fix_only":True}
    before=[json.loads(x) for x in (OLD/"api-runs"/tag/"model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    entries=[json.loads(x) for x in (folder/"model-transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    active=[r for r in result["results"] if r["status"] in ["PASS","FAIL"]]
    assert len(active)==36
    for row in active:
        es=[e for e in entries if e["case_id"]==row["case_id"]]
        first=es[0]
        old=next(e for e in before if e["case_id"]==row["case_id"] and e["turn"]==1)
        assert first["request"]["messages"]==old["request"]["messages"],row["case_id"]
        assert first["request"]["response_format"]==old["request"]["response_format"]
        evidence=load(folder/"evidence"/(row["case_id"]+".json"))
        index=0
        for e in es:
            q,r=e["request"],e["response"]
            assert q["model"]==r["model"]==result["model"]==serving["identity"]["alias"]
            assert q["messages"][0]=={"role":"system","content":bridge.SYSTEM}
            assert q["max_tokens"]==2048 and q["temperature"]==0 and q["seed"]==719 and q["stream"] is False
            assert 0<=r["usage"]["completion_tokens"]<=2048 and r["usage"]["prompt_tokens"]<=8192
            if e["observation"]["event"]=="closed":
                assert row["failure_layer"]=="TIMEOUT";continue
            try: call=bridge.parse_reply(r["choices"][0]["message"].get("content"))
            except (ValueError,TypeError): continue
            actual=evidence["trace"][index]
            assert call=={"tool":actual["tool"],"args":actual["args"]}
            assert {k:v for k,v in e["observation"]["result"].items() if k!="environment"}==actual["result"]
            index+=1
        assert index==len(evidence["trace"]) and evidence["live_service_actions"]==0 and 1<=len(es)<=8
        verified.append({"tag":tag,"case_id":row["case_id"],"passed":row["status"]=="PASS"})
    private=load(OUT/"private"/tag/"results.json")
    assert private["complete"] and private["planned"]==24
    assert len(private["results"])==24
    private_entries=[json.loads(x) for x in (OUT/"private"/tag/"transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    private_cases=[json.loads(x) for x in (ROOT/"data/trajectories/test.jsonl").read_text(encoding="utf-8").splitlines()]
    for case in private_cases:
        w=World(case["scenario"])
        messages=[{"role":"system","content":bridge.SYSTEM},{"role":"user","content":dumps(case["scenario"]["task"])}]
        if case["scenario"]["bad_prefix"]:
            tool,args=case["scenario"]["bad_prefix"]
            observed=w.call(tool,args)
            messages += [{"role":"assistant","content":dumps({"tool":tool,"args":args})},
                         {"role":"user","content":dumps({"event":"observation","result":{"environment":"mock",**observed}})}]
        es=[e for e in private_entries if e["case_id"]==case["id"]]
        assert 1<=len(es)<=8
        for e in es:
            assert e["request"]["messages"]==messages
            assert e["request"]["model"]==e["response"]["model"]==serving["identity"]["alias"]
            assert e["request"]["max_tokens"]==2048 and e["request"]["seed"]==719 and e["request"]["temperature"]==0
            assert e["response"]["usage"]["completion_tokens"]<=2048 and e["response"]["usage"]["prompt_tokens"]<=8192
            text=e["response"]["choices"][0]["message"].get("content")
            try:
                call=bridge.parse_reply(text)
                observed=w.call(call["tool"],call["args"])
            except (ValueError,TypeError): observed={"ok":False,"error":"INVALID_TOOL_JSON"}
            assert observed==e["observation"]
            messages += [{"role":"assistant","content":text or ""},
                         {"role":"user","content":dumps({"event":"observation","result":{"environment":"mock",**observed}})}]
        row=next(r for r in private["results"] if r["id"]==case["id"])
        assert w.passed()==row["passed"] and w.report==row["report"]
assert len(verified)==72
audit={"verified_new_benchmark_model_cases":72,"identical_before_after_initial_messages":True,
       "same_frozen_benchmark_files":True,"unchanged_model_outputs_forwarded":True,"native_token_usage_verified":True,
       "training_and_evaluation_sources_verified":True,"private_model_cases":48,"recovery":recoveries,"live_service_actions":0,"details":verified}
(OUT/"verification.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:v for k,v in audit.items() if k!="details"}))
