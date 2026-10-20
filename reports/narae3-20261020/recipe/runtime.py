"""Verified native Q4 base plus real learned LoRA, UTF-8 final JSON responses."""
import atexit,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:18464'
EXE=Path(r'D:\Codex\tools\llama-b11669-win-cpu/llama-server.exe')
EXE_SHA='6a4635aeb35656153d4bfeeddf761d24ed84aada9c9108d580737cbed465141b'
ALIAS='Narae3-Qwen3-4B-LoRA-v1'
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix(p.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for attempt in range(100):
        try:temp.replace(p);return
        except PermissionError:
            if attempt==99:raise
            time.sleep(.05)
def request(route,payload=None,timeout=600):
    data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(BASE+route,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
class Server:
    def __init__(self,tag,scale=None):
        base=load(Path(r'D:\Codex\models\Qwen3-4B-Instruct-2507-Q4_K_M/verified-source.json'))
        assert sha(base['file'])==base['sha256'] and sha(EXE)==EXE_SHA
        self.alias='Qwen3-4B-Instruct-2507' if scale is None else ALIAS
        self.tag=tag
        command=[str(EXE),'--model',base['file'],'--alias',self.alias,'--host','127.0.0.1','--port','18464',
            '--threads','6','--threads-batch','6','--ctx-size','8192','--parallel','1','--batch-size','512','--ubatch-size','128',
            '--cache-ram','0','--no-context-shift','--no-warmup','--no-webui','--seed','719',
            '--chat-template-kwargs','{"enable_thinking":false}']
        adapter=None
        if scale is not None:
            adapter=load(ROOT/'exports/verification.json')
            assert adapter['all_f32_tensors_bitwise_equal'] and adapter['tensors']==84
            assert sha(adapter['file'])==adapter['export_sha256']
            assert sha(ROOT/'outputs'/ALIAS/'adapter/adapter_model.safetensors')==adapter['source_sha256']
            command+=['--lora',adapter['file']]
        log=ROOT/'evaluation/logs'/f'{tag}-server.log';log.parent.mkdir(parents=True,exist_ok=True)
        self.log=log.open('ab')
        self.process=subprocess.Popen(command,stdout=self.log,stderr=self.log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(self.close)
        try:
            began=time.monotonic()
            while True:
                if self.process.poll() is not None:raise RuntimeError('Native model server exited')
                try:
                    if request('/health',timeout=5).get('status')=='ok':break
                except (OSError,TimeoutError):pass
                if time.monotonic()-began>180:raise TimeoutError('Native server startup timed out')
                time.sleep(.25)
            if scale is not None:request('/lora-adapters',[{'id':0,'scale':scale}])
            loaded=request('/lora-adapters')
            if scale is None:assert loaded==[]
            else:
                assert len(loaded)==1 and loaded[0]['scale']==scale
                assert Path(loaded[0]['path']).resolve()==Path(adapter['file']).resolve()
            assert self.alias in [m['id'] for m in request('/v1/models')['data']]
            self.manifest={'alias':self.alias,'base':base,'adapter':adapter,'actual_narae_weight_training':scale is not None,
                'scale':scale,'loaded_adapters':loaded,'command':command,'executable_sha256':EXE_SHA}
            dump(ROOT/'evaluation/serving'/f'{tag}.json',self.manifest)
        except BaseException:self.close();raise
    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=10)
        self.log.close()
