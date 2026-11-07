"""Synthetic finalization and persistence tests; no microphone or provider calls.

    python -m unittest discover -s tests -p test_translation_session.py -v
"""

import asyncio
import json
import shutil
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.services.transcriber.app import audio_processor as audio
from backend.services.transcriber.app import database, main, session_manager


class ClientSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class Decoder:
    def __init__(self):
        self.output = asyncio.Queue()
        self.stopped = False

    async def start(self):
        pass

    async def write(self, data):
        await self.output.put(b"pcm:" + data)

    async def read(self, _size):
        return await self.output.get()

    async def finish_input(self):
        await self.output.put(b"last decoded samples")
        await self.output.put(b"")

    async def stop(self):
        self.stopped = True


class Translator:
    def __init__(self):
        self.closed = False

    async def start(self):
        pass

    async def stop(self):
        self.closed = True

    async def translate(self, text, _source, _target, user_id=None):
        return "Translated " + text


class ProviderSocket:
    def __init__(self, final="last phrase", never_finish=False):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.final = final
        self.never_finish = never_finish
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.close()

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.incoming.get()
        if message is None:
            raise StopAsyncIteration
        return message

    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data).get("type") == "CloseStream" and not self.never_finish:
            await self.incoming.put(json.dumps({
                "type": "Results", "is_final": True,
                "channel": {"alternatives": [{"transcript": self.final}]},
            }))
            await self.incoming.put(None)

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.incoming.put(None)


@unittest.skipUnless(shutil.which("ffmpeg"), "requires FFmpeg")
class DecoderTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_ffmpeg_drains_synthetic_webm_after_input_eof(self):
        generator = await asyncio.create_subprocess_exec(
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-c:a", "libopus", "-f", "webm", "-loglevel", "error", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        webm, error = await generator.communicate()
        self.assertEqual(generator.returncode, 0, error.decode())
        decoder = audio.FFmpegStreamer()
        await decoder.start()

        async def read_all():
            pieces = []
            while data := await decoder.read(3200):
                pieces.append(data)
            return b"".join(pieces)

        reader = asyncio.create_task(read_all())
        try:
            await decoder.write(webm)
            await decoder.finish_input()
            pcm = await asyncio.wait_for(reader, timeout=3)
            self.assertGreaterEqual(len(pcm), 3000)
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            await decoder.stop()
        self.assertIsNone(decoder.process)


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.provider_sockets = []
        self.final = "last phrase"
        self.never_finish = False

        def connect(*_args, **_kwargs):
            socket = ProviderSocket(self.final, self.never_finish)
            self.provider_sockets.append(socket)
            return socket

        self.patches = [
            patch.object(audio, "FFmpegStreamer", Decoder),
            patch.object(audio, "TranslationService", Translator),
            patch.object(audio, "ws_connect", connect),
            patch.object(audio, "get_token_tracker", return_value=AsyncMock()),
            patch.object(database, "SessionLocal", self.sessions),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.engine.dispose)
        self.manager = session_manager.SessionManager()

    async def start(self, mode="translation", owner="7"):
        client = ClientSocket()
        session = self.manager.create(client, owner)
        await self.manager.start_worker(session, mode=mode, language="EN", source_lang="EN", target_lang="RU")
        await self.manager.handle_audio_chunk(session, b"\x01synthetic webm")
        return session, client

    def saved(self):
        with self.sessions() as db:
            return db.execute(select(database.Transcription)).scalars().all()

    async def test_final_phrase_is_saved_before_done_and_download_matches_history(self):
        session, client = await self.start()
        await self.manager.stop_session(session, language="EN", translate_to="RU")
        done = client.messages[-1]
        self.assertEqual(done["type"], "done")
        self.assertTrue(done["saved"])
        self.assertFalse(done["incomplete"])
        record = self.saved()[0]
        self.assertEqual(record.content, "TRANSLATION\n\nTranslated last phrase")
        self.assertEqual(record.user_id, 7)
        self.assertEqual(record.translate_to, "RU")
        self.assertEqual(self.provider_sockets[0].sent[-2:],
                         [b"last decoded samples", json.dumps({"type": "CloseStream"})])
        self.assertTrue(session.processor.translation_service.closed)
        self.assertTrue(all(stream.stopped for stream in session.processor.ffmpeg_streams))
        with self.sessions() as db, patch.object(main, "verify_token", return_value={"sub": "7"}):
            history = main.get_transcriptions(skip=0, limit=10, token="synthetic", db=db)
            download = main.download_transcription(record.id, token="synthetic", db=db)
            self.assertEqual(history.transcriptions[0].content, record.content)
            self.assertEqual(download.body.decode(), record.content)
        with self.sessions() as db, patch.object(main, "verify_token", return_value={"sub": "8"}):
            with self.assertRaises(main.HTTPException) as error:
                main.download_transcription(record.id, token="synthetic", db=db)
            self.assertEqual(error.exception.status_code, 404)

    async def test_duplicate_stop_does_not_duplicate_saved_text(self):
        session, client = await self.start()
        await asyncio.gather(self.manager.stop_session(session), self.manager.stop_session(session))
        self.assertEqual(len(self.saved()), 1)
        self.assertEqual(sum(message["type"] == "done" for message in client.messages), 1)

    async def test_empty_translation_is_not_saved(self):
        self.final = ""
        session, client = await self.start()
        await self.manager.stop_session(session)
        self.assertFalse(client.messages[-1]["saved"])
        self.assertTrue(client.messages[-1]["empty"])
        self.assertNotIn("download_url", client.messages[-1])
        self.assertEqual(self.saved(), [])

    async def test_timeout_preserves_received_text_and_reports_incomplete(self):
        self.never_finish = True
        session, client = await self.start()
        session.processor.stop_timeout = 0.02
        session.append_translation("Earlier final phrase")
        await self.manager.stop_session(session)
        self.assertTrue(client.messages[-1]["incomplete"])
        self.assertTrue(client.messages[-1]["saved"])
        self.assertIn("Earlier final phrase", self.saved()[0].content)
        self.assertTrue(all(task.done() for task in session.processor.sender_tasks))

    async def test_save_failure_is_explicit_and_has_no_download_url(self):
        session, client = await self.start()
        with patch.object(session, "save_to_db", new=AsyncMock(side_effect=RuntimeError("synthetic DB outage"))):
            await self.manager.stop_session(session)
        self.assertEqual(client.messages[-2]["code"], "save_failed")
        self.assertFalse(client.messages[-1]["saved"])
        self.assertNotIn("download_url", client.messages[-1])
        self.assertEqual(session.translation_log, ["Translated last phrase"])

    async def test_stopping_one_session_does_not_close_the_other_translator(self):
        first, _ = await self.start()
        second, client = await self.start(owner="8")
        self.assertIsNot(first.processor.translation_service, second.processor.translation_service)
        await self.manager.stop_session(first)
        self.assertFalse(second.processor.translation_service.closed)
        await self.manager.handle_audio_chunk(second, b"\x01more synthetic webm")
        await self.manager.stop_session(second)
        self.assertTrue(client.messages[-1]["saved"])
        self.assertEqual(len(self.saved()), 2)

    async def test_transcription_still_saves_both_sources(self):
        session, client = await self.start(mode="transcription")
        await self.manager.stop_session(session)
        self.assertTrue(client.messages[-1]["saved"])
        self.assertEqual(len(session.transcript_log), 2)
        self.assertIn("Translated last phrase", self.saved()[0].content)


if __name__ == "__main__":
    unittest.main()
