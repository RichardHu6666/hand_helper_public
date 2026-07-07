#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path("/root/sign_cloud_v1")
SESSION_ID = "019f1d62-54ab-7e21-bb0f-88484f9972f1"
PROMPT_FILE = PROJECT / "codex_resume_prompt.txt"
LOG_DIR = PROJECT / "codex_resume_logs"
DEFAULT_DELAYS_SECONDS = [2 * 60 * 60, 7 * 60 * 60]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_log(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{now()}] {message}\n")


def load_prompt() -> str:
    if not PROMPT_FILE.exists():
        PROMPT_FILE.write_text(
            "缁х画杩欎竴瀵硅瘽鐨?active goal銆傜户缁湭瀹屾垚宸ヤ綔銆?,
            encoding="utf-8",
        )
    return PROMPT_FILE.read_text(encoding="utf-8")


def codex_command(session_id: str, prompt: str, sandbox: str, approval: str) -> list[str]:
    return [
        "codex",
        "resume",
        "--sandbox",
        sandbox,
        "--ask-for-approval",
        approval,
        "--no-alt-screen",
        session_id,
        prompt,
    ]


def run_once(label: str, session_id: str, sandbox: str, approval: str, log_file: Path) -> int:
    prompt = load_prompt()
    cmd = codex_command(session_id, prompt, sandbox, approval)
    transcript = LOG_DIR / f"codex_resume_{label}_{datetime.now():%Y%m%d_%H%M%S}.typescript"
    command_string = " ".join(shlex.quote(part) for part in cmd)
    script_cmd = ["script", "-q", "-c", command_string, str(transcript)]

    write_log(log_file, f"starting label={label} session_id={session_id}")
    write_log(log_file, f"command={command_string}")
    write_log(log_file, f"transcript={transcript}")

    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    proc = subprocess.run(script_cmd, cwd=PROJECT, env=env)
    write_log(log_file, f"finished label={label} returncode={proc.returncode}")
    return proc.returncode


def run_with_retries(label: str, args: argparse.Namespace, log_file: Path) -> None:
    for attempt in range(1, args.max_attempts + 1):
        write_log(log_file, f"attempt={attempt}/{args.max_attempts} label={label}")
        rc = run_once(label, args.session_id, args.sandbox, args.approval, log_file)
        if rc == 0:
            write_log(log_file, f"success label={label}")
            return
        if attempt < args.max_attempts:
            write_log(log_file, f"failed label={label}; sleeping retry_seconds={args.retry_seconds}")
            time.sleep(args.retry_seconds)
    write_log(log_file, f"failed after all retries label={label}")


def parse_delays(raw: str | None) -> list[int]:
    if not raw:
        return DEFAULT_DELAYS_SECONDS
    delays = []
    for part in raw.split(","):
        part = part.strip()
        if part.endswith("h"):
            delays.append(int(float(part[:-1]) * 3600))
        elif part.endswith("m"):
            delays.append(int(float(part[:-1]) * 60))
        else:
            delays.append(int(float(part)))
    return delays


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume a fixed Codex CLI conversation after scheduled delays.")
    parser.add_argument("--session-id", default=SESSION_ID)
    parser.add_argument("--delays", default=None, help="Comma-separated delays: e.g. 2h,7h or 7200,25200")
    parser.add_argument("--retry-seconds", type=int, default=600)
    parser.add_argument("--max-attempts", type=int, default=36)
    parser.add_argument("--sandbox", default="workspace-write", choices=["read-only", "workspace-write", "danger-full-access"])
    parser.add_argument("--approval", default="never", choices=["untrusted", "on-request", "on-failure", "never"])
    parser.add_argument("--run-now", action="store_true", help="Run once immediately, then exit.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"scheduler_{datetime.now():%Y%m%d_%H%M%S}.log"
    delays = [0] if args.run_now else parse_delays(args.delays)

    write_log(log_file, f"scheduler started pid={os.getpid()} session_id={args.session_id} delays={delays}")
    write_log(log_file, f"prompt_file={PROMPT_FILE}")

    if args.dry_run:
        prompt = load_prompt()
        cmd = codex_command(args.session_id, prompt, args.sandbox, args.approval)
        print("Would run:")
        print(" ".join(shlex.quote(part) for part in cmd))
        print(f"Log file would be: {log_file}")
        return 0

    start = time.monotonic()
    for index, delay in enumerate(delays, start=1):
        target = start + delay
        sleep_seconds = max(0.0, target - time.monotonic())
        write_log(log_file, f"waiting run={index} delay_seconds={delay} sleep_seconds={sleep_seconds:.0f}")
        if sleep_seconds:
            time.sleep(sleep_seconds)
        run_with_retries(f"run{index}", args, log_file)

    write_log(log_file, "scheduler finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

