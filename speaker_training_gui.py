#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr


ROOT = Path(__file__).resolve().parent
IRODORI_ROOT = Path(os.getenv("IRODORI_TTS_ROOT", str(ROOT))).expanduser().resolve()
SPEAKER_ROOT = ROOT / "speaker-training"
EMBEDDING_ROOT = ROOT / "speaker-embeddings"
JOBS_ROOT = SPEAKER_ROOT / ".jobs"
GUI_PYTHON = Path(sys.executable).resolve()
WHISPER_SERVER_URL = (
    os.getenv("MIRAI_WHISPER_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    or "http://127.0.0.1:8000"
)
WHISPER_CLIENT = ROOT / "speaker_training_transcribe_client.py"
AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".wma"}
REVIEW_HEADERS = ["audio", "text", "approved", "asr_status", "notes"]
APPROVED_METADATA_NAME = "approved_metadata.jsonl"
UI_VERSION = "checkpoint-test-v2.8 / 2026-09-18"

REVIEW_AUDIO_REPLAY_JS = r"""
() => {
    if (window.__irodoriReviewAudioReplayInstalled) return;
    window.__irodoriReviewAudioReplayInstalled = true;

    document.addEventListener("click", (event) => {
        const tableRoot = event.target.closest("#speaker-review-table");
        const cell = event.target.closest("td");
        if (!tableRoot || !cell || !tableRoot.contains(cell)) return;

        const headers = Array.from(tableRoot.querySelectorAll("thead th, thead td"));
        const audioColumn = headers.findIndex(
            (header) => header.textContent.trim().toLowerCase() === "audio"
        );
        if (audioColumn < 0) return;

        const rowCells = Array.from(cell.parentElement?.cells || []);
        const audioCell = rowCells[audioColumn];
        const relativePath = audioCell?.textContent.trim() || "";
        if (!relativePath) return;

        let attempts = 0;
        const playWhenReady = () => {
            attempts += 1;
            const statusField = document.querySelector(
                "#speaker-review-selected-clip input, #speaker-review-selected-clip textarea"
            );
            const player = document.querySelector("#speaker-review-audio audio");
            const selectedStatus = statusField?.value || "";
            if (selectedStatus.endsWith(relativePath) && player?.src) {
                player.currentTime = 0;
                const playResult = player.play();
                if (playResult?.catch) playResult.catch(() => {});
                return;
            }
            if (attempts < 50) window.setTimeout(playWhenReady, 100);
        };
        window.setTimeout(playWhenReady, 0);
    }, true);
}
"""


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(content, encoding="utf-8")
    for attempt in range(8):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 7:
                break
            time.sleep(0.05 * (attempt + 1))
    path.write_text(content, encoding="utf-8")
    try:
        temp.unlink(missing_ok=True)
    except OSError:
        pass


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _speaker_names() -> list[str]:
    SPEAKER_ROOT.mkdir(parents=True, exist_ok=True)
    return sorted(
        [path.name for path in SPEAKER_ROOT.iterdir() if path.is_dir() and not path.name.startswith(".")],
        key=str.casefold,
    )


def _speaker_dir(name: str | None) -> Path:
    selected = str(name or "").strip()
    if selected not in _speaker_names():
        raise ValueError("話者をドロップダウンから選択してください。")
    return SPEAKER_ROOT / selected


def _audio_files(speaker_dir: Path) -> list[Path]:
    audio_dir = speaker_dir / "audio"
    if not audio_dir.is_dir():
        return []
    return sorted(
        [path.resolve() for path in audio_dir.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS],
        key=lambda path: str(path).casefold(),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"{path.name} の{line_number}行目が不正です: {exc}") from exc
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _metadata_audio_path(speaker_dir: Path, raw: str) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = speaker_dir / path
    return path.resolve()


def _review_state(speaker_dir: Path) -> dict[str, bool]:
    path = speaker_dir / "review_state.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {}
    approvals = data.get("approvals", {}) if isinstance(data, dict) else {}
    return {str(key).casefold(): bool(value) for key, value in approvals.items()}


def _relative_audio_key(speaker_dir: Path, audio_path: Path) -> str:
    try:
        return audio_path.resolve().relative_to(speaker_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"話者フォルダ外の音声は登録できません: {audio_path}") from exc


def _asr_review(speaker_dir: Path) -> dict[str, dict[str, str]]:
    path = speaker_dir / "transcription_review.csv"
    if not path.is_file():
        return {}
    output: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = str(row.get("audio", "")).strip()
            if raw:
                key = _metadata_audio_path(speaker_dir, raw).as_posix().casefold()
                existing = output.get(key)
                # A legacy CP932 console error could append an error row after an otherwise
                # successful transcription. Keep the useful result when duplicates exist.
                if existing is None or (
                    str(existing.get("status", "")).casefold() == "error"
                    and str(row.get("status", "")).casefold() != "error"
                ):
                    output[key] = row
    return output


