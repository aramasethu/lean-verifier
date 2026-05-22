# lean-verifier

A self improving Lean 4 theorem prover running end to end.

## 1. Objective

`lean-verifier` is a self imporving theorem proving loop, inspired by Deepseek prover, shrunk down to run on a laptop.

This is structured in a way that, a small model is asked to generate proofs (4 attempts). Then it goes through a verifier. The correct proofs are used to train the model, thus constructing a self improving loop. 

## 3. How the Setup Works

The system is a five stage loop driven by an orchestrator. Work flows through Redis queues; artifacts (attempts, successes, trained adapters) are stored in MinIO.

```
                  ┌──────────────────────────────────────┐
                  │  Orchestrator (run_iteration.py)       │
                  │  push problems → wait → metrics → train│
                  └───────────────┬────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
   ┌────▼─────┐   inference   ┌───▼──────┐   verify    ┌────▼─────┐
   │  Redis    │  _queue       │ Inference │  _queue     │ Verifier │
   │  queues   ├──────────────►│  pool     ├────────────►│  pool    │
   │           │               │ (1 pod,   │             │ (1–5 pods│
   │           │◄──────────────┤  Qwen)    │             │  KEDA)   │
   └───────────┘  results      └───────────┘             └────┬─────┘
        ▲                                                     │
        │                                                     │ successes
   ┌────┴──────┐                                         ┌────▼─────┐
   │  Training  │◄────────────  reads successes/  ───────│  MinIO   │
   │  PyTorchJob├──────────────  writes adapter/   ──────►│  storage │
   └────────────┘                                         └──────────┘
```

1. **Problem injection.** The orchestrator clears the queues and pushes problem statements (`{problem_id, statement}`) onto the Redis `inference_queue`.

2. **Inference** (`inference/inference_worker.py`). A worker pops a problem, builds a Lean prompt (`import Mathlib\n\ntheorem … := by`), generates N=4 candidate proofs with Qwen, and pushes each onto the `verify_queue`.

3. **Verification** (`verifier/verifier_worker.py`). Verifier pods pop attempts and run `lake env lean` against the pinned Mathlib build (30s timeout). Every attempt is recorded to MinIO under `attempts/`; successful proofs are also written to `successes/`. KEDA scales this pool 1→5 based on queue depth.

4. **Training** (`training/train.py`). Launched as a Kubeflow `PyTorchJob`. It reads all verified proofs from MinIO `successes/`, builds an SFT dataset, attaches a rank-8 LoRA adapter to the base model, fine-tunes for one epoch, and uploads the adapter (~10 MB) back to MinIO under `adapters/adapter-v{N}/`.

5. **Orchestration** (`orchestrator/run_iteration.py`). Chains the above into one command: pushes problems, polls `verify_results`, computes pass@k, then launches training.

**MinIO layout:**

```
proofs/
  attempts/{problem_id}/{hash}.json     every attempt (pass or fail)
  successes/{problem_id}/{hash}.json    verified-correct proofs only
  adapters/adapter-v{N}/                trained LoRA weights
```

The repo is organized by workload, each with its own Dockerfile and K8s manifest: `infra/` (Redis, MinIO, KEDA), `verifier/`, `inference/`, `training/`, and `orchestrator/`. Cluster config lives in `kind/cluster.yaml`.

## 4. Initial Results

Measured on a local `kind` cluster (Apple Silicon, CPU-only)

**Verifier pool**
- Mathlib cache: 100% hit (8,414/8,414 oleans) on ARM64.
- Functional test (10 mixed proofs): completed in **14s**, 5/5 expected passes verified correctly.
- Autoscaling (300 trivial proofs): pool scaled **1→4 pods at t=12s, 4→5 at t=26s**, queue drained by t=32s, roughly a 3.5–5× throughput gain.

**Inference pool**
- Qwen-0.5B cold-start: ~11s.
- End-to-end demo (3 problems × 4 attempts = 12 verifications): **170s**.
- Pass rate: 0/12, expected since the base Qwen model has never seen Lean. Failures were near-misses (unknown identifiers, Lean 3 syntax), which is exactly the signal expert iteration is meant to improve.
- Inference (~50s/problem on CPU) is the bottleneck; verification (~10s for 4 attempts) is not.

**Training (single LoRA iteration)**
- Data: 305 verified proofs.
- LoRA: rank 8, **1.08M trainable params (0.22% of the model)**.
- Wall clock: **357s (~6 min)** for 1 epoch on CPU.
- Loss: **3.99 → 0.95**.
- Token accuracy: **34% → 79%**.
- Output adapter: ~10 MB safetensors.


---

> **Scaling to production:** inference swaps to vLLM + GPU; the base model swaps to a larger prover (e.g. DeepSeek-Prover); the `PyTorchJob` moves from single-node to multi-node FSDP; MinIO becomes real S3; Redis can be replaced with a sharded queue (Pulsar/NATS) for large verifier fleets.
