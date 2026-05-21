import io

import boto3
import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379

MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minio"
MINIO_SECRET_KEY = "minio12345"
MINIO_BUCKET = "proofs"


def test_redis() -> None:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.delete("smoke_queue")
    r.lpush("smoke_queue", "problem-1", "problem-2", "problem-3")
    assert r.llen("smoke_queue") == 3
    assert r.rpop("smoke_queue") == "problem-1"
    assert r.rpop("smoke_queue") == "problem-2"
    r.delete("smoke_queue")
    print("Redis: LPUSH / RPOP / LLEN / DELETE all OK")


def test_minio() -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if MINIO_BUCKET not in existing:
        s3.create_bucket(Bucket=MINIO_BUCKET)
        print(f"MinIO: created bucket '{MINIO_BUCKET}'")
    else:
        print(f"MinIO: bucket '{MINIO_BUCKET}' already exists")

    payload = b"theorem t : 1 + 1 = 2 := by rfl"
    s3.upload_fileobj(io.BytesIO(payload), MINIO_BUCKET, "smoke/test.lean")
    buf = io.BytesIO()
    s3.download_fileobj(MINIO_BUCKET, "smoke/test.lean", buf)
    assert buf.getvalue() == payload
    s3.delete_object(Bucket=MINIO_BUCKET, Key="smoke/test.lean")
    print("MinIO: upload / download / delete round-trip OK")


if __name__ == "__main__":
    test_redis()
    test_minio()
    print("Phase 1 infra smoke test passed.")
