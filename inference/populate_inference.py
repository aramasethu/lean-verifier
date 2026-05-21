import json
import sys

import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379
INFERENCE_QUEUE = "inference_queue"
VERIFY_QUEUE = "verify_queue"
RESULT_QUEUE = "verify_results"

PROBLEMS = [
    {"problem_id": "one_plus_one", "statement": "1 + 1 = 2"},
    {"problem_id": "true_is_true", "statement": "True"},
    {"problem_id": "nat_self", "statement": "(5 : Nat) = 5"},
]


def main() -> None:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    if "--clear" in sys.argv:
        deleted = r.delete(INFERENCE_QUEUE, VERIFY_QUEUE, RESULT_QUEUE)
        print(f"cleared {deleted} key(s)")

    for p in PROBLEMS:
        r.lpush(INFERENCE_QUEUE, json.dumps(p))

    print(f"pushed {len(PROBLEMS)} problems to '{INFERENCE_QUEUE}'")
    print(f"  inference queue: {r.llen(INFERENCE_QUEUE)}")
    print(f"  verify queue:    {r.llen(VERIFY_QUEUE)}")
    print(f"  results queue:   {r.llen(RESULT_QUEUE)}")


if __name__ == "__main__":
    main()
