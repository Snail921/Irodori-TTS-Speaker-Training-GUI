from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
import tempfile
import speaker_training_gui as gui
from speaker_training_test_worker import RuntimeSession


class WorkerTests(unittest.TestCase):
    def test_embeddings_reuse_model_precision_change_unloads_first(self):
        events = []
        runtime = Mock()
        runtime.unload.side_effect = lambda: events.append('unload')
        runtime.synthesize.return_value = SimpleNamespace(audio=None, sample_rate=48000, used_seed=1234)
        backend = SimpleNamespace(
            RuntimeKey=lambda **kw: kw, SamplingRequest=lambda **kw: kw,
            InferenceRuntime=SimpleNamespace(from_key=Mock(side_effect=lambda key: events.append('load') or runtime)),
            save_wav=Mock(),
        )
        session = RuntimeSession(backend)
        command = ['python', 'infer.py', '--checkpoint', 'base', '--ref-embed', 'a',
                   '--text', 'test', '--output-wav', 'out.wav', '--model-device', 'cuda',
                   '--codec-device', 'cuda', '--model-precision', 'fp32', '--codec-precision', 'fp32']
        session.synthesize(command)
        command[command.index('--ref-embed')+1] = 'b'
        session.synthesize(command)
        self.assertEqual(events, ['load'])
        self.assertEqual(runtime.synthesize.call_args.args[0]['ref_embed'], 'b')
        command[command.index('--model-precision')+1] = 'bf16'
        session.synthesize(command)
        self.assertEqual(events, ['load', 'unload', 'load'])

    def test_non_test_job_releases_model_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            with patch.object(gui, '_running_job', return_value=None), \
                 patch.object(gui, 'LogMirror'), \
                 patch.object(gui, '_job_files', return_value=(root/'status.json', root/'log')), \
                 patch.object(gui, '_release_test_worker', side_effect=lambda: events.append('release')), \
                 patch.object(gui.subprocess, 'Popen', side_effect=lambda *a, **kw: events.append('launch') or SimpleNamespace(pid=123, poll=lambda: 0)):
                gui._launch_job('Alice', 'train', ['python', 'train.py'])
            self.assertEqual(events, ['release', 'launch'])

    def test_active_job_prevents_another_test(self):
        with patch.object(gui, '_running_job', return_value={'speaker': 'Alice', 'kind': 'train'}), \
             patch.object(gui, '_TEST_WORKER', Mock()) as worker:
            with self.assertRaises(Exception):
                gui._launch_job('Alice', 'test', [])
            worker.submit.assert_not_called()

    def test_shutdown_stops_only_owned_running_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            status.write_text('{"pid": 123, "state": "running"}', encoding="utf-8")
            running = Mock(pid=123)
            running.poll.return_value = None
            finished = Mock(pid=456)
            finished.poll.return_value = 0
            owned = {('Alice', 'train'): running, ('Bob', 'prepare'): finished}
            with patch.object(gui, '_OWNED_JOBS', owned), \
                 patch.object(gui, '_release_test_worker') as release, \
                 patch.object(gui, '_job_files', return_value=(status, Path(tmp)/'log')), \
                 patch.object(gui.subprocess, 'run') as kill:
                gui._shutdown_jobs()
                release.assert_called_once()
                kill.assert_called_once()
                self.assertEqual(kill.call_args.args[0], ['taskkill.exe', '/PID', '123', '/T', '/F'])
                running.wait.assert_called_once()
                finished.wait.assert_not_called()
                self.assertEqual(owned, {})
                self.assertIn('stopped', status.read_text(encoding='utf-8'))

    def test_release_waits_for_worker_and_clears_reference(self):
        worker = Mock()
        with patch.object(gui, '_TEST_WORKER', worker):
            gui._release_test_worker()
            worker.stop.assert_called_once()
            self.assertIsNone(gui._TEST_WORKER)


if __name__ == '__main__':
    unittest.main()
