"""Predeclared validation set; no public benchmark score selects the adapter."""
import argparse,importlib.util,json
from pathlib import Path
from runtime import ROOT,Server,request,load,dump,sha
from tool_corpus import World,dumps
spec=importlib.util.spec_from_file_location('bridge',r'D:\Codex\workspaces\narae_bench/mock/evaluate.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

def evaluate_episode(row,alias,turns,tokens,log):
    w=World(row['scenario']);messages=[{'role':'system','content':bridge.SYSTEM},{'role':'user','content':dumps(row['scenario']['task'])}]
    if row['scenario']['bad_prefix']:
        tool,args=row['scenario']['bad_prefix'];observation=w.call(tool,args)
        messages += [{'role':'assistant','content':dumps({'tool':tool,'args':args})},
                     {'role':'user','content':dumps({'event':'observation','result':{'environment':'mock',**observation}})}]
    errors=0;limited=0
    for turn in range(turns):
        payload={'model':alias,'messages':messages,'temperature':0,'max_tokens':tokens,'seed':719,'stream':False,
            'response_format':{'type':'json_schema','json_schema':{'name':'narae3_action','schema':bridge.public_schema(row['scenario']['task'])}}}
        response=request('/v1/chat/completions',payload)
        assert response['model']==alias and response['usage']['completion_tokens']<=tokens
        text=response['choices'][0]['message'].get('content');limited+=response['choices'][0]['finish_reason']=='length'
        try:call=bridge.parse_reply(text);observation=w.call(call['tool'],call['args'])
        except (ValueError,TypeError):call={};errors+=1;observation={'ok':False,'error':'INVALID_TOOL_JSON'}
        log.write(dumps({'case_id':row['id'],'turn':turn+1,'request':payload,'response':response,'observation':observation})+'\n');log.flush()
        messages += [{'role':'assistant','content':text or ''},{'role':'user','content':dumps({'event':'observation','result':{'environment':'mock',**observation}})}]
        if call.get('tool')=='finish' or errors>=2:break
    return {'id':row['id'],'kind':row['kind'],'passed':w.passed(),'turns':turn+1,'report':w.report,
            'failed_finish':bool(w.report is not None and not w.passed()),'length_limited_responses':limited}

def main(tag,scale):
    plan=load(ROOT/'evaluation/selection-plan.json')
    for name,digest in plan['data_sha256'].items():assert sha(ROOT/name)==digest
    out=ROOT/'evaluation/validation'/tag;out.mkdir(parents=True,exist_ok=False)
    server=Server(tag,scale)
    try:
        prefix_checks=[]
        for example in load(ROOT/'data/native-prefix-audit.json'):
            actual=request('/apply-template',{'messages':example['messages']})['prompt']
            assert actual==example['expected_prompt'],example['case_id']
            ids=request('/tokenize',{'content':actual,'add_special':False,'parse_special':True})['tokens']
            assert ids==example['expected_tokens'],example['case_id']
            prefix_checks.append({'id':example['case_id'],'message':example['message_index'],'tokens':len(ids)})
        dump(out/'prefix-verification.json',{'native_prompt_and_tokens_equal_hf':True,'checks':prefix_checks})
        rows=[json.loads(s) for s in (ROOT/'data/validation-trajectories.jsonl').read_text(encoding='utf-8').splitlines()]
        rows=[next(r for r in rows if r['id']==i) for i in plan['tool_case_ids']]
        results=[]
        with (out/'transcript.jsonl').open('x',encoding='utf-8') as log:
            for row in rows:
                results.append(evaluate_episode(row,server.alias,6,768,log))
                dump(ROOT/'evaluation/status.json',{'stage':'validation','model':tag,'completed':len(results),'planned':12,'passed':sum(r['passed'] for r in results)})
            retention=[json.loads(s) for s in (ROOT/'data/validation.jsonl').read_text(encoding='utf-8').splitlines()]
            retention=[r for r in retention if r['kind'].startswith('replay_')]
            replay=[]
            for row in retention:
                payload={'model':server.alias,'messages':row['messages'][:-1],'temperature':0,'seed':719,'max_tokens':256,'stream':False}
                response=request('/v1/chat/completions',payload)
                assert response['model']==server.alias and response['usage']['completion_tokens']<=256
                reply=(response['choices'][0]['message'].get('content') or '').strip();answer=row['messages'][-1]['content'].strip()
                try:passed=json.loads(reply)==json.loads(answer) if row['kind']=='replay_route' else reply==answer
                except (ValueError,TypeError):passed=False
                replay.append({'id':row['id'],'kind':row['kind'],'passed':passed})
                log.write(dumps({'case_id':row['id'],'request':payload,'response':response,'passed':passed})+'\n');log.flush()
        result={'complete':True,'alias':server.alias,'scale':scale,'tool_passed':sum(r['passed'] for r in results),'tool_total':12,
            'retention_passed':sum(r['passed'] for r in replay),'retention_total':12,'failed_finishes':sum(r['failed_finish'] for r in results),
            'length_limited_responses':sum(r['length_limited_responses'] for r in results),'tool_results':results,'retention_results':replay}
        dump(out/'results.json',result);print(dumps({k:v for k,v in result.items() if not isinstance(v,list)}),flush=True)
    finally:server.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tag',required=True);p.add_argument('--scale',type=float)
    args=p.parse_args();main(args.tag,args.scale)
