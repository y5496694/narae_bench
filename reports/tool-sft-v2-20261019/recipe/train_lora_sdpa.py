"""CPU NF4 LoRA SFT of real Qwen/EXAONE checkpoints, with cached frozen prefixes.

Only the final six decoder blocks receive q/v LoRA adapters. Prefix feature
caching is exact: the preceding blocks have no trainable parameters or dropout.
Adapters are standard PEFT checkpoints; evaluation reloads the full base model.
"""
import os
from pathlib import Path
ROOT = Path(r"D:\Codex\training\narae-tool-sft-v2-20261019")
for key, folder in {
    "HF_HOME": "cache/huggingface", "HF_HUB_CACHE": "cache/huggingface/hub",
    "HF_MODULES_CACHE": "cache/modules", "TORCH_HOME": "cache/torch",
    "TORCHINDUCTOR_CACHE_DIR": "cache/inductor", "TORCH_EXTENSIONS_DIR": "cache/extensions",
    "TEMP": "tmp", "TMP": "tmp",
}.items():
    os.environ[key] = str(ROOT / folder)
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import random
import time
import traceback
import torch
from torch.nn import functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
from peft.utils.save_and_load import load_peft_weights, set_peft_model_state_dict

torch.set_num_threads(6)
torch.set_num_interop_threads(1)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_suffix(path.suffix + ".tmp")
    stage.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(100):
        try:
            stage.replace(path)
            break
        except PermissionError:
            if attempt == 99: raise
            time.sleep(.05)


class Captured(Exception):
    pass


