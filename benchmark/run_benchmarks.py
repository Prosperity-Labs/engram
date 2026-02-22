#!/usr/bin/env python3
"""Engram Benchmark Runner — prints scorecard of all benchmarks."""

import subprocess
import sys
import re
from pathlib import Path


BENCHMARKS = [
    {
        "name": "Token Savings",
        "file": "tests/test_benchmark_tokens.py",
        "target": ">50%",
        "metric": "Savings",
    },
    {
        "name": "Artifact Completeness",
        "file": "tests/test_benchmark_artifacts.py",
        "target": ">80%",
        "metric": "Completeness",
    },
    {
        "name": "Search Precision",
        "file": "tests/test_benchmark_search.py",
        "target": ">70%",
        "metric": "precision",
    },
    {
        "name": "Context Recovery",
        "file": "tests/test_benchmark_recovery.py",
        "target": ">60%",
        "metric": "Recovery rate",
    },
]


def run_benchmark(bench: dict) -> dict:
    """Run a single benchmark and extract score from output."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", bench["file"], "-v", "-s", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    output = result.stdout + result.stderr
    passed = result.returncode == 0

    # Extract percentage from output
    score = None
    for line in output.split("\n"):
        if bench["metric"] in line and "%" in line:
            match = re.search(r"(\d+)%", line)
            if match:
                score = int(match.group(1))
                break

    return {
        "name": bench["name"],
        "target": bench["target"],
        "score": f"{score}%" if score is not None else "N/A",
        "passed": passed,
        "output": output,
    }


def main():
    print("=" * 60)
    print("  Engram Benchmark Scorecard")
    print("=" * 60)
    print()

    results = []
    for bench in BENCHMARKS:
        print(f"Running: {bench['name']}...", end=" ", flush=True)
        result = run_benchmark(bench)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} ({result['score']})")

    print()
    print("-" * 60)
    print(f"{'Benchmark':<25} {'Score':<10} {'Target':<10} {'Status':<10}")
    print("-" * 60)

    total_pass = 0
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        if r["passed"]:
            total_pass += 1
        print(f"{r['name']:<25} {r['score']:<10} {r['target']:<10} {status:<10}")

    print("-" * 60)
    print(f"Overall: {total_pass}/{len(results)} benchmarks passing")
    print()

    if total_pass < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
