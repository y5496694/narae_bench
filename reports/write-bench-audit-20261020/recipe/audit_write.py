"""Public-input-only controls and recorded-model analysis; no model inference."""
import copy,hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
REPO=Path(r'D:\Codex\workspaces\narae_bench')
ROOT=Path(__file__).resolve().parent
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,value):Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def public_plan(public,variant='valid'):
    """Only the evaluated agent's public request, bindings and initial state enter here."""
    initial=public['initial_observation'];text=public['request']
    task=json.loads(text[text.index('{'):])
    bindings=initial['bindings'];related=task['related'];facts=task['facts']
    body=(f'1. 관련: {related["producer"]}-{related["number"]}({related["production_date"]}, "{related["title"]}")호\n'
          f'2. {facts["audience"]}은 {facts["deadline"]}까지 {facts["method"]}으로 자료를 제출해 주시기 바랍니다. '
          f'{facts["exception"]}')
    attachments=task['attachments']
    if attachments:
        items=[f'{a["label"]} {a["copies"]}부.' for a in attachments]
        if len(items)>1:items=[f'{i}. {item}' for i,item in enumerate(items,1)]
        body+='\n\n붙임  '+'\n      '.join(items)+'  끝.'
    else:body+='  끝.'
    fields={'title':task['title'],'visibility':task['disclosure']['visibility'],
        'privacy_reasons':task['disclosure']['reasons'],'security':initial['draft']['security'],
        'access_scope':initial['draft']['access_scope'],
        'approval_route':[{'id':bindings[a['binding']]['id'],'organization':bindings[a['binding']]['organization'],'role':a['role']}
                          for a in task['approval_route_after_drafter']],
        'recipients':[bindings[b]['id'] for b in task['recipient_bindings']],
        'attachments':[a['filename'] for a in attachments],'auto_send':task['auto_send'],'body':body}
    recovery=public['case_id'].endswith('04')
    if recovery:fields['body']=initial['draft']['body']
    if variant=='wrong_attachment_label':
        fields['body']=body[:body.index('\n\n붙임  ')]+'\n\n붙임  잘못된 문서 999부.  끝.'
    if variant=='windows_newlines':fields['body']=fields['body'].replace('\n','\r\n')
    if variant=='wrong_recovery_body':fields['body']='사실을 전부 지운 잘못된 본문'
    if variant=='missing_attachment':fields['attachments']=fields['attachments'][:-1]
    patch={k:v for k,v in fields.items() if initial['draft'].get(k)!=v}
    steps=[]
    if recovery:steps.append(('wxs.saved',{'draft_id':initial['draft_id']}))
    if patch:steps.append(('wxs.apply',{'fields':patch}))
    steps += [('wxs.save',{'draft_id':initial['draft_id']}),('wxs.saved',{'draft_id':initial['draft_id']})]
    return steps

def run_control(module,case_id,variant):
    w=module.World(next(c for c in module.CATALOG if c['id']==case_id))
    public=w.public();steps=public_plan(public,variant)
    last=None
    for tool,args in steps:
        last=w.call(tool,copy.deepcopy(args));assert last['ok'],last
    fields=last['fields']
    report={k:last[k] for k in ['draft_id','saved','verified','submitted','sent']}
    report.update(title=fields['title'],visibility=fields['visibility'],attachment_count=len(fields['attachments']),
                  recipient_ids=fields['recipients'],auto_send=fields['auto_send'])
    w.call('finish',report);checks=w.grade()
    return {'case_id':case_id,'variant':variant,'passed':all(checks.values()),'checks':checks,
            'public':public,'steps':steps,'report':report,'tool_errors':w.errors}

def main(tag):
    out=ROOT/tag;out.mkdir(parents=True,exist_ok=False)
    state=out/'state'
    subprocess.run([sys.executable,'-X','utf8',str(REPO/'mock/cli.py'),'prepare','--out',str(state)],check=True,capture_output=True)
    os.environ['NARAE_BENCH_STATE']=str(state)
    spec=importlib.util.spec_from_file_location('write_audit_world',REPO/'mock/mock_workflow.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    controls=[run_control(module,f'NP-E-WXS-WRITE-{i:02d}','valid') for i in range(1,5)]
    controls += [run_control(module,'NP-E-WXS-WRITE-01','wrong_attachment_label'),
                 run_control(module,'NP-E-WXS-WRITE-02','wrong_attachment_label'),
                 run_control(module,'NP-E-WXS-WRITE-04','windows_newlines'),
                 run_control(module,'NP-E-WXS-WRITE-04','wrong_recovery_body'),
                 run_control(module,'NP-E-WXS-WRITE-04','missing_attachment')]
    dump(out/'controls.json',controls)
    paths=['reports/model-comparison-20261019/narae1','reports/model-comparison-20261019/narae2',
           'reports/model-comparison-20261019/qwen4b','reports/tool-sft-v2-20261019/narae1/benchmark',
           'reports/tool-sft-v2-20261019/narae2/benchmark','reports/narae3-20261020/benchmark']
    runs=[]
    for name in paths:
        folder=REPO/name;result=load(folder/'results.json');summary=load(folder/'summary.json');cases=[]
        for row in result['results']:
            if not row['case_id'].startswith('NP-E-WXS-WRITE-'):continue
            e=load(folder/'evidence'/f'{row["case_id"]}.json');cid=row['case_id']
            # Replay exact recorded calls against current grading, without repairing outputs.
            w=module.World(next(c for c in module.CATALOG if c['id']==cid))
            for entry in e['trace']:w.call(entry['tool'],copy.deepcopy(entry['args']))
            checks=w.grade()
            successful_applies=[t for t in e['trace'] if t['tool']=='wxs.apply' and t['result'].get('ok')]
            authored=any(isinstance(t['args'].get('fields',{}).get('body'),str) and t['args']['fields']['body'].strip()
                         for t in successful_applies)
            cases.append({'id':cid,'historical_status':row['status'],'historical_checks':e['checks'],
                'replayed_passed':all(checks.values()),'replayed_checks':checks,
                'actions':[t['tool'] for t in e['trace']], 'successful_apply_count':len(successful_applies),
                'authored_nonempty_body':authored,'format_errors':e['format_errors'],'tool_errors':e['tool_errors'],
                'evidence_source':name+'/evidence/'+cid+'.json'})
        runs.append({'source':name,'partial_percent':summary['domains']['NP-E-WXS-WRITE']['partial_percent'],'cases':cases})
    output={'type':'Benchmark contract audit and exact historical-call replay; no new model inference',
        'source_sha256':{n:sha(REPO/n) for n in ['bench.py','cases.json','mock/mock_workflow.py','mock/cli.py','mock/evaluate.py']},
        'control_uses_only_public_model_inputs':True,'oracle_or_reference_used_by_control':False,
        'controls_file':'controls.json','runs':runs,'live_service_actions':0}
    dump(out/'audit.json',output)
    print(json.dumps({'tag':tag,'valid_public_controls_passed':sum(c['passed'] for c in controls[:4]),
        'wrong_attachment_cases_accepted':sum(c['passed'] for c in controls[4:6]),
        'windows_newline_recovery_accepted':controls[6]['passed'],
        'historical_write_cases':sum(len(r['cases']) for r in runs),
        'newly_authored_bodies_in_18_nonrecovery_cases':sum(c['authored_nonempty_body'] for r in runs for c in r['cases'] if not c['id'].endswith('04'))}))

if __name__=='__main__':main(sys.argv[1])