class Run:
    def __init__(self, tag, epochs=3):
        self.tag, self.epochs = tag, epochs
        self.name = "Narae-0.6B-Tool-LoRA-v2" if tag == "0.6b" else "EXAONE-Narae-2.4B-Tool-LoRA-v2"
        self.initial_name = "Narae-0.6B-LoRA-v1" if tag == "0.6b" else "EXAONE-Narae-2.4B-LoRA-v1"
        self.initial_adapter = Path(r"D:\Codex\training\narae-sft-20261019") / "outputs" / self.initial_name / "adapter"
        self.output = ROOT / "outputs" / self.name
        self.output.mkdir(parents=True, exist_ok=True)
        self.source = json.loads((ROOT / "models" / (tag + "-source.json")).read_text())
        self.started = time.monotonic()
        self.events = self.output / "events.jsonl"
        self.cache = ROOT / "cache" / ("features-" + tag)
        self.cache.mkdir(exist_ok=True)
        self.model = None
        self.train_steps = 0
        self.emit("initializing", base=self.source)

    def emit(self, stage, **data):
        event = {"model": self.name, "stage": stage, "elapsed_seconds": round(time.monotonic()-self.started, 2), **data}
        with self.events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        write_json(self.output / "status.json", event)
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def load_base(self):
        self.emit("loading-base-nf4")
        quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                          bnb_4bit_compute_dtype=torch.float32,
                                          bnb_4bit_use_double_quant=False)
        base = AutoModelForCausalLM.from_pretrained(
            self.source["path"], trust_remote_code=self.tag == "2.4b", local_files_only=True,
            dtype=torch.float32, quantization_config=quantization,
            device_map={"": "cpu"}, attn_implementation="sdpa")
        if self.tag == "2.4b":
            from exaone_compat import configure_exaone
            configure_exaone(base)
        base.config.use_cache = False
        return base

    def parts(self):
        base = self.model.get_base_model()
        if hasattr(base, "transformer") and hasattr(base.transformer, "h"):
            return base.transformer.h, base.transformer.ln_f, base.get_output_embeddings(), "transformer.h"
        return base.model.layers, base.model.norm, base.get_output_embeddings(), "model.layers"

    def encode(self, row):
        from chat_encoding import encode_dialogue
        ids, labels = encode_dialogue(self.tokenizer, row, max_length=2048)
        return {"input_ids": torch.tensor([ids]), "labels": torch.tensor([labels])}

    def cached_loss(self, record):
        layers, norm, head, _ = self.parts()
        hidden = record["hidden"]
        for layer in layers[self.start_layer:]:
            result = layer(hidden, *record["args"], **record["kwargs"])
            hidden = result[0] if isinstance(result, tuple) else result
        hidden = norm(hidden)
        labels = record["labels"][:, 1:]
        positions = labels.ne(-100)
        # Only supervised positions need vocabulary logits; prefix loss is masked.
        logits = head(hidden[:, :-1, :][positions]).float()
        return F.cross_entropy(logits, labels[positions])

    def cache_records(self, rows, split):
        layers, _, _, _ = self.parts()
        collected = {}
        def capture(module, args, kwargs):
            kwargs = dict(kwargs)
            if args:
                hidden, rest = args[0], args[1:]
            else:
                hidden, rest = kwargs.pop("hidden_states"), ()
            collected.update(hidden=hidden.detach(), args=rest, kwargs=kwargs)
            raise Captured()
        handle = layers[self.start_layer].register_forward_pre_hook(capture, with_kwargs=True)
        paths = []
        try:
            for n, row in enumerate(rows):
                path = self.cache / (row["id"] + ".pt")
                encoded = self.encode(row)
                with torch.no_grad():
                    try:
                        self.model(input_ids=encoded["input_ids"], use_cache=False)
                    except Captured:
                        pass
                    else:
                        raise RuntimeError("Prefix capture hook was not reached")
                payload = {**collected, "labels": encoded["labels"], "id": row["id"]}
                torch.save(payload, path)
                paths.append(path)
                if n == 0 or (n+1) % 16 == 0 or n+1 == len(rows):
                    self.emit("caching-frozen-prefix", split=split, completed=n+1, total=len(rows), tokens=int(encoded["input_ids"].shape[1]))
        finally:
            handle.remove()
        return paths

    @staticmethod
    def read_cache(path):
        return torch.load(path, map_location="cpu", weights_only=True)

    def mean_loss(self, paths):
        values = []
        with torch.no_grad():
            for path in paths:
                values.append(float(self.cached_loss(self.read_cache(path))))
        return sum(values) / len(values)

    def adapter_hash(self):
        digest = hashlib.sha256()
        for name, parameter in self.model.named_parameters():
            if "lora_" in name:
                digest.update(name.encode())
                digest.update(parameter.detach().float().contiguous().numpy().tobytes())
        return digest.hexdigest()

    def run(self):
        random.seed(719); torch.manual_seed(719)
        self.tokenizer = AutoTokenizer.from_pretrained(self.source["path"], trust_remote_code=self.tag=="2.4b", local_files_only=True)
        base = self.load_base()
        if self.tag == "2.4b":
            prefix, total_layers = "transformer.h", len(base.transformer.h)
        else:
            prefix, total_layers = "model.layers", len(base.model.layers)
        self.start_layer = total_layers - 6
        targets = [name for name, module in base.named_modules()
                   if any(name.startswith(f"{prefix}.{i}.") for i in range(self.start_layer,total_layers))
                   and name.endswith(("q_proj","v_proj"))]
        assert len(targets)==12, targets
        self.model = PeftModel.from_pretrained(base, str(self.initial_adapter), is_trainable=True)
        initial_report = json.loads((self.initial_adapter.parent / "training-report.json").read_text(encoding="utf-8"))
        assert self.adapter_hash() == initial_report["adapter_sha256_after"], "Starting v1 adapter mismatch"
        del base
        self.model.eval()
        trainable, all_parameters = self.model.get_nb_trainable_parameters()
        before_hash = self.adapter_hash()
        before = {name:p.detach().clone() for name,p in self.model.named_parameters() if p.requires_grad}
        self.emit("adapter-created", trainable_parameters=trainable, total_parameters=all_parameters,
                  adapted_layers=list(range(self.start_layer,total_layers)), adapter_sha256=before_hash)
        splits = {split:[json.loads(line) for line in (ROOT/"data"/(split+".jsonl")).read_text(encoding="utf-8").splitlines()]
                  for split in ("train","validation")}
        # Verify cached-prefix equivalence against the actual complete model.
        first_paths = self.cache_records(splits["train"][:1], "equivalence")
        encoded = self.encode(splits["train"][0])
        with torch.no_grad():
            full_loss = float(self.model(**encoded,use_cache=False).loss)
            cached = float(self.cached_loss(self.read_cache(first_paths[0])))
            base_config = self.model.get_base_model().config
            try:
                base_config._attn_implementation = "eager"
                eager_loss = float(self.model(**encoded,use_cache=False).loss)
            finally:
                base_config._attn_implementation = "sdpa"
            backend_error = abs(full_loss-eager_loss)
            if backend_error > 2e-4:
                raise RuntimeError(f"Attention backend equivalence failed: {full_loss} {eager_loss}")
            self.emit("attention-backend-equivalence-passed", sdpa_loss=full_loss, eager_loss=eager_loss, absolute_error=backend_error)
        if abs(full_loss-cached) > 2e-4:
            raise RuntimeError(f"Cache equivalence failed: {full_loss} {cached}")
        self.emit("cache-equivalence-passed", full_loss=full_loss, cached_loss=cached, absolute_error=abs(full_loss-cached))
        train_paths = self.cache_records(splits["train"], "train")
        validation_paths = self.cache_records(splits["validation"], "validation")
        baseline_val = self.mean_loss(validation_paths)
        self.emit("baseline-validation", loss=baseline_val)
        # Frozen prefix weights can be released; standard PEFT adapters retain
        # their original final-layer names. A fresh full base is loaded for eval.
        layers, _, _, _ = self.parts()
        for i in range(self.start_layer):
            layers[i] = torch.nn.Identity()
        gc.collect()
        params = [p for p in self.model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=2e-4, weight_decay=0.01)
        steps_per_epoch = math.ceil(len(train_paths)/4)
        total_steps = self.epochs*steps_per_epoch
        best_loss, history = float("inf"), []
        for epoch in range(self.epochs):
            order = list(train_paths); random.Random(719+epoch).shuffle(order)
            running = []; optimizer.zero_grad(set_to_none=True)
            for n, path in enumerate(order):
                loss = self.cached_loss(self.read_cache(path))
                if not torch.isfinite(loss): raise RuntimeError("Non-finite training loss")
                (loss/4).backward(); running.append(float(loss.detach()))
                if (n+1)%4==0 or n+1==len(order):
                    gradient_norm = float(torch.nn.utils.clip_grad_norm_(params,1.0))
                    if not math.isfinite(gradient_norm) or gradient_norm == 0:
                        raise RuntimeError("Missing or invalid adapter gradients")
                    self.train_steps += 1
                    scale = min(1.0,self.train_steps/8) * (0.15+0.85*(1+math.cos(math.pi*self.train_steps/total_steps))/2)
                    for group in optimizer.param_groups: group["lr"]=2e-4*scale
                    optimizer.step(); optimizer.zero_grad(set_to_none=True)
                    if self.train_steps%4==0:
                        self.emit("training", epoch=epoch+1, optimizer_step=self.train_steps, total_optimizer_steps=total_steps,
                                  mean_loss=sum(running[-16:])/len(running[-16:]), gradient_norm=gradient_norm)
            validation = self.mean_loss(validation_paths)
            history.append({"epoch":epoch+1,"train_loss":sum(running)/len(running),"validation_loss":validation})
            self.emit("epoch-completed", **history[-1])
            self.model.save_pretrained(self.output/"last-adapter",safe_serialization=True)
            if validation < best_loss:
                best_loss = validation
                self.model.save_pretrained(self.output/"adapter",safe_serialization=True)
                write_json(self.output/"best-checkpoint.json",history[-1])
        selected = load_peft_weights(str(self.output/"adapter"),device="cpu")
        set_peft_model_state_dict(self.model,selected)
        after_hash = self.adapter_hash()
        changes = {name:float((p.detach()-before[name]).float().norm()) for name,p in self.model.named_parameters() if name in before}
        assert before_hash != after_hash and sum(changes.values()) > 0 and self.train_steps > 0
        metadata = {"name":self.name,"base_model":self.source,"actual_weight_training":True,
                    "attention_backend":"sdpa", "attention_backend_equivalence_absolute_error": backend_error, "trainer_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "method":"NF4 base plus float32 PEFT LoRA on q/v projections of final six decoder blocks",
                    "rank":16,"alpha":32,"seed":719,"epochs":self.epochs,"optimizer_steps":self.train_steps,
                    "initial_adapter": str(self.initial_adapter), "initial_adapter_file_sha256": hashlib.sha256((self.initial_adapter/"adapter_model.safetensors").read_bytes()).hexdigest(),
                    "starting_point": "Actual v1 learned adapter; continued SFT", "test_used_for_checkpoint_selection": False,
                    "corpus_manifest_sha256": hashlib.sha256((ROOT/"data/manifest.json").read_bytes()).hexdigest(),
                    "assistant_only_loss": True, "incorrect_assistant_prefixes_masked": True, "max_training_tokens": 2048,
                    "trainable_parameters":trainable,"total_parameters":all_parameters,
                    "adapter_sha256_before":before_hash,"adapter_sha256_after":after_hash,
                    "adapter_parameter_l2_changes":changes,"baseline_validation_loss":baseline_val,
                    "best_validation_loss":best_loss,"history":history,
                    "cache_equivalence_absolute_error":abs(full_loss-cached),
                    "versions":{key:importlib.metadata.version(key) for key in ("torch","transformers","peft","bitsandbytes","accelerate")}}
        write_json(self.output/"training-report.json",metadata)
        self.tokenizer.save_pretrained(self.output/"tokenizer")
        self.emit("training-completed", optimizer_steps=self.train_steps, adapter_sha256=after_hash)
        del optimizer, params, before, selected, layers
        self.model = None
        gc.collect()
        adapter_file = self.output/"adapter/adapter_model.safetensors"
        metadata["adapter_file_sha256"] = hashlib.sha256(adapter_file.read_bytes()).hexdigest()
        write_json(self.output/"training-report.json",metadata)
        self.emit("complete", actual_weight_training=True, optimizer_steps=self.train_steps, best_validation_loss=best_loss, initial_validation_loss=baseline_val)



if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr,"reconfigure"): sys.stderr.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser();parser.add_argument("--model",choices=["0.6b","2.4b"],required=True)
    parser.add_argument("--epochs",type=int,default=2)
    args=parser.parse_args();run=Run(args.model,args.epochs)
    try:
        run.run()
    except BaseException as error:
        run.emit("failed",error=str(error),traceback=traceback.format_exc())
        raise
