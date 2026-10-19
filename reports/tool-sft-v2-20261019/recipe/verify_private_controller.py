"""Local HTTP/World integration check with a stub; this is not model performance."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("evaluation",ROOT/"scripts/evaluate_native.py")
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
rows=[json.loads(x) for x in (ROOT/"data/trajectories/test.jsonl").read_text(encoding="utf-8").splitlines()]
lookup={r["id"]:r for r in rows}
mode="correct"


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        task=json.loads(payload["messages"][1]["content"])
        row=lookup[task["case_id"]]
        assert "expected_report" not in task and "plan" not in task
        count=sum(m["role"]=="assistant" for m in payload["messages"])-bool(row["scenario"]["bad_prefix"])
        tool,args=("finish",row["scenario"]["expected_report"]) if mode=="premature" else row["scenario"]["plan"][count]
        result={"model":payload["model"],"choices":[{"message":{"content":evaluation.dumps({"tool":tool,"args":args})}}],
                "usage":{"completion_tokens":1,"prompt_tokens":1}}
        data=json.dumps(result,ensure_ascii=False).encode()
        self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)


server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
evaluation.native.BASE=f"http://127.0.0.1:{server.server_address[1]}"
evaluation.OUT=ROOT/"tmp/private-controller-check"
(evaluation.OUT/"private").mkdir(parents=True,exist_ok=False)
try:
    for tag in ["correct","premature"]:
        mode=tag
        evaluation.private_tasks({"tag":tag,"alias":"NONMODEL-HTTP-STUB"})
        result=json.loads((evaluation.OUT/"private"/tag/"results.json").read_text(encoding="utf-8"))
        assert result["complete"] and result["passed"]==(24 if tag=="correct" else 0)
    audit={"type":"Non-model private controller contract test","correct_stub_tasks_passed":24,
           "premature_finish_rejected":24,"model_performance_score":False,"real_network_services":0}
    (ROOT/"evaluation/controller-contract-test.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(audit))
finally:
    server.shutdown();thread.join();server.server_close()
