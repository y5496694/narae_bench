"""Paired response-format diagnostic, not a new full-model benchmark score."""
import json,socket,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent;REPO=Path(r'D:\Codex\workspaces\narae_bench')
TRAIN=Path(r'D:\Codex\training\narae3-qwen4b-20261020')
sys.path.insert(0,str(TRAIN/'scripts'))
from runtime import Server,ALIAS,load,dump,sha
sources={n:sha(REPO/n) for n in ['bench.py','cases.json','mock/cli.py','mock/mock_workflow.py','mock/evaluate.py']}
dump(ROOT/'interface-plan.json',{'model':ALIAS,'strength':1,'case':'NP-E-WXS-WRITE-01','formats':['schema','json'],
    'max_tokens':2048,'max_tool_turns':8,'temperature':0,'seed':719,'source_sha256':sources,
    'used_for_model_selection':False,'added_to_historical_full_score':False})
with socket.socket() as probe:probe.bind(('127.0.0.1',18464))
server=Server('write-interface-audit',1)
try:
    assert server.manifest==load(REPO/'reports/narae3-20261020/serving/narae3-public-resume.json')
    dump(ROOT/'interface-serving.json',server.manifest)
    runs=[]
    for mode in ['schema','json']:
        for name,digest in sources.items():assert sha(REPO/name)==digest,name
        out=ROOT/('interface-'+mode)
        with (ROOT/('interface-'+mode+'.log')).open('xb') as log:
            print(json.dumps({'stage':'started','format':mode}),flush=True)
            subprocess.run([sys.executable,'-X','utf8',str(REPO/'mock/evaluate.py'),
                '--base-url','http://127.0.0.1:18464/v1','--model',ALIAS,'--out',str(out),
                '--case','NP-E-WXS-WRITE-01','--format',mode],stdout=log,stderr=log,check=True)
        result=load(out/'results.json');row=next(r for r in result['results'] if r['case_id']=='NP-E-WXS-WRITE-01')
        evidence=load(out/'evidence/NP-E-WXS-WRITE-01.json')
        calls=[json.loads(s) for s in (out/'model-transcript.jsonl').read_text(encoding='utf-8').splitlines()]
        for call in calls:
            q,r=call['request'],call['response']
            assert q['model']==r['model']==ALIAS and q['temperature']==0 and q['seed']==719 and q['max_tokens']==2048
            assert q['stream'] is False and r['usage']['completion_tokens']<=2048
        run={'format':mode,'status':row['status'],'actions':[t['tool'] for t in evidence['trace']],
            'checks':evidence['checks'],'format_errors':evidence['format_errors'],'tool_errors':evidence['tool_errors']}
        runs.append(run);print(json.dumps({'stage':'completed',**run}),flush=True)
    first=[json.loads((ROOT/('interface-'+mode)/'model-transcript.jsonl').read_text(encoding='utf-8').splitlines()[0])['request'] for mode in ['schema','json']]
    assert first[0]['messages']==first[1]['messages']
    baseline=[json.loads(s) for s in (REPO/'reports/narae3-20261020/current-cli/model-transcript.jsonl').read_text(encoding='utf-8').splitlines()]
    old=next(e['request'] for e in baseline if e['case_id']=='NP-E-WXS-WRITE-01' and e['turn']==1)
    assert first[0]==old
    dump(ROOT/'interface-comparison.json',{'type':'Paired response-format diagnostic; no full score or model selection',
        'same_first_messages':True,'schema_request_identical_to_previous_v22_run':True,
        'same_actual_model_and_strength':True,'source_sha256':sources,'runs':runs,'live_service_actions':0})
finally:server.close()
