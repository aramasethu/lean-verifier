import json
import sys

import redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379
VERIFY_QUEUE = "verify_queue"
RESULT_QUEUE = "verify_results"

ATTEMPTS = [
    # expected PASS
    {
        "problem_id": "rfl_easy",
        "proof_str": "theorem t : 1 + 1 = 2 := by rfl",
    },
    {
        "problem_id": "nat_add_zero",
        "proof_str": "theorem t (n : Nat) : n + 0 = n := Nat.add_zero n",
    },
    {
        "problem_id": "true_intro",
        "proof_str": "theorem t : True := True.intro",
    },
    {
        "problem_id": "ring_comm",
        "proof_str": "import Mathlib.Tactic.Ring\ntheorem t (a b : Nat) : a + b = b + a := by ring",
    },
    {
        "problem_id": "simp_add_zero",
        "proof_str": "import Mathlib.Tactic\ntheorem t (n : Nat) : n + 0 = n := by simp",
    },
    # expected FAIL
    {
        "problem_id": "wrong_eq",
        "proof_str": "theorem t : 1 + 1 = 3 := by rfl",
    },
    {
        "problem_id": "unknown_tactic",
        "proof_str": "theorem t : True := by definitely_not_a_real_tactic_12345",
    },
    {
        "problem_id": "syntax_error",
        "proof_str": "theorem t : 1 + 1 = 2 := by rfl ###",
    },
    {
        "problem_id": "omega_false",
        "proof_str": "theorem t : 2 + 2 = 5 := by omega",
    },
    {
        "problem_id": "missing_import",
        "proof_str": "theorem t : (1 : Real) > 0 := by norm_num",
    },
]


def main() -> None:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    if "--clear" in sys.argv:
        deleted = r.delete(VERIFY_QUEUE, RESULT_QUEUE)
        print(f"cleared {deleted} key(s)")

    for a in ATTEMPTS:
        r.lpush(VERIFY_QUEUE, json.dumps(a))

    print(f"pushed {len(ATTEMPTS)} attempts to '{VERIFY_QUEUE}'")
    print(f"  queue depth now: {r.llen(VERIFY_QUEUE)}")
    print(f"  result queue:    {r.llen(RESULT_QUEUE)} items pending")


if __name__ == "__main__":
    main()
