#!/usr/bin/env python3
import asyncio
import json

import websockets


async def test_websocket():
    uri = "ws://localhost:8000/ws/stream"
    async with websockets.connect(uri) as websocket:
        print("Connected")
        # Send start command
        await websocket.send(json.dumps({"type": "start", "sample_rate": 16000}))
        print("Sent start")

        # Send a small audio chunk (silence)
        # 3200 bytes of zeros (100ms of silence at 16kHz mono 16bit)
        silence = bytes([0] * 3200)
        await websocket.send(silence)
        print("Sent audio chunk")

        # Wait for response
        try:
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(response)
            print(f"Received: {data}")
        except asyncio.TimeoutError:
            print("No response received")

        # Send stop
        await websocket.send(json.dumps({"type": "stop"}))
        print("Sent stop")


if __name__ == "__main__":
    asyncio.run(test_websocket())
