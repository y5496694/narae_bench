import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
(root / "work").mkdir(exist_ok=True)
test_root = Path(tempfile.mkdtemp(prefix="validation-", dir=root / "work"))
checks = []


def call(*args, success=True):
    proc = subprocess.run([sys.executable, "-X", "utf8", str(root / "bench.py"), *map(str, args)],
                          text=True, encoding="utf-8", capture_output=True)
    assert (proc.returncode == 0) is success, (proc.returncode, proc.stdout, proc.stderr)
    return json.loads(proc.stdout) if success else proc.stderr


def save(name, obj):
    path = test_root / name
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def record(name):
    checks.append({"check": name, "passed": True})


catalogue = json.loads((root / "cases.json").read_text(encoding="utf-8"))
assert len(catalogue["cases"]) == 45
assert sum(catalogue["domains"].values()) == 100
assert all(sum(k["weight"] for k in c["checks"]) == 100 for c in catalogue["cases"])
record("45 case IDs / six domains / weights sum to 100")

for name in ["seed-a", "seed-b"]:
    call("prepare", "--seed", "20261019", "--run-id", "VERIFY", "--out", test_root / name)
a = json.loads((test_root / "seed-a" / "write_cases.json").read_text(encoding="utf-8"))
b = json.loads((test_root / "seed-b" / "write_cases.json").read_text(encoding="utf-8"))
assert a == b and len(a) == 3
record("seed deterministically reproduces exactly three synthetic write tasks")
public = json.loads((test_root / "seed-a" / "write_tasks.json").read_text(encoding="utf-8"))
assert all("reference_body" not in c for c in public)
record("public write tasks exclude reference answers")
assert [len(c["attachments"]) for c in a] == [1, 2, 0]
assert a[2]["initial_state"]["recipients"] == ["recipient_1"]
record("attachment counts and initial auto-send recipient state are consistent")
import hashlib
for case in a:
    for attachment in case["attachments"]:
        data = (test_root / "seed-a" / attachment["filename"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == attachment["sha256"]
record("all dummy attachment hashes match bytes")

base = json.loads((test_root / "seed-a" / "results.json").read_text(encoding="utf-8"))
empty = call("grade", save("empty.json", base))
assert empty["strict_e2e_score"] == 0 and empty["not_run"] == 45
record("unrun tasks score zero and stay in denominator")

evidence = test_root / "evidence.txt"
evidence.write_text("SYNTHETIC TEST EVIDENCE; not school-service evidence", encoding="utf-8")
full = copy.deepcopy(base)
full["support_frozen_before_run"] = True
for row in full["results"]:
    row.update(status="PASS", declared_supported=True)
    for obs in row["checks"].values():
        obs.update({"pass": True, "evidence": ["evidence.txt"]})
perfect = call("grade", save("full.json", full))
assert perfect["strict_e2e_score"] == 100 and perfect["all_cases_completed"]
record("all independently marked checks aggregate to 100 with evidence")

unsupported = copy.deepcopy(full)
row = unsupported["results"][0]
row.update(status="BLOCKED", declared_supported=False, failure_layer="TOOL_UNSUPPORTED")
for obs in row["checks"].values():
    obs.update({"pass": False, "evidence": []})
summary = call("grade", save("unsupported.json", unsupported))
assert summary["strict_e2e_score"] == 98 and summary["domains"]["NP-P"]["planned"] == 5
assert summary["domains"]["NP-P"]["supported_success_percent"] == 100
record("unsupported tasks do not inflate E2E; supported-only metric stays separate")

incident = copy.deepcopy(full)
incident["results"][0].update(status="FAIL", incidents=["false_success"])
summary = call("grade", save("incident.json", incident))
assert summary["strict_e2e_score"] == 98 and not summary["safety_gate_passed"]
record("critical incidents fail the safety gate and the case")

invalid = copy.deepcopy(full)
invalid["results"][0]["checks"]["K1"]["evidence"] = []
call("grade", save("no-evidence.json", invalid), success=False)
record("PASS without evidence is rejected")
invalid = copy.deepcopy(full)
invalid["results"][0]["checks"]["K1"]["evidence"] = ["missing-file.txt"]
call("grade", save("missing-evidence.json", invalid), success=False)
record("missing evidence files are rejected")
invalid = copy.deepcopy(full)
invalid["results"][0]["checks"]["K1"]["evidence"] = ["../../bench.py"]
call("grade", save("outside-evidence.json", invalid), success=False)
record("evidence outside the run folder is rejected")
invalid = copy.deepcopy(full)
invalid["results"][0]["checks"]["K1"]["pass"] = "true"
call("grade", save("bad-boolean.json", invalid), success=False)
record("string booleans are rejected")
invalid = copy.deepcopy(full)
invalid["results"][0]["case_id"] = invalid["results"][1]["case_id"]
call("grade", save("duplicate-case.json", invalid), success=False)
record("duplicate or omitted case IDs are rejected")
call("prepare", "--seed", "1", "--out", test_root / "seed-a", success=False)
record("existing run folders cannot be overwritten")

body = test_root / "body.txt"
for case in a:
    body.write_text(case["reference_body"], encoding="utf-8")
    assert call("lint-body", body)["format_findings"] == []
record("all three reference bodies pass the limited text-format linter")

result = {"test_type": "offline preparation / aggregation contract tests",
          "checks_passed": len(checks), "checks": checks,
          "live_service_tests": 0,
          "meaning": "These tests verify the benchmark helper, not school-work competence."}
(root / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"passed": len(checks), "live_service_tests": 0}))
