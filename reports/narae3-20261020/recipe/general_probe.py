"""Eight fixed elementary instruction probes, never training data or broad capability claims."""
import argparse,json
from runtime import ROOT,Server,request,load,dump
PROBES=[
    ('addition','17+26의 결과를 숫자만 답하세요.','43',False),
    ('multiplication','9 곱하기 7의 결과를 숫자만 답하세요.','63',False),
    ('sort','[8,3,11,2]를 오름차순으로 정렬한 JSON 배열만 답하세요. 설명이나 코드 블록은 쓰지 마세요.','[2,3,8,11]',True),
    ('extract','이름은 나린이고 학년은 2입니다. name 문자열과 grade 정수 키 두 개인 JSON 객체만 답하세요. 설명이나 코드 블록은 쓰지 마세요.','{"name":"나린","grade":2}',True),
    ('reverse','영문 문자열 ABCD를 역순으로 적으세요. 결과 네 글자만 답하세요.','DCBA',False),
    ('reading','원문: 행사는 목요일 오후 2시 강당에서 열립니다. 수요일에는 교실에서 준비합니다. 질문: 행사가 열리는 장소는? 장소 이름만 답하세요.','강당',False),
    ('count','배열 ["가","나","가","다"]에서 "가"의 개수를 숫자만 답하세요.','2',False),
    ('unknown','원문: 신청은 온라인으로 받습니다. 질문: 신청 마감일은? 원문에 없으면 확인 필요라고만 답하세요.','확인 필요',False),
]
def run(tag,scale):
    server=Server('general-'+tag,scale);out=ROOT/'evaluation/general'/tag;out.mkdir(parents=True,exist_ok=False)
    try:
        results=[]
        with (out/'transcript.jsonl').open('x',encoding='utf-8') as f:
            for identifier,prompt,expected,is_json in PROBES:
                payload={'model':server.alias,'messages':[{'role':'system','content':'사용자가 요청한 형식과 원문을 정확히 따르세요.'},{'role':'user','content':prompt}],
                    'temperature':0,'seed':719,'max_tokens':128,'stream':False}
                response=request('/v1/chat/completions',payload)
                assert response['model']==server.alias and response['usage']['completion_tokens']<=128
                text=(response['choices'][0]['message'].get('content') or '').strip()
                try:passed=json.loads(text)==json.loads(expected) if is_json else text==expected
                except (TypeError,ValueError):passed=False
                results.append({'id':identifier,'passed':passed});f.write(json.dumps({'id':identifier,'request':payload,'response':response,'passed':passed},ensure_ascii=False)+'\n');f.flush()
        dump(out/'results.json',{'complete':True,'passed':sum(r['passed'] for r in results),'planned':8,'results':results,
            'scope':'Eight elementary exact-format probes; not a general intelligence benchmark.'})
    finally:server.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tag',required=True);p.add_argument('--scale',type=float)
    args=p.parse_args();run(args.tag,args.scale)
