"""Independent full trajectories, all action targets, and train-only retention replay."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['HF_HOME']=str(ROOT/'cache/huggingface')
os.environ['TOKENIZERS_PARALLELISM']='false'
import copy,hashlib,json,random
from collections import Counter
from transformers import AutoTokenizer
from tool_corpus import scenario,dialogue,dumps,World
from chat_encoding import encode_dialogue

OLD=Path(r'D:\Codex\training\narae-sft-20261019/data')
tokenizer=AutoTokenizer.from_pretrained(r'D:\Codex\models\Qwen3-4B-Instruct-2507-Q4_K_M',local_files_only=True)
system=(ROOT/'data/system.txt').read_text(encoding='utf-8')
manifest={'type':'Narae3 independent synthetic full-trajectory assistant-only SFT','benchmark_data_read':False,
          'shared_public_tool_interface':True,'developer_prior_benchmark_exposure':True,'splits':{},
          'old_training_replay_only':True,'builder_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
all_ids=set()
for split,count,offset in [('train',24,1061000),('validation',6,1172000),('test',6,1283000)]:
    rows=[]
    for k,kind in enumerate(['query','neis','write','message']):
        for i in range(count):
            row=dialogue(scenario(kind,offset+k*100+i),system)
            assert row['id'] not in all_ids;all_ids.add(row['id']);rows.append(row)
    trajectory_path=ROOT/'data'/f'{split}-trajectories.jsonl'
    trajectory_path.write_text(''.join(dumps(r)+'\n' for r in rows),encoding='utf-8')
    if split in ['train','validation']:
        old=[json.loads(s) for s in (OLD/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        for kind,n in [('route',32 if split=='train' else 6),('quote',24 if split=='train' else 4),('unknown',8 if split=='train' else 2)]:
            pool=[r for r in old if r['kind']==kind];random.Random(offset+len(kind)).shuffle(pool)
            assert len(pool)>=n
            for r in pool[:n]:rows.append({'id':f'replay-{r["id"]}','kind':f'replay_{kind}','messages':[
                {'role':'system','content':r['system']},{'role':'user','content':r['user']},
                {'role':'assistant','content':r['answer'],'loss':True}]})
    if split=='train':
        for i,q in enumerate(['너는 어떤 모델이야?','나래3는 무슨 모델을 바탕으로 만들었어?','모델 이름과 기반을 알려줘.','자기소개를 한 문장으로 해줘.']):
            rows.append({'id':f'narae3-identity-{i}','kind':'identity','messages':[{'role':'system','content':'모델 이름과 기반을 정확하게 소개하세요.'},
                {'role':'user','content':q},{'role':'assistant','content':'저는 Qwen3-4B-Instruct-2507을 바탕으로 나래 업무에 맞춰 추가 학습한 나래3입니다.','loss':True}]})
    stats=[];targets=0
    for row in rows:
        ids,labels,spans=encode_dialogue(tokenizer,row)
        targets+=len(spans)
        stats.append({'id':row['id'],'tokens':len(ids),'supervised_tokens':sum(v!=-100 for v in labels),'correct_assistant_turns':len(spans)})
        if 'scenario' in row:
            w=World(row['scenario']);w.call('finish',row['scenario']['expected_report']);assert not w.passed()
    random.Random(offset).shuffle(rows)
    path=ROOT/'data'/f'{split}.jsonl';path.write_text(''.join(dumps(r)+'\n' for r in rows),encoding='utf-8')
    manifest['splits'][split]={'records':len(rows),'trajectories':count*4,'supervised_assistant_turns':targets,
        'max_tokens':max(r['tokens'] for r in stats),'kinds':dict(Counter(r['kind'] for r in rows)),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'trajectory_sha256':hashlib.sha256(trajectory_path.read_bytes()).hexdigest()}
    (ROOT/'data'/f'{split}-token-audit.json').write_text(json.dumps(stats,indent=2)+'\n',encoding='utf-8')
(ROOT/'data/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
prefix_audit=[]
validation=[json.loads(s) for s in (ROOT/'data/validation-trajectories.jsonl').read_text(encoding='utf-8').splitlines()]
for kind in ['query','neis','write','message']:
    row=next(r for r in validation if r['kind']==kind)
    positions=[i for i,m in enumerate(row['messages']) if m['role']=='assistant' and m.get('loss',True)]
    for index in [positions[0],positions[-1]]:
        messages=[{'role':m['role'],'content':m['content']} for m in row['messages'][:index]]
        prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
        prefix_audit.append({'case_id':row['id'],'message_index':index,'messages':messages,'expected_prompt':prompt,
                             'expected_tokens':tokenizer.encode(prompt,add_special_tokens=False)})
(ROOT/'data/native-prefix-audit.json').write_text(json.dumps(prefix_audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