def _review_rows(speaker: str | None) -> list[list[Any]]:
    speaker_dir = _speaker_dir(speaker)
    metadata = _read_jsonl(speaker_dir / "metadata.jsonl")
    approvals = _review_state(speaker_dir)
    asr = _asr_review(speaker_dir)
    rows: list[list[Any]] = []
    for item in metadata:
        audio = _metadata_audio_path(speaker_dir, str(item.get("audio", "")))
        relative = _relative_audio_key(speaker_dir, audio)
        review = asr.get(audio.as_posix().casefold(), {})
        rows.append(
            [
                relative,
                str(item.get("text", "")).strip(),
                bool(approvals.get(relative.casefold(), False)),
                str(review.get("status", "")),
                str(review.get("notes", "")),
            ]
        )
    return rows


def _table_rows(value: Any) -> list[list[Any]]:
    if value is None:
        return []
    if hasattr(value, "values"):
        value = value.values.tolist()
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return [[item.get(header, "") for header in REVIEW_HEADERS] for item in value]
        return [list(row) for row in value]
    raise ValueError("レビュー表の形式を読み取れません。")


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes", "on", "済", "承認"}


def _review_summary(rows: list[list[Any]]) -> str:
    total = len(rows)
    approved = sum(len(row) > 2 and _bool_value(row[2]) for row in rows)
    blank = sum(len(row) < 2 or not str(row[1]).strip() for row in rows)
    return f"登録: {total}件 / 承認済み: {approved}件 / 未承認: {total - approved}件 / 空欄: {blank}件"


def _load_review(speaker: str | None):
    rows = _review_rows(speaker)
    return rows, None, "audioまたはtextセルをクリックしてください。", _review_summary(rows)


def _select_review_cell(speaker: str | None, table: Any, evt: gr.SelectData):
    rows = _table_rows(table)
    index = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    try:
        row = rows[int(index)]
    except (IndexError, TypeError, ValueError):
        return None, "音声行を選択してください。"
    if not row:
        return None, "音声行を選択してください。"
    relative = str(row[0])
    audio = (_speaker_dir(speaker) / relative).resolve()
    if not audio.is_file():
        return None, f"音声ファイルがありません: {relative}"
    return str(audio), f"選択中: {relative}"


def _mark_all_approved(table: Any):
    rows = _table_rows(table)
    for row in rows:
        while len(row) < len(REVIEW_HEADERS):
            row.append("")
        row[2] = True
    return rows, _review_summary(rows)


def _save_review(speaker: str | None, table: Any):
    speaker_dir = _speaker_dir(speaker)
    rows = _table_rows(table)
    if not rows:
        raise gr.Error("保存する文字起こしがありません。")
    metadata: list[dict[str, str]] = []
    approvals: dict[str, bool] = {}
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        while len(row) < len(REVIEW_HEADERS):
            row.append("")
        relative = str(row[0]).strip().replace("\\", "/")
        text = str(row[1]).strip()
        approved = _bool_value(row[2])
        audio = (speaker_dir / relative).resolve()
        key = _relative_audio_key(speaker_dir, audio)
        if key.casefold() in seen:
            raise gr.Error(f"音声が重複しています: {key}")
        if approved and not audio.is_file():
            raise gr.Error(f"承認済み項目の音声ファイルがありません: {key}")
        if approved and not text:
            raise gr.Error(f"承認済み項目の文字起こしが空欄です: {key}")
        seen.add(key.casefold())
        metadata.append({"audio": audio.as_posix(), "text": text})
        approvals[key] = approved
    _atomic_text(
        speaker_dir / "metadata.jsonl",
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in metadata),
    )
    _atomic_json(
        speaker_dir / "review_state.json",
        {
            "version": 1,
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "approvals": approvals,
        },
    )
    return f"保存しました。{_review_summary(rows)}", _speaker_status(speaker)


def _approved_training_rows(speaker: str | None) -> tuple[list[dict[str, str]], int]:
    speaker_dir = _speaker_dir(speaker)
    rows = _review_rows(speaker)
    if not rows:
        raise ValueError("metadata.jsonlがありません。先に文字起こしを作成してください。")
    approved: list[dict[str, str]] = []
    for row in rows:
        if len(row) < 3 or not _bool_value(row[2]):
            continue
        relative = str(row[0]).strip().replace("\\", "/")
        text = str(row[1]).strip()
        audio = (speaker_dir / relative).resolve()
        if not text:
            raise ValueError(f"承認済み項目の文字起こしが空欄です: {relative}")
        if not audio.is_file():
            raise ValueError(f"承認済み項目の音声がありません: {relative}")
        approved.append({"audio": audio.as_posix(), "text": text})
    return approved, len(rows)


def _dataset_ready(speaker: str | None) -> tuple[bool, str]:
    try:
        approved, total = _approved_training_rows(speaker)
    except Exception as exc:
        return False, str(exc)
    if not approved:
        return False, "承認済みの音声・文字起こしペアがありません。"
    return True, f"学習対象: 承認済み {len(approved)}件 / 登録 {total}件"


