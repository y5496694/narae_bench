"""One conservative full-trajectory SFT pass on a fresh Qwen3-4B instruction base."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import sys;sys.path.insert(0,str(ROOT/'scripts'))
for key,folder in {'HF_HOME':'cache/huggingface','HF_HUB_CACHE':'cache/huggingface/hub','HF_MODULES_CACHE':'cache/modules',
    'TORCH_HOME':'cache/torch','TORCHINDUCTOR_CACHE_DIR':'cache/inductor','TORCH_EXTENSIONS_DIR':'cache/extensions','TEMP':'tmp','TMP':'tmp'}.items():
    os.environ[key]=str(ROOT/folder)
os.environ['HF_HUB_DISABLE_XET']='1';os.environ['TOKENIZERS_PARALLELISM']='false'
import gc,hashlib,importlib.metadata,json,math,random,time,traceback
import torch
from torch.nn import functional as F
from transformers import AutoModelForCausalLM,AutoTokenizer,BitsAndBytesConfig
from peft import LoraConfig,get_peft_model
from runtime import ALIAS,dump,load,sha
from chat_encoding import encode_dialogue
torch.set_num_threads(6);torch.set_num_interop_threads(1)
class Captured(Exception):pass
class Run:
    def __init__(self):
        self.started=time.monotonic();self.output=ROOT/'outputs'/ALIAS;self.output.mkdir(parents=True,exist_ok=True)
        self.cache=ROOT/'cache/features';self.cache.mkdir(parents=True,exist_ok=True)
        self.step=0;self.model=None
    def emit(self,stage,**values):
        event={'model':ALIAS,'stage':stage,'elapsed_seconds':round(time.monotonic()-self.started,2),**values}
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(event)+'\n')
        dump(self.output/'status.json',event);print(json.dumps(event),flush=True)
    def parts(self):
        base=self.model.get_base_model();return base.model.layers,base.model.norm,base.get_output_embeddings()
    def encode(self,row):
        ids,labels,spans=encode_dialogue(self.tokenizer,row)
        return {'input_ids':torch.tensor([ids]),'labels':torch.tensor([labels])},spans
    def cached_loss(self,record):
        layers,norm,head=self.parts();hidden=record['hidden']
        for layer in layers[self.start_layer:]:
            result=layer(hidden,*record['args'],**record['kwargs']);hidden=result[0] if isinstance(result,tuple) else result
        labels=record['labels'][:,1:];positions=labels.ne(-100)
        logits=head(norm(hidden)[:,:-1,:][positions]).float()
        return F.cross_entropy(logits,labels[positions])
    def capture(self,input_ids):
        layers,_,_=self.parts();collected={}
        def hook(module,args,kwargs):
            kwargs=dict(kwargs)
            if args:hidden,rest=args[0],args[1:]
            else:hidden,rest=kwargs.pop('hidden_states'),()
            collected.update(hidden=hidden.detach(),args=rest,kwargs=kwargs);raise Captured()
        handle=layers[self.start_layer].register_forward_pre_hook(hook,with_kwargs=True)
        try:
            with torch.no_grad():
                try:self.model(input_ids=input_ids,use_cache=False)
                except Captured:pass
                else:raise RuntimeError('Frozen prefix hook not reached')
        finally:handle.remove()
        return collected
    def cache_records(self,rows,split):
        paths=[];manifest=load(ROOT/'recovery/cache-manifest.json')
        for n,row in enumerate(rows):
            encoded,_=self.encode(row);path=self.cache/(row['id']+'.pt')
            assert sha(path)==manifest['files'][str(path.relative_to(ROOT))]
            record=self.read(path)
            assert record['id']==row['id'] and torch.equal(record['labels'],encoded['labels'])
            assert record['hidden'].shape==(1,encoded['input_ids'].shape[1],2560)
            assert torch.isfinite(record['hidden']).all()
            paths.append(path)
        self.emit('frozen-prefix-cache-verified-and-reused',split=split,records=len(paths))
        return paths
    def read(self,path):return torch.load(path,map_location='cpu',weights_only=True)
    def mean_loss(self,paths):
        with torch.no_grad():return sum(float(self.cached_loss(self.read(p))) for p in paths)/len(paths)
    def adapter_hash(self):
        h=hashlib.sha256()
        for name,p in self.model.named_parameters():
            if 'lora_' in name:h.update(name.encode());h.update(p.detach().float().contiguous().numpy().tobytes())
        return h.hexdigest()
    def run(self):
        profile=load(ROOT/'frozen-training-profile.json')
        for name,digest in profile['source_sha256'].items():assert sha(ROOT/name)==digest,name
        source=load(ROOT/'models/source.json')
        random.seed(719);torch.manual_seed(719)
        self.emit('loading-base-nf4',source=source)
        self.tokenizer=AutoTokenizer.from_pretrained(source['path'],local_files_only=True)
        base=AutoModelForCausalLM.from_pretrained(source['path'],local_files_only=True,dtype=torch.float32,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_compute_dtype=torch.float32,bnb_4bit_use_double_quant=False),
            device_map={'':'cpu'},attn_implementation='sdpa')
        base.config.use_cache=False;self.start_layer=len(base.model.layers)-6
        projections=('q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj')
        targets=[name for name,module in base.named_modules() if any(name.startswith(f'model.layers.{i}.') for i in range(self.start_layer,len(base.model.layers))) and name.endswith(projections)]
        assert len(targets)==42
        self.model=get_peft_model(base,LoraConfig(r=8,lora_alpha=16,lora_dropout=0.0,bias='none',target_modules=targets,task_type='CAUSAL_LM'));del base
        self.model.eval()
        parameters={name:p for name,p in self.model.named_parameters() if p.requires_grad}
        assert len(parameters)==84 and all('lora_' in name for name in parameters)
        assert all(torch.count_nonzero(p).item()==0 for name,p in parameters.items() if 'lora_B' in name)
        before={name:p.detach().clone() for name,p in parameters.items()};before_hash=self.adapter_hash()
        self.model.save_pretrained(self.output/'initial-adapter',safe_serialization=True)
        from safetensors.torch import load_file
        old_initial=load_file(ROOT/'recovery/attempt-1/output/initial-adapter/adapter_model.safetensors')
        new_initial=load_file(self.output/'initial-adapter/adapter_model.safetensors')
        assert old_initial.keys()==new_initial.keys() and len(old_initial)==84
        assert all(torch.equal(old_initial[name],value) for name,value in new_initial.items())
        del old_initial,new_initial
        scalable=[m for m in self.model.modules() if isinstance(getattr(m,'scaling',None),dict) and 'default' in m.scaling]
        assert len(scalable)==42
        for value in [0,.5,1]:
            for module in scalable:module.scaling['default']=2.0*value
            assert all(module.scaling['default']==2.0*value for module in scalable)
        self.emit('recovery-preflight-passed',identical_initial_tensors=84,scalable_lora_modules=42)

        self.emit('adapter-created',trainable_parameters=sum(p.numel() for p in parameters.values()),tensors=len(parameters),adapted_layers=list(range(self.start_layer,self.start_layer+6)))
        rows={split:[json.loads(x) for x in (ROOT/'data'/f'{split}.jsonl').read_text(encoding='utf-8').splitlines()] for split in ['train','validation']}
        representative=next(r for r in rows['train'] if r['kind']=='write')
        encoded,spans=self.encode(representative);record=self.capture(encoded['input_ids']);record['labels']=encoded['labels']
        prior_record=self.read(self.cache/(representative['id']+'.pt'))
        cache_recovery_error=float((record['hidden']-prior_record['hidden']).abs().max())
        assert cache_recovery_error<=2e-4 and torch.equal(record['labels'],prior_record['labels'])
        del prior_record

        with torch.no_grad():
            full_loss=float(self.model(**encoded,use_cache=False).loss);cached_loss=float(self.cached_loss(record))
            config=self.model.get_base_model().config;config._attn_implementation='eager'
            try:eager_loss=float(self.model(**encoded,use_cache=False).loss)
            finally:config._attn_implementation='sdpa'
        assert abs(full_loss-cached_loss)<=2e-4 and abs(full_loss-eager_loss)<=2e-4
        changed=encoded['input_ids'].clone();start=spans[0]['first_token']
        changed[:,start:]=torch.randint(0,self.tokenizer.vocab_size,changed[:,start:].shape)
        perturbation=self.capture(changed)
        causal_error=float((record['hidden'][:,:start,:]-perturbation['hidden'][:,:start,:]).abs().max())
        assert causal_error<=2e-4,'Future tokens changed earlier frozen-prefix states'
        self.emit('equivalence-passed',full_loss=full_loss,cached_loss=cached_loss,eager_loss=eager_loss,future_token_causality_max_error=causal_error)
        del record,perturbation,changed,encoded
        train_paths=self.cache_records(rows['train'],'train');validation_paths=self.cache_records(rows['validation'],'validation')
        baseline_val=self.mean_loss(validation_paths)
        with torch.no_grad():baseline_first=float(self.cached_loss(self.read(validation_paths[0])))
        assert abs(baseline_val-1.475590513087809)<=1e-6
        self.emit('baseline-validation',loss=baseline_val)
        layers,_,_=self.parts()
        for i in range(self.start_layer):layers[i]=torch.nn.Identity()
        gc.collect()
        params=list(parameters.values());optimizer=torch.optim.AdamW(params,lr=5e-5,weight_decay=.01)
        total_steps=math.ceil(len(train_paths)/4);assert total_steps==41
        order=list(train_paths);random.Random(719).shuffle(order);running=[];optimizer.zero_grad(set_to_none=True)
        for n,path in enumerate(order):
            loss=self.cached_loss(self.read(path));assert torch.isfinite(loss)
            (loss/4).backward();running.append(float(loss.detach()))
            if (n+1)%4==0:
                gradient=float(torch.nn.utils.clip_grad_norm_(params,1.0));assert math.isfinite(gradient) and gradient>0
                self.step+=1;factor=min(1.0,self.step/4)*(.15+.85*(1+math.cos(math.pi*self.step/total_steps))/2)
                for group in optimizer.param_groups:group['lr']=5e-5*factor
                optimizer.step();optimizer.zero_grad(set_to_none=True)
                self.emit('training',optimizer_step=self.step,total_optimizer_steps=total_steps,mean_loss=sum(running[-4:])/4,gradient_norm=gradient)
        assert self.step==total_steps
        self.model.save_pretrained(self.output/'adapter',safe_serialization=True)
        dump(self.output/'post-update-checkpoint.json',{'optimizer_steps':self.step,
            'adapter_file_sha256':sha(self.output/'adapter/adapter_model.safetensors'),
            'recovery_amendment_sha256':sha(ROOT/'recovery/amendment.json')})
        self.emit('post-update-checkpoint-saved',optimizer_steps=self.step)

        full_val=self.mean_loss(validation_paths)
        def set_scale(value):
            for module in self.model.modules():
                if isinstance(getattr(module,'scaling',None),dict) and 'default' in module.scaling:module.scaling['default']=2.0*value
        set_scale(0)
        with torch.no_grad():zero_error=abs(float(self.cached_loss(self.read(validation_paths[0])))-baseline_first)
        assert zero_error<=1e-6
        set_scale(.5);half_val=self.mean_loss(validation_paths);set_scale(1)
        self.model.save_pretrained(self.output/'adapter',safe_serialization=True)
        changes={name:float((p.detach()-before[name]).float().norm()) for name,p in parameters.items()}
        assert len(changes)==84 and all(value>0 for value in changes.values())
        after_hash=self.adapter_hash();assert before_hash!=after_hash
        report={'name':ALIAS,'base_model':source,'actual_weight_training':True,'starting_point':'Fresh upstream Qwen3-4B-Instruct-2507, zero-B LoRA initialization; no prior Narae adapter',
            'method':'NF4 frozen base, F32 LoRA on all seven linear projections of final six decoder blocks','attention_backend':'sdpa',
            'rank':8,'alpha':16,'epochs':1,'seed':719,'learning_rate':5e-5,'optimizer_steps':self.step,'trainable_parameters':sum(p.numel() for p in params),
            'assistant_only_loss':True,'all_correct_assistant_turns_supervised':True,'incorrect_context_turns_masked':True,
            'benchmark_used_for_training_or_selection':False,'validation_losses_by_scale':{'0':baseline_val,'0.5':half_val,'1':full_val},
            'zero_scale_returns_initial_first_validation_loss_absolute_error':zero_error,'train_loss':sum(running)/len(running),
            'cached_vs_full_loss_absolute_error':abs(full_loss-cached_loss),'sdpa_vs_eager_loss_absolute_error':abs(full_loss-eager_loss),
            'future_token_causality_max_error':causal_error,'adapter_sha256_before':before_hash,'adapter_sha256_after':after_hash,
            'adapter_file_sha256':sha(self.output/'adapter/adapter_model.safetensors'),'adapter_parameter_l2_changes':changes,
            'corpus_manifest_sha256':sha(ROOT/'data/manifest.json'),'trainer_source_sha256':sha(__file__),
            'versions':{name:importlib.metadata.version(name) for name in ['torch','transformers','peft','bitsandbytes','accelerate']}}
        report.update(recovery_amendment_sha256=sha(ROOT/'recovery/amendment.json'),
            attempts=2,discarded_first_attempt_updates=41,final_artifact_optimizer_updates=41,
            first_attempt_weights_saved=False,identical_initial_adapter_tensors_verified=84,
            cached_prefix_recovery_max_error=cache_recovery_error,
            original_frozen_trainer_sha256=profile['source_sha256'][r'scripts\train_lora.py'])
        dump(self.output/'training-report.json',report)
        self.emit('complete',actual_weight_training=True,optimizer_steps=self.step,validation_losses_by_scale=report['validation_losses_by_scale'])
if __name__=='__main__':
    run=Run()
    try:run.run()
    except BaseException as e:run.emit('failed',error=str(e),traceback=traceback.format_exc());raise
