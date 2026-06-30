#!/usr/bin/env python3
"""
Run Arena × SWE-agent across multiple SWE-bench Lite instances and report results.

Usage:
    ./benchmark.py                          # golden-patch mode across default instances
    ./benchmark.py --use-llm                # let LLM generate patches
    ./benchmark.py --no-fallback            # disable golden patch fallback (requires --use-llm)
    ./benchmark.py --instances django__django-11039 sympy__sympy-12236

The script starts a local Arena server unless one is already listening on
ARENA_ENDPOINT (default localhost:9090).
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR / "../.."
DEFAULT_ENDPOINT = "localhost:9090"
DEFAULT_INSTANCES = [
    "pallets__flask-4045",
    "django__django-11039",
    "sympy__sympy-12236",
    "scikit-learn__scikit-learn-10949",
    "pytest-dev__pytest-5103",
]


def parse_host_port(endpoint: str) -> tuple[str, int]:
    """Parse 'host:port' into (host, port)."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        endpoint = endpoint.split("://", 1)[1]
    parts = endpoint.rsplit(":", 1)
    return parts[0], int(parts[1])


def server_alive(endpoint: str) -> bool:
    host, port = parse_host_port(endpoint)
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def wait_for_server(endpoint: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server_alive(endpoint):
            return True
        time.sleep(0.5)
    return False


def start_arena_server(endpoint: str):
    """Start a local Arena server if one is not already running."""
    if server_alive(endpoint):
        print(f"Arena server already running at {endpoint}")
        return None

    print(f"Starting Arena server at {endpoint}...")
    server_log = PROJECT_ROOT / "examples" / "swe-agent" / "arena_server.log"
    proc = subprocess.Popen(
        [str(PROJECT_ROOT / "bin" / "openagora-server"), "--sandbox=docker", "--grpc", ":9090", "--http", ":9093"],
        stdout=subprocess.DEVNULL,
        stderr=open(server_log, "w", encoding="utf-8"),
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if not wait_for_server(endpoint, timeout=30.0):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise RuntimeError("Arena server failed to start within 30 seconds")
    print("Arena server started")
    return proc


def run_one(instance_id: str, use_llm: bool, no_fallback: bool, endpoint: str, first_build: bool) -> dict:
    env = os.environ.copy()
    env["SWE_INSTANCE_ID"] = instance_id
    env["ARENA_ENDPOINT"] = endpoint
    env["WRAPPER_IMAGE"] = f"openagora-swe-agent:{instance_id}"
    env["SKIP_BUILD"] = "0" if first_build else "1"

    # Prepare task.json
    print(f"[{instance_id}] Preparing task...")
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "prepare_task.py"), "--instance-id", instance_id, "--output", "task.json"],
        cwd=str(SCRIPT_DIR),
        check=True,
    )

    # run.sh reads these environment variables and injects them into task.json.
    env["USE_LLM"] = "1" if use_llm else "0"
    if use_llm:
        env.setdefault("ARENA_MODEL", "qwen2.5-coder:1.5b")
        env.setdefault("LLM_MAX_TURNS", "3")
        env.setdefault("ARENA_LLM_BACKEND", "http://localhost:11434/v1")
        if os.environ.get("USE_TOOLS", "") in ("1", "true", "yes"):
            env["USE_TOOLS"] = "1"
    if no_fallback:
        env["NO_GOLDEN_FALLBACK"] = "1"

    print(f"[{instance_id}] Running rollout (SKIP_BUILD={env['SKIP_BUILD']}, USE_LLM={env['USE_LLM']})...")
    start = time.time()

    # Stream output to terminal while also capturing it for parsing.
    log_path = SCRIPT_DIR / f"benchmark_{instance_id}.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                ["bash", str(SCRIPT_DIR / "run.sh")],
                env=env,
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            combined_lines = []
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log_file.write(line)
                combined_lines.append(line)
            proc.wait(timeout=1800)
            returncode = proc.returncode
        combined = "".join(combined_lines)
    except subprocess.TimeoutExpired:
        proc.kill()
        combined = "".join(combined_lines)
        return {
            "instance_id": instance_id,
            "use_llm": use_llm,
            "no_fallback": no_fallback,
            "status": "timeout",
            "reward": None,
            "elapsed": 1800,
            "returncode": -1,
            "error": "rollout timed out after 1800s",
            "log_tail": combined[-4000:],
        }
    elapsed = time.time() - start

    reward = None
    status = "unknown"
    trajectory_steps = None
    for line in combined.splitlines():
        m = re.search(r"Reward:\s*([\d.]+)", line)
        if m:
            try:
                reward = float(m.group(1))
            except ValueError:
                pass
        m = re.search(r"Status:\s*(\S+)", line)
        if m:
            status = m.group(1)
        m = re.search(r"Trajectory steps:\s*(\d+)", line)
        if m:
            trajectory_steps = int(m.group(1))

    # Determine fallback usage from logs.
    used_fallback = "golden fallback patch applied" in combined
    llm_succeeded = "LLM bash agent completed" in combined

    return {
        "instance_id": instance_id,
        "use_llm": use_llm,
        "no_fallback": no_fallback,
        "status": status,
        "reward": reward,
        "elapsed": elapsed,
        "returncode": returncode,
        "llm_succeeded": llm_succeeded,
        "used_fallback": used_fallback,
        "trajectory_steps": trajectory_steps,
        "log_tail": combined[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Arena × SWE-agent on SWE-bench Lite")
    parser.add_argument("--instances", nargs="+", default=DEFAULT_INSTANCES, help="Instance IDs to run")
    parser.add_argument("--use-llm", action="store_true", help="Let LLM generate patches")
    parser.add_argument("--no-fallback", action="store_true", help="Disable golden patch fallback")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Arena gRPC endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Only validate task.json generation, do not run rollouts")
    parser.add_argument("--output", default="benchmark_results.json", help="Path to write results JSON")
    args = parser.parse_args()

    if args.no_fallback and not args.use_llm:
        print("Warning: --no-fallback only makes sense with --use-llm", file=sys.stderr)

    def dry_run_one(iid: str) -> dict:
        print(f"[{iid}] Dry-run prepare_task...")
        start = time.time()
        try:
            subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "prepare_task.py"), "--instance-id", iid, "--output", "task.json"],
                cwd=str(SCRIPT_DIR),
                check=True,
                capture_output=True,
            )
            with open(SCRIPT_DIR / "task.json") as f:
                task = json.load(f)
            elapsed = time.time() - start
            return {
                "instance_id": iid,
                "status": "prepared",
                "sandbox_image": task.get("sandbox_image"),
                "test_command": task.get("test_command"),
                "fail_to_pass_count": len(task.get("FAIL_TO_PASS", [])),
                "elapsed": elapsed,
            }
        except Exception as e:
            return {"instance_id": iid, "status": "error", "error": str(e), "elapsed": time.time() - start}

    if args.dry_run:
        print("Dry-run mode: only validating task.json generation.\n")
        results = [dry_run_one(iid) for iid in args.instances]
        output_path = Path(args.output)
        output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWrote {output_path}")
        ok = sum(1 for r in results if r["status"] == "prepared")
        print(f"Summary: {ok}/{len(results)} prepared successfully")
        return 0 if ok == len(results) else 1

    server_proc = None
    try:
        server_proc = start_arena_server(args.endpoint)
        results = []
        first_build = True
        for iid in args.instances:
            print(f"\n{'=' * 60}")
            print(f"Running {iid} ...")
            try:
                r = run_one(iid, args.use_llm, args.no_fallback, args.endpoint, first_build)
                first_build = False
            except Exception as e:
                r = {
                    "instance_id": iid,
                    "use_llm": args.use_llm,
                    "no_fallback": args.no_fallback,
                    "status": "error",
                    "reward": None,
                    "elapsed": 0,
                    "error": str(e),
                }
            results.append(r)
            print(
                f"Result: status={r['status']} reward={r['reward']} "
                f"elapsed={r.get('elapsed', 0):.1f}s "
                f"llm_succeeded={r.get('llm_succeeded')} fallback={r.get('used_fallback')}"
            )

        output_path = Path(args.output)
        output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWrote {output_path}")

        # Summary
        total = len(results)
        passed = sum(1 for r in results if r.get("reward") == 1.0)
        failed = sum(1 for r in results if r.get("reward") != 1.0)
        print(f"\nSummary: {passed}/{total} passed, {failed}/{total} failed")
        return 0 if passed == total else 1
    finally:
        if server_proc is not None:
            print("Stopping Arena server...")
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()
            if server_proc.stderr is not None:
                server_proc.stderr.close()


if __name__ == "__main__":
    sys.exit(main())
