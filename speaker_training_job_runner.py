#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(8):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 7:
                break
            time.sleep(0.05 * (attempt + 1))
    # exFAT on Windows can transiently reject replacement while the GUI polls the file.
    # A direct UTF-8 write is safe here because malformed intermediate reads are retried by the GUI.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temp.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Detached job runner for Speaker Training GUI")
    parser.add_argument("--status", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--speaker", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("No child command was supplied")

    status_path = Path(args.status).resolve()
    log_path = Path(args.log).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": args.kind,
        "speaker": args.speaker,
        "state": "running",
        "pid": os.getpid(),
        "child_pid": None,
        "started_at": now_text(),
        "finished_at": None,
        "exit_code": None,
        "command": command,
        "log": str(log_path),
    }
    atomic_json(status_path, payload)

    try:
        with log_path.open("a", encoding="utf-8", errors="replace", buffering=1) as log:
            log.write(f"\n[{now_text()}] START {args.kind} / {args.speaker}\n")
            log.write("COMMAND: " + subprocess.list2cmdline(command) + "\n\n")
            child_env = os.environ.copy()
            child_env["PYTHONUTF8"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            child = subprocess.Popen(
                command,
                cwd=str(Path(args.cwd).resolve()),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=child_env,
            )
            payload["child_pid"] = child.pid
            atomic_json(status_path, payload)
            exit_code = child.wait()
            log.write(f"\n[{now_text()}] END exit_code={exit_code}\n")
        payload["state"] = "completed" if exit_code == 0 else "failed"
        payload["exit_code"] = int(exit_code)
        payload["finished_at"] = now_text()
        atomic_json(status_path, payload)
        return int(exit_code)
    except BaseException as exc:
        payload["state"] = "failed"
        payload["exit_code"] = -1
        payload["finished_at"] = now_text()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        atomic_json(status_path, payload)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
