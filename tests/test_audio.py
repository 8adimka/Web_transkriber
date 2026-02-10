#!/usr/bin/env python3
import asyncio
import json
import os
import subprocess
import tempfile

import websockets


async def test():
    # Генерируем 1 секунду синусоиды 440Hz в формате WebM/Opus
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        webm_path = f.name

    try:
        # Используем ffmpeg для генерации тестового аудио
        cmd = [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "libopus",
            "-b:a",
            "64k",
            "-f",
            "webm",
            webm_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        subprocess.run(cmd, check=True)

        # Читаем сгенерированный файл
        with open(webm_path, "rb") as f:
            webm_data = f.read()

        print(f"Generated WebM size: {len(webm_data)} bytes")

        # Подключаемся к WebSocket
        uri = "ws://localhost:8000/ws/stream"
        async with websockets.connect(uri) as ws:
            print("Connected")
            # Send start command
            await ws.send(json.dumps({"type": "start", "sample_rate": 48000}))
            print("Sent start")

            # Send WebM chunk
            await ws.send(webm_data)
            print("Sent audio chunk")

            # Wait for responses for 10 seconds
            for i in range(10):
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(response)
                    print(f"Received: {data}")
                    if (
                        data.get("type") == "transcript"
                        and data.get("text", "").strip()
                    ):
                        print(f"SUCCESS: Got transcript: {data['text']}")
                        break
                except asyncio.TimeoutError:
                    print(f"Waiting... {i + 1}")

            # Send stop
            await ws.send(json.dumps({"type": "stop"}))
            print("Sent stop")

    finally:
        if os.path.exists(webm_path):
            os.unlink(webm_path)


if __name__ == "__main__":
    asyncio.run(test())
