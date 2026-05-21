import argparse
import json
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379

INFERENCE_QUEUE = "inference_queue"
VERIFY_QUEUE = "verify_queue"
RESULT_QUEUE = "verify_results"

ATTEMPTS_PER_PROBLEM = 4

PROBLEMS = [
    {"problem_id": "one_plus_one", "statement": "1 + 1 = 2"},
    {"problem_id": "true_is_true", "statement": "True"},
    {"problem_id": "nat_self", "statement": "(5 : Nat) = 5"},
]

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTORCH_JOB_YAML = REPO_ROOT / "training" / "pytorch-job.yaml"


def push_problems(r: redis.Redis) -> int:
    r.delete(INFERENCE_QUEUE, VERIFY_QUEUE, RESULT_QUEUE)
    for p in PROBLEMS:
        r.lpush(INFERENCE_QUEUE, json.dumps(p))
    expected = len(PROBLEMS) * ATTEMPTS_PER_PROBLEM
    print(f"[push] {len(PROBLEMS)} problems → inference_queue (expecting {expected} attempts)")
    return expected


def wait_for_results(r: redis.Redis, expected: int, timeout: int) -> bool:
    print(f"[wait] polling {RESULT_QUEUE}, timeout={timeout}s")
    start = time.monotonic()
    while True:
        n = r.llen(RESULT_QUEUE)
        elapsed = int(time.monotonic() - start)
        iq = r.llen(INFERENCE_QUEUE)
        vq = r.llen(VERIFY_QUEUE)
        print(f"  t={elapsed:3d}s | inference={iq} verify={vq} results={n}/{expected}")
        if n >= expected:
            print(f"[wait] all {expected} results in after {elapsed}s")
            return True
        if elapsed >= timeout:
            print(f"[wait] TIMEOUT at {elapsed}s — got {n}/{expected}")
            return False
        time.sleep(15)


def compute_pass_at_k(r: redis.Redis) -> tuple[float, dict]:
    raw = r.lrange(RESULT_QUEUE, 0, -1)
    results = [json.loads(item) for item in raw]
    by_problem: dict[str, list[bool]] = defaultdict(list)
    for item in results:
        orig = item["problem_id"].rsplit("_attempt_", 1)[0]
        by_problem[orig].append(item["success"])

    print(f"\n[pass@k] {len(by_problem)} problems × {ATTEMPTS_PER_PROBLEM} attempts:")
    n_solved = 0
    for problem, successes in sorted(by_problem.items()):
        k = len(successes)
        n_pass = sum(successes)
        mark = "PASS" if n_pass > 0 else "FAIL"
        if n_pass > 0:
            n_solved += 1
        print(f"  [{mark}] {problem:20s}  {n_pass}/{k}")
    rate = n_solved / len(by_problem) if by_problem else 0.0
    print(f"  → pass@{ATTEMPTS_PER_PROBLEM} = {n_solved}/{len(by_problem)} = {rate:.1%}")
    return rate, dict(by_problem)


def launch_training(version: int) -> bool:
    job_name = f"train-v{version}"
    pod_name = f"{job_name}-master-0"
    print(f"\n[train] launching PyTorchJob {job_name}")
    subprocess.run(
        ["kubectl", "delete", "pytorchjob", job_name, "--ignore-not-found"],
        capture_output=True,
    )
    subprocess.run(
        ["kubectl", "apply", "-f", str(PYTORCH_JOB_YAML)],
        check=True,
    )
    print(f"[train] applied; polling pod {pod_name}")
    start = time.monotonic()
    while True:
        out = subprocess.run(
            ["kubectl", "get", "pod", pod_name, "-o", "jsonpath={.status.phase}"],
            capture_output=True, text=True,
        )
        phase = out.stdout.strip() or "Pending"
        elapsed = int(time.monotonic() - start)
        print(f"  t={elapsed:4d}s | phase={phase}")
        if phase == "Succeeded":
            print(f"[train] complete in {elapsed}s — adapter saved to MinIO adapters/adapter-v{version}/")
            return True
        if phase == "Failed":
            print("[train] FAILED — pod logs:")
            subprocess.run(["kubectl", "logs", pod_name, "--tail=30"])
            return False
        if elapsed >= 1800:
            print("[train] timeout at 30min")
            return False
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one expert-iteration cycle.")
    parser.add_argument("--no-train", action="store_true", help="skip the training step")
    parser.add_argument("--version", type=int, default=1, help="adapter version to produce")
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for verify_results")
    args = parser.parse_args()

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    print("=" * 60)
    print(f"EXPERT-ITERATION CYCLE — adapter v{args.version}")
    print("=" * 60)

    expected = push_problems(r)
    if not wait_for_results(r, expected, args.timeout):
        raise SystemExit(1)

    rate, _ = compute_pass_at_k(r)

    if args.no_train:
        print(f"\n[done] pass@{ATTEMPTS_PER_PROBLEM} = {rate:.1%} (training skipped)")
        return

    ok = launch_training(args.version)
    print()
    print("=" * 60)
    if ok:
        print(f"ITERATION COMPLETE — pass@{ATTEMPTS_PER_PROBLEM}={rate:.1%}, adapter v{args.version} ready")
    else:
        print(f"ITERATION FAILED at training — pass@{ATTEMPTS_PER_PROBLEM}={rate:.1%}")
    print("=" * 60)


if __name__ == "__main__":
    main()
