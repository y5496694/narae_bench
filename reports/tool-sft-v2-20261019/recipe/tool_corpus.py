"""Independent synthetic tool episodes. No benchmark cases, answers or evaluator imports."""
import copy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def shape(value):
    if value is None: return {"type": "null"}
    if isinstance(value, bool): return {"type": "boolean"}
    if isinstance(value, (int, float)): return {"type": "number"}
    if isinstance(value, str): return {"type": "string"}
    if isinstance(value, list): return {"type": "array", **({"items": shape(value[0])} if value else {})}
    return {"type": "object", "properties": {k: shape(v) for k,v in value.items()}}


class World:
    """Small executable simulator; observations depend on the model's actual calls."""
    def __init__(self, scenario):
        self.s = copy.deepcopy(scenario)
        self.kind = self.s["kind"]
        self.state = {"saved": None, "draft": {}, "sent": [], "verified": False}
        self.calls = []
        self.report = None
        self.failures = 0

    def call(self, tool, args):
        self.calls.append({"tool": tool, "args": copy.deepcopy(args)})
        try:
            result = self.dispatch(tool, args)
        except (KeyError, ValueError, TypeError, StopIteration) as error:
            self.failures += 1
            result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        return result

    def dispatch(self, tool, a):
        s, state = self.s, self.state
        if tool == "finish":
            self.report = copy.deepcopy(a)
            return {"ok": True, "finished": True}
        if tool == "documents.query" and self.kind == "query":
            if a.get("date_basis") not in ["processed", "registered"]:
                raise ValueError("date_basis must be processed or registered")
            if any(a.get(k) != v for k,v in s["filters"].items()):
                raise ValueError("Query filters differ from the requested filters")
            complete = a.get("all_pages") is True or len(s["rows"]) <= 1
            rows = s["rows"] if complete else s["rows"][:1]
            state["queried_complete"] = complete
            return {"ok": True, "query": a, "rows": rows, "pages": [1,2] if len(rows)>1 else [1],
                    "total_rows": len(rows), "has_more": not complete}
        if tool == "ask" and self.kind == "neis":
            if a.get("fields") != ["end"]: raise ValueError("Ask for the missing end time")
            state["asked"] = True
            return {"ok": True, "provided": {"end": s["fields"]["end"]}}
        if tool == "neis.prepare" and self.kind == "neis":
            f = a["fields"]
            if not isinstance(f, dict): raise ValueError("fields must be an object")
            if f != s["fields"]: raise ValueError("MISSING_OR_DIFFERENT_FIELD")
            if s["missing_end"] and not state.get("asked"): raise ValueError("ASK_MISSING_END_FIRST")
            state["prepared"] = True
            return {"ok": True, **s["expected_report"]}
        if tool == "wxs.apply" and self.kind == "write":
            f = a["fields"]
            if not isinstance(f, dict): raise ValueError("fields must be an object")
            state["draft"].update(copy.deepcopy(f))
            state["verified"] = False
            return {"ok": True, "updated": sorted(f), "saved": False}
        if tool in ["wxs.save", "wxs.saved"] and self.kind == "write":
            if a["draft_id"] != s["draft_id"]: raise ValueError("UNKNOWN_DRAFT_ID")
            if tool == "wxs.save":
                state["saved"] = copy.deepcopy(state["draft"])
                return {"ok": True, "draft_id": s["draft_id"], "saved": True, "verified": False, "submitted": False, "sent": False}
            state["verified"] = state["saved"] is not None
            return {"ok": True, "draft_id": s["draft_id"], "fields": state["saved"], "saved": state["verified"],
                    "verified": state["verified"], "submitted": False, "sent": False}
        if tool == "cbe.search" and self.kind == "message":
            if a["name"] != s["person"]["name"]: return {"ok": True, "users": [], "scope": "my", "fallback": False, "searched": ["my"]}
            scope = "all" if s["fallback"] else "my"
            state["searched"] = True
            return {"ok": True, "users": [s["person"], s["other_person"]], "scope": scope,
                    "fallback": s["fallback"], "searched": ["my", "all"] if s["fallback"] else ["my"]}
        if tool == "cbe.send" and self.kind == "message":
            if not state.get("searched"): raise ValueError("SEARCH_RECIPIENT_FIRST")
            wanted = s["send_args"]
            if a != wanted: raise ValueError("SEND_FIELDS_DO_NOT_MATCH_REQUEST")
            if state["sent"]: raise ValueError("DUPLICATE_SEND")
            state["sent"].append({"id": s["message_id"], **copy.deepcopy(a)})
            return {"ok": True, "message_id": s["message_id"], "message_ids": [s["message_id"]],
                    "room_id": wanted["room_id"], "sent": True, "verified": False}
        if tool == "cbe.verify" and self.kind == "message":
            ids = a.get("message_ids") or [a["message_id"]]
            if ids != [s["message_id"]] or not state["sent"]: raise ValueError("UNKNOWN_MESSAGE_ID")
            state["verified"] = True
            return {"ok": True, **s["expected_report"], "partial": False, "resent": False}
        raise ValueError("UNSUPPORTED_TOOL")

    def passed(self):
        if self.report != self.s["expected_report"]: return False
        if self.kind == "query": return bool(self.state.get("queried_complete"))
        if self.kind == "neis": return bool(self.state.get("prepared"))
        if self.kind == "write": return self.state["verified"] and self.state["saved"] == self.s["fields"]
        return self.state["verified"] and len(self.state["sent"]) == 1


