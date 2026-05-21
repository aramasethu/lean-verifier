import argparse
import json

import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    if args.clear:
        deleted = r.delete("verify_queue", "verify_results")
        print(f"cleared {deleted} key(s)")

    for i in range(args.count):
        payload = {
            "problem_id": f"stress_{i:03d}",
            "proof_str": f"theorem t : {i} + 0 = {i} := by rfl",
        }
        r.lpush("verify_queue", json.dumps(payload))

    print(f"pushed {args.count} attempts; queue depth: {r.llen('verify_queue')}")


if __name__ == "__main__":
    main()
