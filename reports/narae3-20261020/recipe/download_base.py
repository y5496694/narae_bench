"""Download and verify the exact upstream checkpoint used by the existing 4B GGUF."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for key,value in {"HF_HOME":ROOT/"cache/huggingface","HF_HUB_CACHE":ROOT/"cache/huggingface/hub","TEMP":ROOT/"tmp","TMP":ROOT/"tmp"}.items():os.environ[key]=str(value)
os.environ["HF_HUB_DISABLE_XET"]="1"
import hashlib
import json
from huggingface_hub import HfApi
import time
import urllib.request
import shutil
from concurrent.futures import ThreadPoolExecutor

MODEL="Qwen/Qwen3-4B-Instruct-2507"
REVISION="cdbee75f17c01a7cc42f958dc650907174af0554"
DEST=Path(r"D:\Codex\models\Qwen3-4B-Instruct-2507-HF")

def main():
    info=HfApi().model_info(MODEL,revision=REVISION,files_metadata=True)
    assert info.sha==REVISION
    files=[s for s in info.siblings if s.rfilename.endswith((".json",".safetensors",".txt",".jinja")) or s.rfilename in ["README.md","LICENSE"]]
    files=[s for s in files if "/" not in s.rfilename]
    listing=[{"name":s.rfilename,"bytes":s.size,"lfs_sha256":getattr(s.lfs,"sha256",None),"git_blob":s.blob_id} for s in files]
    (ROOT/"models/download-plan.json").write_text(json.dumps({"model":MODEL,"revision":REVISION,"destination":str(DEST),"files":listing},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"stage":"downloading","bytes":sum(s.size or 0 for s in files),"files":len(files)}),flush=True)
    DEST.mkdir(parents=True,exist_ok=True)
    def fetch(s):
        target=DEST/s['name'];part=target.with_name(target.name+'.part')
        if target.exists() and target.stat().st_size==s['bytes']:return
        if s['lfs_sha256']:
            candidates=list((DEST/'.cache/huggingface/download').glob('*'+s['lfs_sha256']+'*.incomplete'))
            if candidates:
                cached=max(candidates,key=lambda p:p.stat().st_size)
                if cached.stat().st_size>(part.stat().st_size if part.exists() else 0):
                    shutil.copyfile(cached,part)
                    print(json.dumps({'stage':'resuming-cached-prefix','file':s['name'],'bytes':part.stat().st_size}),flush=True)
        failures=0
        while not part.exists() or part.stat().st_size<s['bytes']:
            offset=part.stat().st_size if part.exists() else 0
            url=f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{s["name"]}?download=true&narae={time.time_ns()}'
            req=urllib.request.Request(url,headers={'Range':f'bytes={offset}-{s["bytes"]-1}'})
            try:
                with urllib.request.urlopen(req,timeout=30) as response,part.open('ab') as output:
                    assert response.status==206 or (response.status==200 and offset==0)
                    if response.status==206:assert response.headers['Content-Range'].startswith(f'bytes {offset}-')
                    position=offset;last_report=offset
                    while chunk:=response.read(8*1024*1024):
                        output.write(chunk);position+=len(chunk)
                        if position-last_report>=128*1024*1024:
                            output.flush();last_report=position
                            print(json.dumps({'stage':'downloading','file':s['name'],'downloaded_bytes':position,'file_bytes':s['bytes']}),flush=True)
                    assert position<=s['bytes']
            except (OSError,TimeoutError) as error:
                failures+=1
                print(json.dumps({'stage':'retrying','file':s['name'],'attempt':failures,'error_type':type(error).__name__}),flush=True)
                if failures>=6:raise
            else:failures=0
        assert part.stat().st_size==s['bytes']
        part.replace(target)
        print(json.dumps({'stage':'file-downloaded','file':s['name'],'bytes':s['bytes']}),flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(fetch,listing))
    verification={}
    for s in listing:
        path=DEST/s["name"]
        assert path.stat().st_size==s["bytes"],s["name"]
        digest=hashlib.sha256()
        if s["lfs_sha256"]:
            with path.open("rb") as stream:
                for chunk in iter(lambda:stream.read(8*1024*1024),b""):digest.update(chunk)
            assert digest.hexdigest()==s["lfs_sha256"],s["name"]
        else:
            data=path.read_bytes();digest.update(data)
            assert hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==s["git_blob"],s["name"]
        verification[s["name"]]=digest.hexdigest()
    source={"model":MODEL,"revision":REVISION,"path":str(DEST),"license":"Apache-2.0","upstream_files_sha256":verification,
            "upstream_original":True,"narae_weight_training":False,"matched_existing_gguf_source_revision":True}
    (ROOT/"models/source.json").write_text(json.dumps(source,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"stage":"verified","files":len(verification)}),flush=True)

if __name__=="__main__":main()
