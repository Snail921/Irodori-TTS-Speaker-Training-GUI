"""GUI-owned inference worker. Only its child process imports the GPU runtime."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from speaker_training_job_runner import atomic_json, now_text


class TestWorker:
    def __init__(self, python: str, script: Path, irodori_root: Path):
        self.python = python
        self.script = script
        self.irodori_root = irodori_root
        self.process = None
        self.thread = None

    def stop(self):
        process = self.process
        if process is not None:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
            if self.thread is not None:
                self.thread.join(timeout=15)
                if self.thread.is_alive():
                    raise RuntimeError("Test worker monitor did not stop")
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        self.process = None
        self.thread = None

    def submit(self, command, status_path: Path, log_path: Path, speaker: str):
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=1)
            if self.thread.is_alive():
                raise RuntimeError("A test is already running")
        if self.process is None or self.process.poll() is not None:
            self.stop()
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            self.process = subprocess.Popen(
                [self.python, str(self.script), "--irodori-root", str(self.irodori_root)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", bufsize=1, env=env,
                cwd=str(self.script.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        process = self.process
        status = dict(kind="test", speaker=speaker, state="running", pid=process.pid,
                      started_at=now_text(), finished_at=None, exit_code=None,
                      command=command, log=str(log_path))
        atomic_json(status_path, status)
        request = dict(command=command, status=str(status_path), log=str(log_path), payload=status)

        def monitor():
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                while True:
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError("Test worker exited before completing the request")
                    if line.startswith("IRODORI_TEST_DONE "):
                        break
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(line)
            except Exception as exc:
                status.update(state="failed", exit_code=-1, finished_at=now_text(), error=str(exc))
                # An intentional cancellation is already marked stopped by the GUI.
                try:
                    current = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    current = {}
                if current.get("state") != "stopped":
                    atomic_json(status_path, status)
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"[worker] {exc}\n")

        self.thread = threading.Thread(target=monitor, daemon=True)
        self.thread.start()
        return process.pid


class RuntimeSession:
    def __init__(self, backend):
        self.backend = backend
        self.key = None
        self.runtime = None

    def synthesize(self, command):
        parser = argparse.ArgumentParser()
        for name in ("checkpoint", "ref-embed", "text", "output-wav", "model-device",
                     "codec-device", "model-precision", "codec-precision"):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--caption")
        parser.add_argument("--num-steps", type=int, default=40)
        parser.add_argument("--seed", type=int, default=1234)
        args = parser.parse_args(command[2:])
        key = self.backend.RuntimeKey(checkpoint=args.checkpoint, model_device=args.model_device,
                                      codec_device=args.codec_device, model_precision=args.model_precision,
                                      codec_precision=args.codec_precision)
        started = time.perf_counter()
        if self.key != key:
            # Free the previous model before loading another, avoiding double VRAM use.
            if self.runtime is not None:
                self.runtime.unload()
            self.runtime = None
            self.key = None
            print("[worker] Loading base model and codec", flush=True)
            self.runtime = self.backend.InferenceRuntime.from_key(key)
            self.key = key
        else:
            print("[worker] Reusing loaded base model and codec", flush=True)
        loaded = time.perf_counter()
        result = self.runtime.synthesize(self.backend.SamplingRequest(
            text=args.text, caption=args.caption, ref_embed=args.ref_embed,
            num_steps=args.num_steps, seed=args.seed,
        ))
        self.backend.save_wav(args.output_wav, result.audio, result.sample_rate)
        print(f"[worker] load={loaded-started:.3f}s generation_and_save={time.perf_counter()-loaded:.3f}s", flush=True)
        print(f"Saved: {args.output_wav} / seed={result.used_seed}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--irodori-root", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.irodori_root).resolve()))
    session = None
    for line in sys.stdin:
        request = json.loads(line)
        payload = request["payload"]
        with Path(request["log"]).open("a", encoding="utf-8", buffering=1) as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    if session is None:
                        from irodori_tts import inference_runtime
                        session = RuntimeSession(inference_runtime)
                    session.synthesize(request["command"])
                    payload.update(state="completed", exit_code=0)
                except BaseException as exc:
                    traceback.print_exc()
                    payload.update(state="failed", exit_code=1, error=f"{type(exc).__name__}: {exc}")
                payload["finished_at"] = now_text()
                atomic_json(Path(request["status"]), payload)
        print("IRODORI_TEST_DONE " + str(payload["exit_code"]), flush=True)
    # Parent owns stdin; GUI exit closes the pipe and terminates an idle worker.
    if session is not None and session.runtime is not None:
        session.runtime.unload()


if __name__ == "__main__":
    main()
