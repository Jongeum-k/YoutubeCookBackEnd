#!/usr/bin/env python3
"""Manual test client for the /ws/analyze-video endpoint.

Usage:
    uv run python scripts/test_analyze_video.py <tester_key> <youtube_url> <ko|en>

Example (walks through all four branches for one video):

    uv run python scripts/test_analyze_video.py mykey https://youtu.be/XXXXXXXXXXX ko
    uv run python scripts/test_analyze_video.py mykey https://youtu.be/XXXXXXXXXXX ko   # cache hit
    uv run python scripts/test_analyze_video.py mykey https://youtu.be/XXXXXXXXXXX en   # translation
    uv run python scripts/test_analyze_video.py mykey https://youtu.be/XXXXXXXXXXX en   # cache hit
"""

import asyncio
import json
import sys

import websockets

WS_URL = "ws://localhost:8000/api/v1/ws/analyze-video"


async def main(tester_key: str, youtube_url: str, language: str) -> None:
    async with websockets.connect(WS_URL) as ws:
        await ws.send(
            json.dumps(
                {
                    "tester_key": tester_key,
                    "youtube_url": youtube_url,
                    "language": language,
                }
            )
        )

        delta_count = 0

        async for raw in ws:
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "delta":
                delta_count += 1
                continue

            if delta_count:
                print(f"[delta] {delta_count} chunk(s) streamed")
                delta_count = 0

            if msg_type == "completed":
                print(f"[completed] cached={message.get('cached')} model={message.get('model')}")
                print(json.dumps(message["data"]["basic_info"], ensure_ascii=False, indent=2))
                print(f"ingredients: {len(message['data']['ingredients'])}")
                print(f"steps: {len(message['data']['steps'])}")
                if message.get("cost"):
                    print(f"cost_usd: {message['cost']['total_usd']}")
            else:
                print(f"[{msg_type}] {message}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(1)

    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
