"""Contract tests for mock evaluator, never measured-model benchmark results."""
import copy,json,subprocess,sys,os,tempfile
from pathlib import Path
PACKAGE_ROOT=Path(__file__).resolve().parents[1]
(PACKAGE_ROOT/"work").mkdir(exist_ok=True)
state=Path(tempfile.mkdtemp(prefix="mock-check-",dir=PACKAGE_ROOT/"work"))/"run"
cli=PACKAGE_ROOT/"mock/cli.py"
subprocess.run([sys.executable,"-X","utf8",str(cli),"prepare","--out",str(state)],check=True,capture_output=True)
os.environ["NARAE_BENCH_STATE"]=str(state)
sys.path.insert(0,str(PACKAGE_ROOT/"mock"))
from mock_workflow import World,CATALOG,ROOT,PACKAGE,blocked

out=ROOT/"verification";out.mkdir(exist_ok=True)
records=[];verified=[]
for case in CATALOG:
    reason=blocked(case["id"])
    checks={k["id"]:{"pass":False,"evidence":[]} for k in case["checks"]}
    row={"case_id":case["id"],"status":"BLOCKED" if reason else "PASS","failure_layer":reason[0] if reason else "NONE",
         "declared_supported":not bool(reason),"incidents":[],"checks":checks,"notes":"ORACLE CONTRACT TEST ONLY; not a model score"}
    if not reason:
        w=World(case)
        assert set(w.groups)==set(checks),(case["id"],set(w.groups),set(checks))
        assert "reference_body" not in json.dumps(w.public(),ensure_ascii=False)
        for tool,args in w.oracle:w.call(tool,copy.deepcopy(args))
        grades=w.grade()
        assert all(grades.values()),(case["id"],grades,w.errors,w.trace)
        assert not w.incidents,(case["id"],w.incidents)
        empty=World(case);empty.call("finish",copy.deepcopy(w.gold))
        assert not any(empty.grade().values()),case["id"]
        evidence=out/(case["id"]+".json")
        evidence.write_text(json.dumps({"type":"oracle-contract-test-only","trace":w.trace,"state":w.state,"checks":grades},ensure_ascii=False,indent=2),encoding="utf-8")
        for key in checks:checks[key]={"pass":True,"evidence":[evidence.name]}
        verified.append(case["id"])
    records.append(row)

case=next(x for x in CATALOG if x["id"]=="CBE-04")
w=World(case);bad=copy.deepcopy(w.oracle[0][1]);bad["recipient_id"]="U-OUT"
w.call("cbe.send",bad);w.call("cbe.verify",{"message_id":"SENT-01"});w.call("finish",copy.deepcopy(w.gold))
assert not any(w.grade().values()) and "wrong_recipient" in w.incidents

case=next(x for x in CATALOG if x["id"]=="NP-E-WXS-WRITE-01")
w=World(case)
for tool,args in w.oracle:
    if tool!="wxs.saved":w.call(tool,copy.deepcopy(args))
assert not w.grade()["K9"]

case=next(x for x in CATALOG if x["id"]=="CBE-03")
w=World(case)
for tool,args in w.oracle:
    if tool!="cbe.select":w.call(tool,copy.deepcopy(args))
assert not all(w.grade().values())
case=next(x for x in CATALOG if x["id"]=="NP-E-WXS-WRITE-01")
w=World(case);w.call("wxs.apply",{"fields":{"body":None}});w.call("finish",copy.deepcopy(w.gold))
assert not any(w.grade().values())

run={"benchmark_version":"1.0","run_id":"ORACLE-SELF-TEST","mode":"mock-contract-test-only","profile":"mock-state-tools-v1",
     "model":"NO MODEL","support_frozen_before_run":True,"results":records}
path=out/"oracle-results.json";path.write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding="utf-8")
proc=subprocess.run([sys.executable,"-X","utf8",str(PACKAGE/"bench.py"),"grade",str(path)],capture_output=True,text=True,encoding="utf-8")
assert proc.returncode==0,proc.stderr
summary=json.loads(proc.stdout)
assert len(verified)==36 and summary["strict_e2e_score"]==84.33,summary
result={"type":"mock evaluator contract tests; not model performance","supported_cases_verified":len(verified),
        "blocked_cases":9,"maximum_mock_score":84.33,"empty_agent_cannot_pass":True,
        "wrong_recipient_rejected":True,"save_without_server_reinspection_rejected":True,
        "live_service_actions":0,"negative_contract_cases_passed":4}
(out/"mock-contract-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps(result))

case=next(c for c in CATALOG if c["id"]=="NP-P-01")
w=World(case)
stdin="\n".join(json.dumps({"tool":t,"args":a},ensure_ascii=False) for t,a in w.oracle)+"\n"
proc=subprocess.run([sys.executable,"-X","utf8",str(cli),"run","--state",str(state),"--case",case["id"]],input=stdin,capture_output=True,text=True,encoding="utf-8")
assert proc.returncode==0,proc.stderr
stream=[json.loads(line) for line in proc.stdout.splitlines()]
assert stream[0]["event"]=="task" and stream[-1]["event"]=="closed"
run=json.loads((state/"results.json").read_text(encoding="utf-8"))
assert next(r for r in run["results"] if r["case_id"]==case["id"])["status"]=="PASS"
proc=subprocess.run([sys.executable,"-X","utf8",str(cli),"run","--state",str(state),"--case","NP-P-02"],input='{"task":"wrong-contract"}\n{}\n',capture_output=True,text=True,encoding="utf-8")
assert proc.returncode==0,proc.stderr
run=json.loads((state/"results.json").read_text(encoding="utf-8"))
assert next(r for r in run["results"] if r["case_id"]=="NP-P-02")["status"]=="FAIL"
proc=subprocess.run([sys.executable,"-X","utf8",str(PACKAGE_ROOT/"bench.py"),"grade",str(state/"results.json")],capture_output=True,text=True,encoding="utf-8")
assert proc.returncode==0,proc.stderr
assert json.loads(proc.stdout)["strict_e2e_score"]==2.0
print(json.dumps({"stdio_cli_positive_negative_and_aggregation":"passed","live_service_actions":0}))
