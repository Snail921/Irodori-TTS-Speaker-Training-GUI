import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import speaker_training_gui as gui
from speaker_training_job_runner import LogMirror


class DiagnosticsTests(unittest.TestCase):
    def test_log_mirror_prints_new_bytes_once_and_drains_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); status=root/'status'; log=root/'log'
            status.write_text('{"state":"running"}',encoding='utf-8')
            log.write_text('first\n',encoding='utf-8')
            console=io.StringIO()
            with contextlib.redirect_stdout(console):
                mirror=LogMirror(status,log,'test')
                time.sleep(0.3)
                with log.open('a',encoding='utf-8') as handle: handle.write('second\n')
                status.write_text('{"state":"completed"}',encoding='utf-8')
                mirror.thread.join(timeout=3)
                mirror.stop()
            self.assertEqual(console.getvalue().count('first'),1)
            self.assertEqual(console.getvalue().count('second'),1)

    def test_media_diagnostics_record_range_and_disconnect(self):
        async def app(scope, receive, send):
            await receive()
            await send({'type':'http.response.start','status':206})
            await send({'type':'http.response.body','body':b'audio'})
        async def receive(): return {'type':'http.disconnect'}
        async def send(message): pass
        with patch.object(gui,'_network_log') as log:
            asyncio.run(gui.NetworkDiagnostics(app)(
                {'type':'http','client':('127.0.0.1',321),'method':'GET','path':'/gradio_api/file=test.wav','headers':[(b'range',b'bytes=0-4')]},receive,send))
            messages=[call.args[0] for call in log.call_args_list]
            self.assertTrue(any('disconnect' in m and 'bytes=0-4' in m for m in messages))
            self.assertTrue(any('status=206 bytes=5' in m for m in messages))

    def test_queue_stream_disconnect_is_not_logged(self):
        async def app(scope, receive, send):
            await receive()
        async def receive(): return {'type':'http.disconnect'}
        async def send(message): pass
        with patch.object(gui,'_network_log') as log:
            asyncio.run(gui.NetworkDiagnostics(app)(
                {'type':'http','client':('127.0.0.1',321),'method':'GET',
                 'path':'/gradio_api/queue/data','headers':[]},receive,send))
            log.assert_not_called()

    def test_exception_is_logged_and_forwarded_without_suppression(self):
        loop=Mock(); previous=Mock()
        transport=Mock(); transport.get_extra_info.return_value=('127.0.0.1',321)
        ctx={'transport':transport,'exception':ConnectionResetError(10054,'reset')}
        with patch.object(gui,'_network_log') as log:
            gui._network_exception(loop,ctx,previous)
            self.assertIn('10054',log.call_args.args[0])
            previous.assert_called_once_with(loop,ctx)


if __name__=='__main__': unittest.main()