def _manifest_fresh(speaker_dir: Path) -> bool:
    manifest = speaker_dir / "train_manifest.jsonl"
    approved_metadata = speaker_dir / APPROVED_METADATA_NAME
    if not manifest.is_file() or not approved_metadata.is_file():
        return False
    try:
        metadata_rows = _read_jsonl(approved_metadata)
        manifest_rows = _read_jsonl(manifest)
    except Exception:
        return False
    if not metadata_rows or len(manifest_rows) != len(metadata_rows):
        return False
    for item in manifest_rows:
        latent_raw = str(item.get("latent_path", "")).strip()
        if not str(item.get("text", "")).strip() or not latent_raw:
            return False
        latent_path = Path(latent_raw).expanduser()
        if not latent_path.is_absolute():
            latent_path = manifest.parent / latent_path
        if not latent_path.is_file():
            return False
    approved_audio = [
        _metadata_audio_path(speaker_dir, str(item.get("audio", ""))) for item in metadata_rows
    ]
    sources = [
        approved_metadata,
        speaker_dir / "metadata.jsonl",
        speaker_dir / "review_state.json",
        *approved_audio,
    ]
    newest = max((path.stat().st_mtime_ns for path in sources if path.exists()), default=0)
    return manifest.stat().st_mtime_ns >= newest


