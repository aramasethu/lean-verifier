import json
import os
import socket
import time

import redis
import torch
from torch.profiler import ProfilerActivity, profile, record_function
from transformers import AutoModelForCausalLM, AutoTokenizer

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
INFERENCE_QUEUE = "inference_queue"
VERIFY_QUEUE = "verify_queue"

MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")
N_ATTEMPTS = int(os.environ.get("N_ATTEMPTS", "4"))
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "64"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.8"))
PROFILE_INFERENCE = os.environ.get("PROFILE_INFERENCE", "0") == "1"
TRACE_PATH = "/tmp/inference-trace.json"

WORKER_ID = os.environ.get("HOSTNAME", socket.gethostname())


def build_prompt(problem_id: str, statement: str) -> str:
    return (
        "import Mathlib\n\n"
        f"-- {problem_id}\n"
        f"theorem {problem_id} : {statement} := by\n"
    )


def main() -> None:
    print(f"[{WORKER_ID}] loading {MODEL_NAME}...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, dtype=torch.float32)
    model.eval()
    print(f"[{WORKER_ID}] model ready", flush=True)

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    print(f"[{WORKER_ID}] inference worker listening on {INFERENCE_QUEUE}", flush=True)
    if PROFILE_INFERENCE:
        print(f"[{WORKER_ID}] PROFILE_INFERENCE=1 — first generate() will be traced", flush=True)

    profiled = False
    while True:
        item = r.brpop(INFERENCE_QUEUE, timeout=10)
        if item is None:
            continue
        _, payload = item
        try:
            job = json.loads(payload)
            problem_id = job["problem_id"]
            statement = job["statement"]
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[{WORKER_ID}] skipping malformed job ({e}): {payload[:100]}", flush=True)
            continue

        prompt = build_prompt(problem_id, statement)
        print(f"[{WORKER_ID}] generating {N_ATTEMPTS} attempts for {problem_id}", flush=True)
        start = time.monotonic()

        inputs = tokenizer(prompt, return_tensors="pt")

        def _generate():
            with torch.no_grad():
                return model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    do_sample=True,
                    temperature=TEMPERATURE,
                    num_return_sequences=N_ATTEMPTS,
                    pad_token_id=tokenizer.eos_token_id,
                )

        if PROFILE_INFERENCE and not profiled:
            with profile(
                activities=[ProfilerActivity.CPU],
                record_shapes=True,
                profile_memory=True,
            ) as prof:
                with record_function("generate"):
                    outputs = _generate()
            profiled = True
            print(f"\n[{WORKER_ID}] === PROFILER SUMMARY (top 20 by cpu_time_total) ===", flush=True)
            print(prof.key_averages().table(sort_by="cpu_time_total", row_limit=20), flush=True)
            prof.export_chrome_trace(TRACE_PATH)
            print(f"[{WORKER_ID}] chrome trace saved to {TRACE_PATH}\n", flush=True)
        else:
            outputs = _generate()

        duration = time.monotonic() - start

        for i, output_ids in enumerate(outputs):
            full_text = tokenizer.decode(output_ids, skip_special_tokens=True)
            r.lpush(
                VERIFY_QUEUE,
                json.dumps({
                    "problem_id": f"{problem_id}_attempt_{i}",
                    "proof_str": full_text,
                }),
            )

        print(f"[{WORKER_ID}]   -> {N_ATTEMPTS} attempts in {duration:.1f}s", flush=True)


if __name__ == "__main__":
    main()