def scenario(kind, seed):
    rng = random.Random(seed)
    suffix = hashlib.sha256(str(seed).encode()).hexdigest()[:8]
    school = rng.choice(["푸른중", "솔빛고", "달오름초", "은하중"])
    year = {731: 2027, 842: 2028, 953: 2029}[seed//1000]
    day = date(year,1,5) + timedelta(days=rng.randrange(300))
    person = {"id": "person-"+suffix, "name": rng.choice(["김다온", "박도윤", "윤서진", "정하람"]), "organization": school, "position": "교사"}
    draft_id, message_id = "draft-"+suffix, "sent-"+suffix
    title = rng.choice(["독서 행사", "융합 수업", "진로 체험", "학습 동아리"])
    s = {"id": f"episode-{kind}-{seed}", "kind": kind, "seed": seed, "draft_id": draft_id, "message_id": message_id}
    tools = {}
    initial = {}
    if kind == "query":
        filters = {"scope": rng.choice(["my_documents", "registry"]), "role": rng.choice(["drafted", "received", "approved"]),
                   "from": day.isoformat(), "to": (day+timedelta(days=9)).isoformat(), "date_basis": rng.choice(["processed", "registered"]),
                   "title_contains": title, "drafter_id": person["id"], "condition": ""}
        rows = [{"id": f"doc-{suffix}-{i}", "title": title, "document_number": f"문서-{rng.randrange(3000,9000)}"} for i in range(rng.randrange(5))]
        s.update(filters=filters, rows=rows)
        tools["documents.query"] = 'args: scope=my_documents|registry, role=drafted|received|approved, from,to,date_basis=processed|registered,title_contains,drafter_id,condition,all_pages boolean. Select one enum value. Returns actual rows,pages,has_more.'
        request = "다음 검색 조건을 모두 지켜 문서를 조회하고 중복 없는 ID와 건수를 보고하세요. 전체 페이지를 확인하세요. 조건: "+dumps(filters)
        report = {"ids": [r["id"] for r in rows], "total": len(rows), "date_basis": filters["date_basis"], "pages": [1,2] if len(rows)>1 else [1], "role": filters["role"], "scope": filters["scope"]}
        plan = [("documents.query", {**filters, "all_pages": True})]
        bad = ("documents.query", {**filters, "date_basis": "processed|registered"})
    elif kind == "neis":
        start = rng.choice([8,9,10,13,15]); duration = rng.choice([1,2,3])
        fields = {"type": rng.choice(["연가-조퇴", "관내출장", "관외출장"]), "date": day.isoformat(), "start": f"{start:02}:00", "end": f"{start+duration:02}:00", "reason": title+" 협의",
                  "destination": "학생문화관", "transport": "대중교통", "expense": "여비 미지급", "companions": [], "approval_route": [{"id": "approval-"+suffix, "organization": school, "role": "결재"}]}
        missing = seed%4 == 1
        public = copy.deepcopy(fields)
        if missing: public.pop("end")
        s.update(fields=fields, missing_end=missing)
        tools["neis.prepare"] = 'args JSON structure: {"fields": {}}. Put the complete requested object inside args.fields. Does not submit; returns calculated duration and preparation state.'
        plan = []
        if missing:
            tools["ask"] = "args: fields array of missing field names. Returns the user's provided values."
            plan.append(("ask", {"fields": ["end"]}))
        request = "허용된 값으로 복무를 준비하고 계산된 분 단위 시간을 보고하세요. 필수값이 빠졌으면 질문하세요. 최종 상신 금지. "+dumps(public)
        report = {"fields": fields, "duration_minutes": duration*60, "ready": True, "submitted": False, "saved_separately": False}
        plan.append(("neis.prepare", {"fields": fields}))
        bad = ("neis.prepare", public)
    elif kind == "write":
        deadline = (day+timedelta(days=8)).isoformat()+" 16:30"
        source = {"institution": "학생지원팀", "number": rng.randrange(4000,9000), "date": day.isoformat(), "title": title+" 운영", "audience": "희망 학급", "deadline": deadline, "method": "담당자 전자우편", "exception": "미참여 학급은 회신 생략"}
        body = f'1. 관련: {source["institution"]}-{source["number"]}({source["date"]}, "{source["title"]}")호\n2. {source["audience"]}은 {source["deadline"]}까지 {source["method"]}으로 명단을 제출해 주시기 바랍니다. {source["exception"]}.  끝.'
        fields = {"title": title+" 명단 제출", "visibility": rng.choice(["공개", "부분공개"]), "privacy_reasons": [], "security": "일반", "access_scope": school,
                  "approval_route": [{"id": "approval-"+suffix, "organization": school, "role": "결재"}], "recipients": ["org-"+suffix], "attachments": [], "auto_send": False, "body": body}
        if fields["visibility"] == "부분공개": fields["privacy_reasons"] = ["개인정보 포함"]
        initial = {"draft_id": draft_id, "source": source, "draft": {"title": "이전 초안", "auto_send": True}, "public_style_rules": '본문은 1. 관련: 기관-번호(생산일자, "제목")호 다음 줄 2. 대상·기한·방법·예외를 보존. 무첨부는 붙임 없이 공백 두 칸 뒤 끝.으로 마침.'}
        requested = {k:v for k,v in fields.items() if k!="body"}
        request = "원문 사실과 공개 본문 형식으로 초안을 작성해 같은 기안에 임시저장하고 저장 내용을 다시 확인하세요. 상신·발송 금지. 설정: "+dumps(requested)
        tools = {"wxs.apply": 'args: {"fields": {}}. Put edited field values inside args.fields. Allowed: title,visibility,privacy_reasons,security,access_scope,approval_route,recipients,attachments,auto_send,body. Does not save.',
                 "wxs.save": "args: draft_id from initial state. Saves without submitting or sending.", "wxs.saved": "args: draft_id. Reads actual saved fields and verifies them."}
        report = {"draft_id": draft_id, "saved": True, "verified": True, "submitted": False, "sent": False, "title": fields["title"], "visibility": fields["visibility"], "attachment_count": 0, "recipient_ids": fields["recipients"], "auto_send": False}
        s["fields"] = fields
        plan = [("wxs.apply", {"fields": fields}), ("wxs.save", {"draft_id": draft_id}), ("wxs.saved", {"draft_id": draft_id})]
        bad = ("wxs.apply", {"title": fields["title"]})
    else:
        kind_value = rng.choice(["note", "chat"])
        room = "room-"+suffix if kind_value == "chat" else None
        send_args = {"kind": kind_value, "recipient_id": person["id"], "room_id": room, "title": "" if room else title+" 안내", "body": title+" 모임은 "+day.isoformat()+" 14:20 학생문화관에서 열립니다.", "files": []}
        initial = {"my_organization": school, "existing_room": room}
        request = f'{school} {person["name"]} 교사에게 다음 허용된 가상 메시지를 한 번 보내고 실제 서버 기록을 확인하세요. 수신자는 먼저 이름과 소속으로 검색하세요. '+dumps({k:v for k,v in send_args.items() if k!="recipient_id"})
        tools = {"cbe.search": "args: name,scope=auto|my|all. auto searches my organization first; successful zero results allow fallback. Returns observed candidates.",
                 "cbe.send": "args: kind=note|chat,recipient_id,room_id,title,body,files. One mock send; use observed IDs and existing room.",
                 "cbe.verify": "args: message_id from actual send result. Re-reads the server record without resending."}
        report = {"message_id": message_id, **send_args, "sent": True, "verified": True, "send_count": 1, "new_room_created": False}
        s.update(person=person, other_person={**person, "id": "other-"+suffix, "organization": "다른학교"}, fallback=seed%3==0, send_args=send_args)
        plan = [("cbe.search", {"name": person["name"], "scope": "auto"}), ("cbe.send", send_args), ("cbe.verify", {"message_id": message_id})]
        bad = ("cbe.verify", {"message_id": "unobserved"})
    s["expected_report"] = report
    s["task"] = {"case_id": s["id"], "environment": "mock", "request": request, "initial": initial,
                 "available_tools": tools, "finish_report_fields": sorted(report), "finish_report_schema": shape(report)}
    s["plan"] = plan + [("finish", report)]
    s["bad_prefix"] = bad if seed%4==0 else None
    return s


def dialogue(s, system):
    w = World(s)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": dumps(s["task"])}]
    if s["bad_prefix"]:
        tool, args = s["bad_prefix"]
        result = w.call(tool, args)
        assert result["ok"] is False
        messages += [{"role": "assistant", "content": dumps({"tool": tool, "args": args}), "loss": False},
                     {"role": "user", "content": dumps({"event": "observation", "result": {"environment": "mock", **result}})}]
    for tool, args in s["plan"]:
        messages.append({"role": "assistant", "content": dumps({"tool": tool, "args": args}), "loss": True})
        result = w.call(tool, args)
        assert result["ok"]
        if tool != "finish": messages.append({"role": "user", "content": dumps({"event": "observation", "result": {"environment": "mock", **result}})})
    assert w.passed()
    return {"id": s["id"], "kind": s["kind"], "messages": messages, "scenario": s}


def build():
    system = (ROOT / "data/system.txt").read_text(encoding="utf-8")
    counts = {"train": 24, "validation": 6, "test": 6}
    (ROOT / "data/trajectories").mkdir(exist_ok=True)
    ids = set()
    manifests = {}
    for split, count in counts.items():
        rows = []
        offset = {"train": 731000, "validation": 842000, "test": 953000}[split]
        for k, kind in enumerate(["query", "neis", "write", "message"]):
            for i in range(count):
                row = dialogue(scenario(kind, offset+k*100+i), system)
                assert row["id"] not in ids
                ids.add(row["id"]); rows.append(row)
        trajectory_path = ROOT / "data/trajectories" / (split+".jsonl")
        trajectory_path.write_text("".join(dumps(row)+"\n" for row in rows), encoding="utf-8")
        expanded = []
        for row in rows:
            targets = [i for i,m in enumerate(row["messages"]) if m["role"] == "assistant" and m.get("loss", True)]
            selected = [targets[row["scenario"]["seed"] % (len(targets)-1)], targets[-1]]
            for index in selected:
                item = copy.deepcopy(row)
                item["id"] += f"-turn-{index}"
                item["trajectory_id"] = row["id"]
                item["messages"] = item["messages"][:index+1]
                for m in item["messages"][:-1]:
                    if m["role"] == "assistant": m["loss"] = False
                expanded.append(item)
        rows = expanded
        if split == "train":
            old = Path(r"D:\Codex\training\narae-sft-20261019/data/train.jsonl")
            records = [json.loads(x) for x in old.read_text(encoding="utf-8").splitlines()]
            replay = []
            for kind in ["route", "quote"]:
                selected = [r for r in records if r["kind"] == kind and "unsupported" not in r["answer"]][:8]
                replay += [{"id": "replay-"+r["id"], "kind": "replay_"+kind, "messages": [{"role": "system", "content": r["system"]}, {"role": "user", "content": r["user"]}, {"role": "assistant", "content": r["answer"], "loss": True}]} for r in selected]
            rows += replay
        random.Random(offset).shuffle(rows)
        path = ROOT / "data" / (split+".jsonl")
        path.write_text("".join(dumps(row)+"\n" for row in rows), encoding="utf-8")
        manifests[split] = {"records": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "tool_trajectories": len({row["trajectory_id"] for row in rows if "scenario" in row}),
                            "next_turn_tool_examples": sum("scenario" in row for row in rows),
                            "masked_bad_prefixes": sum(bool(row.get("scenario",{}).get("bad_prefix")) for row in rows)}
    manifest = {"type": "independently generated synthetic multi-turn school tool corpus", "files": manifests,
                "benchmark_cases_or_answers_read_by_generator": False, "shared_interface": "Public tool names, argument contracts and system prompt only",
                "split_unit": "Whole trajectory with disjoint seeds, dates and IDs; templates shared, not a novel-workflow test",
                "error_prefix_loss": "Incorrect initial assistant calls are context only and never supervised targets",
                "loss_mask": "Native generation prompt plus separately tokenized next assistant answer and EOS. Entire previous multi-turn history is context only.",
                "replay": "16 examples from v1 training split only; no v1 validation/test replay",
                "live_service_actions": 0, "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (ROOT / "data/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(dumps(manifest))


if __name__ == "__main__":
    build()
