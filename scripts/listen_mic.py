"""Print listen events live from the microphone: .venv/bin/python scripts/listen_mic.py [profile] [device]"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compa.listen import Listener, MicSource  # noqa: E402
from compa.settings import load_profile  # noqa: E402


async def main():
    profile = load_profile(sys.argv[1] if len(sys.argv) > 1 else None)
    device = sys.argv[2] if len(sys.argv) > 2 else None
    listener = Listener(MicSource(int(device) if device and device.isdigit() else device), profile.language, profile.whisper_prompt)
    await listener.warm_up()
    print(f"Listening ({profile.language}), Ctrl+C to stop")
    started = time.monotonic()
    async for event in listener.events():
        print(f"{time.monotonic() - started:6.2f}s  {event}", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
