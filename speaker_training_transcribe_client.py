#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import http.client
import json
import mimetypes
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SUPPORTED_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mka",
    ".mkv",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


def atomic_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def json_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def discover_audio(source: Path) -> list[Path]:
    if source.is_file():
        if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported audio/video extension: {source.suffix}")
        return [source.resolve()]
    if not source.is_dir():
        raise FileNotFoundError(f"Input does not exist: {source}")
    return sorted(
        (path.resolve() for path in source.rglob("*") if path.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda path: str(path).casefold(),
    )


def default_output_dir(source: Path, irodori: bool) -> Path:
    if irodori and source.is_dir() and source.name.casefold() == "audio":
        return source.resolve().parent
    label = source.stem if source.is_file() else source.name
    return Path.cwd() / "output" / label


def relative_audio_path(audio: Path, source: Path) -> Path:
    if source.is_file():
        return Path(audio.name)
    return audio.relative_to(source.resolve())


def timestamp(seconds: float, *, vtt: bool = False) -> str:
    millis = max(0, round(float(seconds) * 1000.0))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def result_outputs(result: dict[str, Any]) -> tuple[str, str, str]:
    srt_blocks: list[str] = []
    vtt_blocks = ["WEBVTT", ""]
    for index, segment in enumerate(result.get("segments") or [], start=1):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        srt_blocks.append(f"{index}\n{timestamp(start)} --> {timestamp(end)}\n{text}\n")
        vtt_blocks.append(
            f"{timestamp(start, vtt=True)} --> {timestamp(end, vtt=True)}\n{text}\n"
        )
    return (
        str(result.get("text", "")).strip() + "\n",
        "\n".join(srt_blocks),
        "\n".join(vtt_blocks).rstrip() + "\n",
    )


def summarize(
    audio: Path,
    result: dict[str, Any],
    elapsed: float,
    cached: bool,
    server_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    segments = result.get("segments") or []
    logprobs = [float(item["avg_logprob"]) for item in segments if item.get("avg_logprob") is not None]
    no_speech = [
        float(item["no_speech_prob"])
        for item in segments
        if item.get("no_speech_prob") is not None
    ]
    compression = [
        float(item["compression_ratio"])
        for item in segments
        if item.get("compression_ratio") is not None
    ]
    duration = max((float(item.get("end", 0.0)) for item in segments), default=0.0)
    text = str(result.get("text", "")).strip()
    avg_logprob = sum(logprobs) / len(logprobs) if logprobs else None
    notes: list[str] = []
    if not text:
        notes.append("empty transcription")
    if avg_logprob is not None and avg_logprob < -0.8:
        notes.append("low average log probability")
    if no_speech and max(no_speech) > 0.6:
        notes.append("possible silence/no-speech segment")
    if compression and max(compression) > 2.4:
        notes.append("possible repetitive/hallucinated text")
    if server_result and server_result.get("suppressed"):
        reason = str(server_result.get("suppressed_reason", "quality check"))
        notes.append(f"server suppressed: {reason}")
    return {
        "audio": audio.as_posix(),
        "text": text,
        "language": str(result.get("language", "")),
        "duration_seconds": round(duration, 3),
        "avg_logprob": None if avg_logprob is None else round(avg_logprob, 5),
        "min_logprob": None if not logprobs else round(min(logprobs), 5),
        "max_no_speech_prob": None if not no_speech else round(max(no_speech), 5),
        "max_compression_ratio": None if not compression else round(max(compression), 5),
        "elapsed_seconds": round(elapsed, 3),
        "cached": cached,
        "status": "review" if notes else "ok",
        "notes": "; ".join(notes),
    }


def load_cached_result(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    result = payload.get("whisper_result") if isinstance(payload, dict) else None
    return result if isinstance(result, dict) else None


def write_result(
    prefix: Path,
    audio: Path,
    result: dict[str, Any],
    model_name: str,
    server_result: dict[str, Any],
) -> None:
    text, srt, vtt = result_outputs(result)
    atomic_text(prefix.with_suffix(".txt"), text)
    atomic_text(prefix.with_suffix(".srt"), srt)
    atomic_text(prefix.with_suffix(".vtt"), vtt)
    payload = {
        "source_audio": audio.as_posix(),
        "model": model_name,
        "whisper_result": result,
        "server_result": server_result,
    }
    atomic_text(prefix.with_suffix(".json"), json.dumps(payload, ensure_ascii=False, indent=2))


def existing_metadata(path: Path) -> dict[str, str]:
    preserved: dict[str, str] = {}
    if not path.is_file():
        return preserved
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        audio = str(item.get("audio", "")).strip()
        text = str(item.get("text", "")).strip()
        if audio and text:
            preserved[Path(audio).resolve().as_posix().casefold()] = text
    return preserved


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "audio",
        "text",
        "language",
        "duration_seconds",
        "avg_logprob",
        "min_logprob",
        "max_no_speech_prob",
        "max_compression_ratio",
        "elapsed_seconds",
        "cached",
        "status",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _connection(server_url: str, timeout: float) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlsplit(server_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid Whisper server URL: {server_url}")
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    return connection, parsed.path.rstrip("/")


def check_health(server_url: str, timeout: float) -> dict[str, Any]:
    connection, base_path = _connection(server_url, timeout)
    try:
        connection.request("GET", f"{base_path}/health")
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise RuntimeError(f"Whisper health check failed: HTTP {response.status}")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("status") not in {"ok", "loading"}:
        raise RuntimeError(f"Whisper server is not ready: {payload}")
    return payload


def transcribe_audio(
    server_url: str,
    audio: Path,
    model: str,
    language: str,
    prompt: str | None,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
    boundary = f"----IrodoriSpeakerTraining{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    add_field("model", model)
    add_field("language", language)
    add_field("response_format", "verbose_json")
    add_field("temperature", "0")
    if prompt and prompt.strip():
        add_field("prompt", prompt.strip())
    filename = audio.name.replace('"', "_")
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            audio.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    body = b"".join(chunks)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    connection, base_path = _connection(server_url, timeout)
    try:
        connection.request("POST", f"{base_path}/v1/audio/transcriptions", body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
    finally:
        connection.close()
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"Whisper server returned invalid JSON (HTTP {response.status})") from exc
    if response.status != 200:
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        raise RuntimeError(f"Whisper API HTTP {response.status}: {detail}")
    if not isinstance(payload, dict):
        raise RuntimeError("Whisper server returned a non-object response")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Whisper API transcription utility for Irodori")
    parser.add_argument("input", help="Audio/video file or a directory (recursive)")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--server-url", default=os.getenv("MIRAI_WHISPER_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("MIRAI_WHISPER_API_KEY", ""))
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--model", default="turbo")
    parser.add_argument("--language", default="ja")
    parser.add_argument("--initial-prompt", default=None)
    parser.add_argument("--irodori", action="store_true", help="Write Irodori metadata.jsonl")
    parser.add_argument("--force", action="store_true", help="Re-transcribe existing results")
    parser.add_argument(
        "--replace-existing-metadata",
        action="store_true",
        help="Replace manually corrected text already present in metadata.jsonl",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server_url = str(args.server_url).strip().rstrip("/")
    source = Path(args.input).expanduser().resolve()
    audio_files = discover_audio(source)
    if not audio_files:
        print(f"No supported audio/video files found: {source}", file=sys.stderr)
        return 2

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else default_output_dir(source, args.irodori)
    )
    transcript_dir = output_dir / ("transcriptions" if args.irodori else "files")
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[Path, Path, Path]] = []
    for audio in audio_files:
        prefix = (transcript_dir / relative_audio_path(audio, source)).with_suffix("")
        jobs.append((audio, prefix, prefix.with_suffix(".json")))

    pending = [job for job in jobs if args.force or load_cached_result(job[2]) is None]
    print(f"Whisper server: {server_url}")
    print(f"Input: {source}")
    print(f"Output: {output_dir}")
    print(f"Audio files: {len(jobs)}  Pending: {len(pending)}  Cached: {len(jobs) - len(pending)}")
    if pending:
        health = check_health(server_url, min(float(args.timeout), 10.0))
        print(
            f"Whisper ready: model={health.get('model', '-')} "
            f"device={health.get('device', '-')}"
        )

    rows: list[dict[str, Any]] = []
    failures = 0
    for index, (audio, prefix, cache_json) in enumerate(jobs, start=1):
        cached_result = None if args.force else load_cached_result(cache_json)
        print(f"[{index}/{len(jobs)}] {audio}")
        started = time.perf_counter()
        try:
            server_result: dict[str, Any] | None = None
            if cached_result is not None:
                result = cached_result
                cached = True
            else:
                server_result = transcribe_audio(
                    server_url,
                    audio,
                    str(args.model).strip() or "turbo",
                    str(args.language).strip() or "ja",
                    args.initial_prompt,
                    str(args.api_key).strip(),
                    float(args.timeout),
                )
                result = {
                    "text": str(server_result.get("text", "")).strip(),
                    "language": str(server_result.get("language", "")),
                    "segments": server_result.get("segments") or [],
                }
                used_model = str(server_result.get("model", args.model))
                write_result(prefix, audio, result, used_model, server_result)
                cached = False
            row = summarize(audio, result, time.perf_counter() - started, cached, server_result)
            rows.append(row)
            print(f"  [{row['status']}] {row['text']}")
        except Exception as exc:
            failures += 1
            print(f"  [ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            rows.append(
                {
                    "audio": audio.as_posix(),
                    "text": "",
                    "language": "",
                    "duration_seconds": "",
                    "avg_logprob": "",
                    "min_logprob": "",
                    "max_no_speech_prob": "",
                    "max_compression_ratio": "",
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "cached": False,
                    "status": "error",
                    "notes": f"{type(exc).__name__}: {exc}",
                }
            )

    write_review_csv(output_dir / "transcription_review.csv", rows)
    successful = [row for row in rows if row["text"] and row["status"] != "error"]
    atomic_text(
        output_dir / "transcripts.jsonl",
        "".join(json_line(row) + "\n" for row in successful),
    )

    if args.irodori:
        metadata_path = output_dir / "metadata.jsonl"
        preserved = {} if args.replace_existing_metadata else existing_metadata(metadata_path)
        metadata_rows: list[dict[str, str]] = []
        preserved_count = 0
        for row in successful:
            audio_key = Path(row["audio"]).resolve().as_posix().casefold()
            text = preserved.get(audio_key, str(row["text"]))
            if audio_key in preserved:
                preserved_count += 1
            metadata_rows.append({"audio": Path(row["audio"]).resolve().as_posix(), "text": text})
        atomic_text(metadata_path, "".join(json_line(row) + "\n" for row in metadata_rows))
        print(
            f"Irodori metadata: {metadata_path} "
            f"({len(metadata_rows)} rows, preserved edits: {preserved_count})"
        )

    review_count = sum(row["status"] == "review" for row in rows)
    print(f"Finished. OK={len(successful) - review_count} Review={review_count} Errors={failures}")
    print(f"Review CSV: {output_dir / 'transcription_review.csv'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
