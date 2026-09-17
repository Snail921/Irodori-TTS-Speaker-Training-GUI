from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import speaker_training_gui as gui


class CheckpointTestFunctions(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.speaker_root = self.root / "speaker-training"
        self.embedding_root = self.root / "speaker-embeddings"
        self.irodori_root = self.root / "Irodori-TTS"
        self.jobs_root = self.speaker_root / ".jobs"
        (self.speaker_root / "Alice" / "audio").mkdir(parents=True)
        (self.embedding_root / "Alice" / "20260918-120000").mkdir(parents=True)
        self.embedding = (
            self.embedding_root
            / "Alice"
            / "20260918-120000"
            / "checkpoint_0000250.speaker.safetensors"
        )
        self.embedding.write_bytes(b"test")
        self.checkpoint = self.root / "model.safetensors"
        self.checkpoint.write_bytes(b"test")
        self.infer = self.irodori_root / "infer.py"
        self.infer.parent.mkdir(parents=True)
        self.infer.write_text("# test\n", encoding="utf-8")
        self.patches = [
            patch.object(gui, "SPEAKER_ROOT", self.speaker_root),
            patch.object(gui, "EMBEDDING_ROOT", self.embedding_root),
            patch.object(gui, "IRODORI_ROOT", self.irodori_root),
            patch.object(gui, "JOBS_ROOT", self.jobs_root),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_embedding_choices_use_paths_relative_to_speaker(self) -> None:
        self.assertEqual(
            gui._embedding_choices("Alice"),
            ["20260918-120000/checkpoint_0000250.speaker.safetensors"],
        )

    def test_start_test_builds_reproducible_infer_command(self) -> None:
        with patch.object(gui, "_launch_job", return_value="started") as launch:
            status, log, output, audio, audio_status, loaded = gui._start_test(
                "Alice",
                "20260918-120000/checkpoint_0000250.speaker.safetensors",
                str(self.checkpoint),
                "テストです。",
                "落ち着いた声",
                "fp32",
                40,
                1234,
            )

        self.assertEqual(status, "started")
        self.assertEqual(log, "")
        self.assertIsNone(audio)
        self.assertIn("自動再生", audio_status)
        self.assertEqual(loaded, "")
        self.assertTrue(output.endswith(".wav"))
        command = launch.call_args.args[2]
        self.assertEqual(launch.call_args.args[:2], ("Alice", "test"))
        self.assertIn(str(self.infer), command)
        self.assertEqual(command[command.index("--seed") + 1], "1234")
        self.assertEqual(command[command.index("--num-steps") + 1], "40")
        self.assertEqual(command[command.index("--ref-embed") + 1], str(self.embedding))
        self.assertEqual(command[command.index("--caption") + 1], "落ち着いた声")

    def test_completed_test_is_loaded_only_once(self) -> None:
        output = self.embedding.parent / "tests" / "sample.wav"
        output.parent.mkdir()
        output.write_bytes(b"RIFF-test")
        status_path, log_path = gui._job_files("Alice", "test")
        status_path.parent.mkdir(parents=True)
        status_path.write_text(
            json.dumps(
                {
                    "state": "completed",
                    "exit_code": 0,
                    "command": ["--output-wav", str(output)],
                }
            ),
            encoding="utf-8",
        )
        log_path.write_text("done", encoding="utf-8")

        first = gui._test_job_view("Alice", str(output), "")
        self.assertEqual(first[2], str(output.resolve()))
        self.assertIn("自動再生", first[3])
        self.assertEqual(first[4], str(output.resolve()))

        second = gui._test_job_view("Alice", str(output), first[4])
        self.assertEqual(second[4], str(output.resolve()))


if __name__ == "__main__":
    unittest.main()
