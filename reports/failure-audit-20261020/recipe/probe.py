"""Failure-selected v2.4 diagnostic; never extrapolate to a complete score."""
import json
from pathlib import Path
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
REPO=Path('D:/Codex/workspaces/narae_bench')
TRAIN=Path('D:/Codex/training/narae3-qwen4b-20261020')
sys.path.insert(0,str(TRAIN/'scripts'))
from runtime import Server, ALIAS, load, dump, sha

CASES=['NP-E-04','NP-E-WXS-READ-02','NP-E-WXS-WRITE-01','NP-N-01','CBE-03','CBE-07']
sources={n:sha(REPO/n) for n in ['bench.py','cases.json','mock/cli.py','mock/mock_workflow.py','mock/evaluate.py','mock/contracts.py']}
dump(ROOT/'diagnostic-plan.json',{'type':__doc__,'cases':CASES,'profile':'high-level-mock-cli-v2.4',
    'model':ALIAS,'strength':1,'max_tokens':2048,'max_tool_turns':8,'temperature':0,'seed':719,
    'source_sha256':sources,'used_for_model_selection':False,'added_to_historical_full_score':False})
with socket.socket() as port:port.bind(('127.0.0.1',18464))
server=Server('failure-contract-v24-audit',1)
try:
    assert server.manifest==load(REPO/'reports/narae3-20261020/serving/narae3-public-resume.json')
    dump(ROOT/'diagnostic-serving.json',server.manifest)
    command=[sys.executable,'-X','utf8',str(REPO/'mock/evaluate.py'),'--base-url','http://127.0.0.1:18464/v1',
             '--model',ALIAS,'--out',str(ROOT/'diagnostic'),'--format','schema']
    for cid in CASES:command+=['--case',cid]
    print(json.dumps({'stage':'started','cases':CASES}),flush=True)
    with (ROOT/'diagnostic-controller.log').open('xb') as log:
        subprocess.run(command,stdout=log,stderr=log,check=True)
    for name,digest in sources.items():assert sha(REPO/name)==digest
    results=load(ROOT/'diagnostic/results.json')
    rows=[r for r in results['results'] if r['case_id'] in CASES]
    assert len(rows)==6 and all(r['status'] in ('PASS','FAIL') for r in rows)
    assert not (ROOT/'diagnostic/controller-error.json').exists()
    transcripts=[json.loads(s) for s in (ROOT/'diagnostic/model-transcript.jsonl').read_text(encoding='utf8').splitlines()]
    verified=0
    for row in rows:
        cid=row['case_id'];e=load(ROOT/f'diagnostic/evidence/{cid}.json')
        calls=[t for t in transcripts if t['case_id']==cid]
        for t,trace in zip(calls,e['trace']):
            q,r=t['request'],t['response']
            assert q['model']==r['model']==ALIAS and q['max_tokens']==2048 and q['seed']==719 and q['temperature']==0
            assert r['choices'][0]['finish_reason']=='stop' and r['usage']['completion_tokens']<=2048
            call=json.loads(r['choices'][0]['message']['content'])
            assert call=={'tool':trace['tool'],'args':trace['args']}
            if t['observation']['event']=='observation':
                assert t['observation']['result']=={'environment':'mock',**trace['result']}
            verified+=1
        assert len(calls)==len(e['trace']) and e['live_service_actions']==0
    dump(ROOT/'diagnostic-verification.json',{'type':'actual-model selected diagnostic, not full benchmark or training',
        'profile':results['profile'],'cases':CASES,'passed':sum(r['status']=='PASS' for r in rows),
        'transcript_calls_verified':verified,'rows':rows,'source_sha256':sources,'model_manifest_matches_historical':True,
        'added_to_historical_full_score':False,'weight_training_performed':False,'live_service_actions':0})
    print(json.dumps({'stage':'completed','passed':sum(r['status']=='PASS' for r in rows),'cases':6}),flush=True)
finally:server.close()
