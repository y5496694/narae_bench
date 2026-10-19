"""Finish both real SFT jobs, export their changed tensors, then run frozen tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(r"D:\Codex\training\narae-sft-20261019/venv/Scripts/python.exe")
for key in ["TEMP", "TMP"]: os.environ[key] = str(ROOT/"tmp")
os.environ["HF_HOME"] = str(ROOT/"cache/huggingface")
os.environ["HF_MODULES_CACHE"] = str(ROOT/"cache/modules")
os.environ["PYTHONPYCACHEPREFIX"] = str(ROOT/"cache/pycache")


def command(args, log):
    with (ROOT/"logs"/log).open("wb") as output:
        result = subprocess.run([str(PYTHON), "-X", "utf8", *map(str,args)], stdout=output, stderr=output,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    if result.returncode: raise RuntimeError(f"Step failed: {log}")


def main():
    status = ROOT/"outputs/Narae-0.6B-Tool-LoRA-v2/status.json"
    while True:
        try: value=json.loads(status.read_text(encoding="utf-8"))
        except (OSError, ValueError): value={}
        if value.get("stage") == "failed": raise RuntimeError("0.6B training failed")
        if value.get("stage") == "complete": break
        time.sleep(5)
    command([ROOT/"scripts/train_lora_sdpa.py", "--model", "2.4b", "--epochs", "2"], "train-2.4b.log")
    for tag, name in [("0.6b","Narae-0.6B-Tool-LoRA-v2"),("2.4b","EXAONE-Narae-2.4B-Tool-LoRA-v2")]:
        source=json.loads((ROOT/"models"/(tag+"-source.json")).read_text())
        args=[Path(r"D:\Codex\tools\llama.cpp/convert_lora_to_gguf.py"), "--base", source["path"], "--outtype", "f32",
              "--outfile", ROOT/"exports"/(name+"-f32.gguf"), ROOT/"outputs"/name/"adapter"]
        if tag == "2.4b": args += ["--trust-remote-code"]
        command(args, "convert-"+tag+".log")
    command([ROOT/"exports/verify_exports.py"], "verify-exports.log")
    command([ROOT/"scripts/evaluate_native.py"], "evaluate-native.log")
    print("Both trained models and frozen evaluations completed", flush=True)


if __name__ == "__main__": main()
