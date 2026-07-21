from __future__ import annotations

import argparse
import statistics
import subprocess
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cli")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--discard", type=int, default=2)
    args = parser.parse_args()
    timings = []
    for _ in range(args.runs):
        start = time.perf_counter()
        subprocess.run([args.cli, "--help"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        timings.append(time.perf_counter() - start)
    kept = timings[args.discard :]
    print(f"runs={args.runs} discard={args.discard} mean={statistics.mean(kept):.6f}s min={min(kept):.6f}s max={max(kept):.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