def _default_checkpoint() -> str:
    configured = os.getenv("IRODORI_CHECKPOINT", "").strip()
    if configured and Path(configured).expanduser().is_file():
        return str(Path(configured).expanduser().resolve())

    hf_home = Path(
        os.getenv("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    ).expanduser()
    cache_roots = [
        IRODORI_ROOT / "models-cache" / "huggingface" / "hub",
        ROOT / "models-cache" / "huggingface" / "hub",
        hf_home / "hub",
    ]
    model_dirs = [
        "models--Aratako--Irodori-TTS-v4.1-Small",
        "models--Aratako--Irodori-TTS-v4-Small",
    ]
    candidates: list[Path] = []
    for cache_root in cache_roots:
        for model_dir in model_dirs:
            candidates.extend((cache_root / model_dir / "snapshots").glob("*/model.safetensors"))
    candidates = sorted(
        {path.resolve() for path in candidates if path.is_file()},
        key=lambda path: path.stat().st_mtime_ns,
    )
    return str(candidates[-1]) if candidates else ""


def _embedding_choices(speaker: str | None) -> list[str]:
    try:
        speaker_dir = _speaker_dir(speaker)
    except Exception:
        return []
    root = EMBEDDING_ROOT / speaker_dir.name
    if not root.is_dir():
        return []

    def sort_key(path: Path) -> tuple[int, int, int, str]:
        match = re.search(r"checkpoint_(\d+)", path.name, re.IGNORECASE)
        step = int(match.group(1)) if match else -1
        is_final = 1 if "final" in path.name.casefold() else 0
        return (path.parent.stat().st_mtime_ns, is_final, step, path.as_posix().casefold())

    paths = sorted(root.rglob("*.speaker.safetensors"), key=sort_key, reverse=True)
    return [path.resolve().relative_to(root.resolve()).as_posix() for path in paths]


def _resolve_embedding(speaker: str | None, selection: str | None) -> Path:
    speaker_dir = _speaker_dir(speaker)
    root = (EMBEDDING_ROOT / speaker_dir.name).resolve()
    selected = str(selection or "").strip()
    if not selected:
        raise gr.Error("テストするSpeaker Embeddingを選択してください。")
    candidate = (root / selected).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise gr.Error("Speaker Embeddingの指定が話者フォルダー外です。") from exc
    if not candidate.is_file() or not candidate.name.endswith(".speaker.safetensors"):
        raise gr.Error(f"Speaker Embeddingが見つかりません: {candidate}")
    return candidate


def _refresh_test_embeddings(speaker: str | None, current: str | None = None):
    choices = _embedding_choices(speaker)
    value = current if current in choices else (choices[0] if choices else None)
    if choices:
        message = f"{len(choices)}個のSpeaker Embeddingを検出しました。"
    else:
        message = "Speaker Embeddingがありません。先に学習を完了してください。"
    return gr.update(choices=choices, value=value), message


def _start_test(
    speaker: str | None,
    embedding_selection: str | None,
    checkpoint: str,
    text: str,
    caption: str,
    precision: str,
    num_steps: int,
    seed: int,
) -> tuple[str, str, str]:
    speaker_dir = _speaker_dir(speaker)
    embedding = _resolve_embedding(speaker, embedding_selection)
    infer_script = IRODORI_ROOT / "infer.py"
    if not infer_script.is_file():
        raise gr.Error(f"Irodori-TTSのinfer.pyが見つかりません: {infer_script}")
    checkpoint_path = Path(str(checkpoint).strip()).expanduser().resolve()
    if not checkpoint_path.is_file():
        raise gr.Error(f"ベースモデルがありません: {checkpoint_path}")
    reading_text = str(text).strip()
    if not reading_text:
        raise gr.Error("読み上げテキストを入力してください。")
    if str(precision) not in {"fp32", "bf16"}:
        raise gr.Error("Precisionはfp32またはbf16を指定してください。")
    if int(num_steps) <= 0:
        raise gr.Error("Num Stepsは1以上を指定してください。")

    output_dir = embedding.parent / "tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    embedding_name = embedding.name.removesuffix(".speaker.safetensors")
    output_path = output_dir / (
        f"{embedding_name}_{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.wav"
    )
    command = [
        str(GUI_PYTHON),
        str(infer_script),
        "--checkpoint",
        str(checkpoint_path),
        "--ref-embed",
        str(embedding),
        "--text",
        reading_text,
        "--output-wav",
        str(output_path),
        "--model-device",
        "cuda",
        "--codec-device",
        "cuda",
        "--model-precision",
        str(precision),
        "--codec-precision",
        str(precision),
        "--num-steps",
        str(int(num_steps)),
        "--seed",
        str(int(seed)),
    ]
    if str(caption).strip():
        command += ["--caption", str(caption).strip()]
    message = _launch_job(speaker_dir.name, "test", command)
    return message, "", str(output_path)


def _load_test_audio(output_path: str | None) -> tuple[str, str]:
    raw = str(output_path or "").strip()
    if not raw:
        raise gr.Error("先にテスト音声を生成してください。")
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(EMBEDDING_ROOT.resolve())
    except ValueError as exc:
        raise gr.Error("テスト音声のパスが出力フォルダー外です。") from exc
    if not path.is_file():
        raise gr.Error("音声はまだ生成されていません。ジョブ完了後にもう一度押してください。")
    return str(path), f"生成音声を読み込みました: {path.name}"


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _job_files(speaker: str, kind: str) -> tuple[Path, Path]:
    safe_kind = "".join(ch for ch in str(kind) if ch.isalnum() or ch in {"-", "_"})
    speaker_dir = _speaker_dir(speaker)
    job_dir = JOBS_ROOT / speaker_dir.name
    return job_dir / f"{safe_kind}.status.json", job_dir / f"{safe_kind}.log"


def _read_status(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {}


def _running_job() -> dict[str, Any] | None:
    if not JOBS_ROOT.is_dir():
        return None
    for status_path in JOBS_ROOT.rglob("*.status.json"):
        status = _read_status(status_path)
        if status.get("state") != "running":
            continue
        pid = int(status.get("pid") or 0)
        if _pid_exists(pid):
            return status
        status["state"] = "interrupted"
        status["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _atomic_json(status_path, status)
    return None


def _launch_job(speaker: str, kind: str, command: list[str]) -> str:
    active = _running_job()
    if active:
        raise gr.Error(f"別のジョブが実行中です: {active.get('speaker')} / {active.get('kind')}")
    status_path, log_path = _job_files(speaker, kind)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    runner = [
        str(GUI_PYTHON),
        str(ROOT / "speaker_training_job_runner.py"),
        "--status",
        str(status_path),
        "--log",
        str(log_path),
        "--cwd",
        str(ROOT),
        "--kind",
        kind,
        "--speaker",
        speaker,
        "--",
        *command,
    ]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    process = subprocess.Popen(
        runner,
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    _atomic_json(
        status_path,
        {
            "kind": kind,
            "speaker": speaker,
            "state": "running",
            "pid": process.pid,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "command": command,
            "log": str(log_path),
        },
    )
    return f"開始しました: {speaker} / {kind} (PID {process.pid})"


def _tail(path: Path, max_chars: int = 18000) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    # Older logs may contain UTF-8 runner lines and CP932 child lines in one file.
    # Decode each physical/progress line independently so both old and new logs remain readable.
    decoded: list[str] = []
    for raw_line in data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"):
        try:
            decoded.append(raw_line.decode("utf-8"))
        except UnicodeDecodeError:
            decoded.append(raw_line.decode("cp932", errors="replace"))
    text = "\n".join(decoded)
    return text[-max_chars:]


def _job_view(speaker: str | None, kind: str) -> tuple[str, str]:
    try:
        status_path, log_path = _job_files(str(speaker), kind)
    except Exception:
        return "話者を選択してください。", ""
    status = _read_status(status_path)
    if not status:
        return "未実行", _tail(log_path)
    state = status.get("state", "unknown")
    text = f"状態: {state} / PID: {status.get('pid', '-')} / 終了コード: {status.get('exit_code', '-')}"
    if status.get("started_at"):
        text += f" / 開始: {status['started_at']}"
    if status.get("finished_at"):
        text += f" / 終了: {status['finished_at']}"
    return text, _tail(log_path)


def _stop_job(speaker: str | None, kind: str) -> tuple[str, str]:
    status_path, log_path = _job_files(str(speaker), kind)
    status = _read_status(status_path)
    if status.get("state") != "running":
        return "実行中のジョブはありません。", _tail(log_path)
    pid = int(status.get("pid") or 0)
    if pid > 0 and _pid_exists(pid):
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    status["state"] = "stopped"
    status["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    status["exit_code"] = -9
    _atomic_json(status_path, status)
    return "停止しました。", _tail(log_path)


def _start_transcription(
    speaker: str | None,
    model: str,
    language: str,
    initial_prompt: str,
    force: bool,
) -> tuple[str, str]:
    speaker_dir = _speaker_dir(speaker)
    audio_dir = speaker_dir / "audio"
    audio_count = len(_audio_files(speaker_dir))
    if audio_count == 0:
        raise gr.Error(f"audioフォルダに音声がありません: {audio_dir}")
    if not WHISPER_CLIENT.is_file():
        raise gr.Error(f"Whisper APIクライアントが見つかりません: {WHISPER_CLIENT}")
    command = [
        str(GUI_PYTHON),
        str(WHISPER_CLIENT),
        str(audio_dir),
        "--irodori",
        "--server-url",
        WHISPER_SERVER_URL,
        "--model",
        str(model).strip() or "turbo",
        "--language",
        str(language).strip() or "ja",
    ]
    if str(initial_prompt).strip():
        command += ["--initial-prompt", str(initial_prompt).strip()]
    if force:
        command.append("--force")
    message = _launch_job(speaker_dir.name, "transcribe", command)
    return message, ""


def _start_prepare(speaker: str | None) -> tuple[str, str]:
    speaker_dir = _speaker_dir(speaker)
    ready, detail = _dataset_ready(speaker)
    if not ready:
        raise gr.Error(f"データセットが未完成です: {detail}")
    approved_rows, _ = _approved_training_rows(speaker)
    approved_metadata = speaker_dir / APPROVED_METADATA_NAME
    _atomic_text(
        approved_metadata,
        "".join(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            for item in approved_rows
        ),
    )
    command = [
        str(GUI_PYTHON),
        str(IRODORI_ROOT / "prepare_manifest.py"),
        "--dataset",
        "json",
        "--data-files",
        f"train={approved_metadata}",
        "--split",
        "train",
        "--audio-column",
        "audio",
        "--text-column",
        "text",
        "--output-manifest",
        str(speaker_dir / "train_manifest.jsonl"),
        "--latent-dir",
        str(speaker_dir / "latents"),
        "--device",
        "cuda",
        "--cache-dir",
        str(ROOT / "models-cache" / "huggingface" / "datasets"),
        "--prefetch",
        "8",
        "--prefetch-workers",
        "2",
    ]
    return _launch_job(speaker_dir.name, "prepare", command), ""


def _start_training(
    speaker: str | None,
    checkpoint: str,
    precision: str,
    batch_size: int,
    grad_accum: int,
    max_steps: int,
    save_every: int,
    num_workers: int,
) -> tuple[str, str, str]:
    speaker_dir = _speaker_dir(speaker)
    ready, detail = _dataset_ready(speaker)
    if not ready:
        raise gr.Error(f"データセットが未完成です: {detail}")
    if not _manifest_fresh(speaker_dir):
        raise gr.Error("manifestが未作成または素材更新後の再作成が必要です。先に『manifestを作成』してください。")
    positive_values = {
        "Batch Size": int(batch_size),
        "Gradient Accumulation": int(grad_accum),
        "Max Steps": int(max_steps),
        "Save Every": int(save_every),
    }
    invalid = [name for name, value in positive_values.items() if value <= 0]
    if invalid:
        raise gr.Error("1以上を指定してください: " + ", ".join(invalid))
    if int(num_workers) < 0:
        raise gr.Error("DataLoader Workersは0以上を指定してください。")
    if os.name == "nt" and int(num_workers) > 0:
        raise gr.Error(
            "WindowsではDataLoader Workersを0にしてください。"
            "複数workerはPyTorch/CUDAを子プロセスごとに読み込み、ページファイル不足を起こすことがあります。"
        )
    checkpoint_path = Path(str(checkpoint).strip()).expanduser().resolve()
    if not checkpoint_path.is_file():
        raise gr.Error(f"ベースモデルがありません: {checkpoint_path}")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = EMBEDDING_ROOT / speaker_dir.name / timestamp
    command = [
        str(GUI_PYTHON),
        str(IRODORI_ROOT / "train.py"),
        "--config",
        str(IRODORI_ROOT / "configs" / "train_v4_small_speaker_inversion.yaml"),
        "--manifest",
        str(speaker_dir / "train_manifest.jsonl"),
        "--init-checkpoint",
        str(checkpoint_path),
        "--output-dir",
        str(output_dir),
        "--device",
        "cuda",
        "--precision",
        str(precision),
        "--batch-size",
        str(int(batch_size)),
        "--gradient-accumulation-steps",
        str(int(grad_accum)),
        "--max-steps",
        str(int(max_steps)),
        "--save-every",
        str(int(save_every)),
        "--num-workers",
        str(int(num_workers)),
        "--gradient-checkpointing",
    ]
    message = _launch_job(speaker_dir.name, "train", command)
    return message, "", str(output_dir)


def _speaker_status(speaker: str | None) -> str:
    try:
        speaker_dir = _speaker_dir(speaker)
    except Exception:
        return "話者フォルダを選択してください。"
    audio_count = len(_audio_files(speaker_dir))
    metadata_count = len(_read_jsonl(speaker_dir / "metadata.jsonl"))
    approvals = _review_state(speaker_dir)
    approved_count = sum(approvals.values())
    manifest_count = len(_read_jsonl(speaker_dir / "train_manifest.jsonl"))
    embeddings = list((EMBEDDING_ROOT / speaker_dir.name).rglob("*.speaker.safetensors")) if (EMBEDDING_ROOT / speaker_dir.name).is_dir() else []
    return (
        f"話者: {speaker_dir.name} | 音声: {audio_count} | 文字起こし: {metadata_count} | "
        f"承認: {approved_count}/{metadata_count} | manifest: {manifest_count} | embedding: {len(embeddings)}"
    )


def _refresh_speakers(current: str | None):
    names = _speaker_names()
    value = current if current in names else (names[0] if names else None)
    return gr.update(choices=names, value=value), _speaker_status(value)


def _training_readiness(speaker: str | None) -> str:
    try:
        speaker_dir = _speaker_dir(speaker)
    except Exception as exc:
        return str(exc)
    ready, detail = _dataset_ready(speaker)
    manifest = speaker_dir / "train_manifest.jsonl"
    latent_count = len(list((speaker_dir / "latents").glob("*.pt"))) if (speaker_dir / "latents").is_dir() else 0
    return (
        f"レビュー: {'OK' if ready else 'NG'} — {detail}\n"
        f"manifest: {'最新' if _manifest_fresh(speaker_dir) else '未作成または古い'} "
        f"({manifest})\n学習latent: {latent_count}件"
    )


def build_ui() -> gr.Blocks:
    speakers = _speaker_names()
    initial = speakers[0] if speakers else None
    initial_embeddings = _embedding_choices(initial)
    initial_embedding = initial_embeddings[0] if initial_embeddings else None
    with gr.Blocks(title="Irodori Speaker Training") as demo:
        gr.Markdown(
            "# Irodori Speaker Training\n"
            "文字起こし → 音声付きレビュー → manifest作成・Speaker Inversion学習 → チェックポイント比較を行います。\n\n"
            f"UI Version: `{UI_VERSION}`"
        )
        with gr.Row():
            speaker = gr.Dropdown(label="話者 / キャラクターフォルダ", choices=speakers, value=initial, scale=4)
            refresh_speakers = gr.Button("フォルダ一覧を更新", scale=1)
        speaker_status = gr.Textbox(label="データ状況", value=_speaker_status(initial), interactive=False)

        with gr.Tabs():
            with gr.Tab("1. 文字起こし"):
                gr.Markdown(
                    "選択話者の `audio` フォルダをWhisperサーバーで一括処理します。"
                    "既存metadataの手修正は保持されます。"
                    f" 接続先: `{WHISPER_SERVER_URL}`"
                )
                with gr.Row():
                    whisper_model = gr.Dropdown(
                        label="Whisper Model", choices=["turbo", "large-v3", "medium", "small"], value="turbo"
                    )
                    whisper_language = gr.Dropdown(label="Language", choices=["ja", "auto"], value="ja")
                    force_transcribe = gr.Checkbox(label="既存結果も再文字起こし", value=False)
                initial_prompt = gr.Textbox(
                    label="固有名詞ヒント（任意）",
                    placeholder="キャラクター名、作品名、頻出する固有名詞など",
                )
                with gr.Row():
                    start_transcribe = gr.Button("文字起こしを開始", variant="primary")
                    stop_transcribe = gr.Button("文字起こしを停止", variant="stop")
                transcription_status = gr.Textbox(label="ジョブ状態", interactive=False)
                transcription_log = gr.Textbox(label="文字起こしログ", lines=16, interactive=False)

            with gr.Tab("2. 文字起こし確認・修正"):
                gr.Markdown(
                    "audioまたはtextセルをクリックすると対応音声がセットされます。"
                    "選択中のaudioセルは、同じセルを再クリックするたびに先頭から再生します。"
                    "textセルは表内で直接編集できます。"
                    "approvedをオンにしたペアだけが次回のmanifestへ含まれます。"
                    "編集内容は『修正と承認状態を保存』を押した時点でmetadata.jsonlへ反映されます。"
                )
                with gr.Row():
                    load_review = gr.Button("文字起こしを読み込む", variant="primary")
                    approve_all = gr.Button("全件を承認済みにする")
                    save_review = gr.Button("修正と承認状態を保存", variant="primary")
                review_summary = gr.Textbox(label="レビュー状況", interactive=False)
                review_table = gr.Dataframe(
                    headers=REVIEW_HEADERS,
                    datatype=["str", "str", "bool", "str", "str"],
                    type="array",
                    interactive=True,
                    wrap=True,
                    column_widths=[22, 45, 10, 10, 25],
                    max_height=440,
                    show_row_numbers=True,
                    static_columns=[0, 3, 4],
                    label="文字起こし一覧",
                    elem_id="speaker-review-table",
                )
                selected_clip_status = gr.Textbox(
                    label="選択クリップ",
                    interactive=False,
                    elem_id="speaker-review-selected-clip",
                )
                clip_audio = gr.Audio(
                    label="学習用クリップ",
                    type="filepath",
                    interactive=False,
                    autoplay=True,
                    elem_id="speaker-review-audio",
                )
                review_save_status = gr.Textbox(label="保存結果", interactive=False)

            with gr.Tab("3. manifest作成・学習"):
                gr.Markdown(
                    "承認済みの音声・文字起こしペアだけでmanifestを作成します。"
                    "未承認項目はファイルを保持したまま学習対象から除外されます。"
                    "通常のTTS GUIは終了してGPUとメモリを空けてください。"
                    "WindowsではDataLoader Workersを0にします。"
                )
                with gr.Row():
                    check_training = gr.Button("学習準備を確認")
                    prepare_manifest = gr.Button("manifestを作成", variant="primary")
                    stop_prepare = gr.Button("manifest作成を停止", variant="stop")
                training_readiness = gr.Textbox(label="学習準備", lines=4, interactive=False)
                prepare_status = gr.Textbox(label="manifestジョブ状態", interactive=False)
                prepare_log = gr.Textbox(label="manifest作成ログ", lines=12, interactive=False)

                with gr.Accordion("Speaker Inversion 学習設定", open=True):
                    checkpoint = gr.Textbox(label="V4/V4.1-Small Base Model", value=_default_checkpoint())
                    with gr.Row():
                        precision = gr.Dropdown(label="Precision", choices=["fp32", "bf16"], value="fp32")
                        batch_size = gr.Number(label="Batch Size", value=16, precision=0)
                        grad_accum = gr.Number(label="Gradient Accumulation", value=1, precision=0)
                        num_workers = gr.Number(
                            label="DataLoader Workers（Windowsは0）",
                            value=0,
                            precision=0,
                            minimum=0,
                        )
                    with gr.Row():
                        max_steps = gr.Number(label="Max Steps", value=3000, precision=0)
                        save_every = gr.Number(label="Save Every", value=250, precision=0)
                with gr.Row():
                    start_training = gr.Button("Speaker Embedding学習を開始", variant="primary")
                    stop_training = gr.Button("学習を停止", variant="stop")
                training_output = gr.Textbox(label="今回の出力先", interactive=False)
                train_status = gr.Textbox(label="学習ジョブ状態", interactive=False)
                train_log = gr.Textbox(label="学習ログ", lines=18, interactive=False)

            with gr.Tab("4. テスト"):
                gr.Markdown(
                    "学習で保存されたステップ別のSpeaker Embeddingを使って音声を生成し、聴き比べます。"
                    "比較時はテキスト・Seed・Num Steps・Precisionを同じ値にしてください。"
                    "テスト推論もGPUを使用するため、学習中や別のIrodori-TTS推論処理との同時実行は避けてください。"
                )
                with gr.Row():
                    test_embedding = gr.Dropdown(
                        label="テストするSpeaker Embedding",
                        choices=initial_embeddings,
                        value=initial_embedding,
                        scale=4,
                    )
                    refresh_test_embeddings = gr.Button("保存済みモデルを更新", scale=1)
                test_embedding_status = gr.Textbox(
                    label="検出状況",
                    value=(
                        f"{len(initial_embeddings)}個のSpeaker Embeddingを検出しました。"
                        if initial_embeddings
                        else "Speaker Embeddingがありません。先に学習を完了してください。"
                    ),
                    interactive=False,
                )
                test_checkpoint = gr.Textbox(
                    label="V4/V4.1-Small Base Model",
                    value=_default_checkpoint(),
                )
                test_text = gr.Textbox(
                    label="読み上げテキスト",
                    value="こんにちは。これは学習した話者の音声を確認するためのテストです。",
                    lines=3,
                )
                test_caption = gr.Textbox(
                    label="Caption / 話し方の指示（任意）",
                    placeholder="例: 落ち着いた自然な声で、やわらかく話す。",
                    lines=2,
                )
                with gr.Row():
                    test_precision = gr.Dropdown(
                        label="Precision",
                        choices=["fp32", "bf16"],
                        value="fp32",
                    )
                    test_num_steps = gr.Number(label="Num Steps", value=40, precision=0, minimum=1)
                    test_seed = gr.Number(
                        label="Seed（比較時は固定）",
                        value=1234,
                        precision=0,
                    )
                with gr.Row():
                    start_test = gr.Button("テスト音声を生成", variant="primary")
                    stop_test = gr.Button("テストを停止", variant="stop")
                    load_test_audio = gr.Button("生成音声をプレイヤーへ読み込む")
                test_output = gr.Textbox(label="今回の音声出力先", interactive=False)
                test_status = gr.Textbox(label="テストジョブ状態", interactive=False)
                test_log = gr.Textbox(label="テストログ", lines=14, interactive=False)
                test_audio_status = gr.Textbox(label="音声の読み込み結果", interactive=False)
                test_audio = gr.Audio(
                    label="生成音声",
                    type="filepath",
                    interactive=False,
                )

        refresh_speakers.click(_refresh_speakers, inputs=[speaker], outputs=[speaker, speaker_status])
        speaker.change(_speaker_status, inputs=[speaker], outputs=[speaker_status])
        speaker.change(
            _refresh_test_embeddings,
            inputs=[speaker, test_embedding],
            outputs=[test_embedding, test_embedding_status],
        )

        start_transcribe.click(
            _start_transcription,
            inputs=[speaker, whisper_model, whisper_language, initial_prompt, force_transcribe],
            outputs=[transcription_status, transcription_log],
        )
        stop_transcribe.click(
            lambda value: _stop_job(value, "transcribe"),
            inputs=[speaker],
            outputs=[transcription_status, transcription_log],
        )

        load_review.click(
            _load_review,
            inputs=[speaker],
            outputs=[review_table, clip_audio, selected_clip_status, review_summary],
        )
        review_table.select(
            _select_review_cell,
            inputs=[speaker, review_table],
            outputs=[clip_audio, selected_clip_status],
            show_progress="hidden",
        )
        review_table.change(
            lambda table: _review_summary(_table_rows(table)),
            inputs=[review_table],
            outputs=[review_summary],
            show_progress="hidden",
        )
        approve_all.click(_mark_all_approved, inputs=[review_table], outputs=[review_table, review_summary])
        save_review.click(
            _save_review,
            inputs=[speaker, review_table],
            outputs=[review_save_status, speaker_status],
        )

        check_training.click(_training_readiness, inputs=[speaker], outputs=[training_readiness])
        prepare_manifest.click(
            _start_prepare, inputs=[speaker], outputs=[prepare_status, prepare_log]
        )
        stop_prepare.click(
            lambda value: _stop_job(value, "prepare"),
            inputs=[speaker],
            outputs=[prepare_status, prepare_log],
        )
        start_training.click(
            _start_training,
            inputs=[
                speaker,
                checkpoint,
                precision,
                batch_size,
                grad_accum,
                max_steps,
                save_every,
                num_workers,
            ],
            outputs=[train_status, train_log, training_output],
        )
        stop_training.click(
            lambda value: _stop_job(value, "train"),
            inputs=[speaker],
            outputs=[train_status, train_log],
        )

        refresh_test_embeddings.click(
            _refresh_test_embeddings,
            inputs=[speaker, test_embedding],
            outputs=[test_embedding, test_embedding_status],
        )
        start_test.click(
            _start_test,
            inputs=[
                speaker,
                test_embedding,
                test_checkpoint,
                test_text,
                test_caption,
                test_precision,
                test_num_steps,
                test_seed,
            ],
            outputs=[test_status, test_log, test_output],
        )
        stop_test.click(
            lambda value: _stop_job(value, "test"),
            inputs=[speaker],
            outputs=[test_status, test_log],
        )
        load_test_audio.click(
            _load_test_audio,
            inputs=[test_output],
            outputs=[test_audio, test_audio_status],
        )

        timer = gr.Timer(value=2.0, active=True)
        timer.tick(
            lambda value: _job_view(value, "transcribe"),
            inputs=[speaker],
            outputs=[transcription_status, transcription_log],
            show_progress="hidden",
        )
        timer.tick(
            lambda value: _job_view(value, "prepare"),
            inputs=[speaker],
            outputs=[prepare_status, prepare_log],
            show_progress="hidden",
        )
        timer.tick(
            lambda value: _job_view(value, "train"),
            inputs=[speaker],
            outputs=[train_status, train_log],
            show_progress="hidden",
        )
        timer.tick(
            lambda value: _job_view(value, "test"),
            inputs=[speaker],
            outputs=[test_status, test_log],
            show_progress="hidden",
        )

    return demo


def main() -> None:
    parser = argparse.ArgumentParser(description="Irodori Speaker Training GUI")
    parser.add_argument("--server-name", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=7862)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args()
    demo = build_ui()
    demo.queue(default_concurrency_limit=4)
    demo.launch(
        server_name=args.server_name,
        server_port=args.server_port,
        share=bool(args.share),
        js=REVIEW_AUDIO_REPLAY_JS,
        allowed_paths=[str(SPEAKER_ROOT.resolve()), str(EMBEDDING_ROOT.resolve())],
    )


if __name__ == "__main__":
    main()
