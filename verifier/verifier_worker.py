import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import boto3
import redis

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
VERIFY_QUEUE = "verify_queue"
RESULT_QUEUE = "verify_results"

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minio12345")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "proofs")

MATHLIB_DIR = "/opt/mathlib4"
LEAN_TIMEOUT_S = 30

WORKER_ID = os.environ.get("HOSTNAME", socket.gethostname())


def verify(proof_str: str) -> tuple[bool, str, float]:
    proof_hash = hashlib.sha256(proof_str.encode()).hexdigest()[:12]
    tmp_path = Path(f"/tmp/verifier_{proof_hash}.lean")
    tmp_path.write_text(proof_str)
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["lake", "env", "lean", str(tmp_path)],
            cwd=MATHLIB_DIR,
            capture_output=True,
            text=True,
            timeout=LEAN_TIMEOUT_S,
        )
        duration = time.monotonic() - start
        if result.returncode == 0:
            return True, "", duration
        return False, (result.stderr or result.stdout)[:4096], duration
    except subprocess.TimeoutExpired:
        return False, "timeout", LEAN_TIMEOUT_S
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )
    print(f"[{WORKER_ID}] verifier ready, listening on {VERIFY_QUEUE}", flush=True)

    while True:
        item = r.brpop(VERIFY_QUEUE, timeout=10)
        if item is None:
            continue
        _, payload = item
        try:
            job = json.loads(payload)
            problem_id = job["problem_id"]
            proof_str = job["proof_str"]
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[{WORKER_ID}] skipping malformed job ({e}): {payload[:100]}", flush=True)
            continue

        proof_hash = hashlib.sha256(proof_str.encode()).hexdigest()[:12]
        print(f"[{WORKER_ID}] verifying {problem_id} ({proof_hash})", flush=True)
        success, error, duration = verify(proof_str)
        print(
            f"[{WORKER_ID}]   -> {'PASS' if success else 'FAIL'} in {duration:.1f}s",
            flush=True,
        )

        result = {
            "problem_id": problem_id,
            "proof_hash": proof_hash,
            "success": success,
            "error": error,
            "duration_s": round(duration, 2),
            "worker": WORKER_ID,
        }
        r.lpush(RESULT_QUEUE, json.dumps(result))

        attempt_record = {
            "problem_id": problem_id,
            "proof_str": proof_str,
            "success": success,
            "error": error,
            "duration_s": round(duration, 2),
            "worker": WORKER_ID,
        }
        s3.put_object(
            Bucket=MINIO_BUCKET,
            Key=f"attempts/{problem_id}/{proof_hash}.json",
            Body=json.dumps(attempt_record),
            ContentType="application/json",
        )

        if success:
            s3.put_object(
                Bucket=MINIO_BUCKET,
                Key=f"successes/{problem_id}/{proof_hash}.json",
                Body=json.dumps({"problem_id": problem_id, "proof_str": proof_str}),
                ContentType="application/json",
            )


if __name__ == "__main__":
    main()
