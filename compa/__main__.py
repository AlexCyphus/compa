"""compa [language] — start a voice call. Ctrl-C hangs up and saves the call."""
import argparse
import asyncio
import os
import warnings
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
warnings.filterwarnings("ignore")

from compa.account import use_claude_account
from compa.conversation import Brain, Conversation
from compa.listen import Listener, MicSource
from compa.report import Reporter
from compa.screen import Screen
from compa.session_file import save_call
from compa.settings import load_profile, profile_names
from compa.speak import Speaker

CACHE = Path("~/.cache/compa").expanduser()


def main() -> None:
    arguments = _arguments()
    profile = load_profile(arguments.language)
    account = use_claude_account(profile)
    with Screen() as screen:
        screen.console.print(f"🤠 Compa · {profile.language_name} · Claude: {account}", style="dim")
        mic = arguments.mic or _built_in_mic()
        listener = Listener(MicSource(mic), profile.language, profile.whisper_prompt, arguments.end_silence)
        conversation = Conversation(listener, Speaker(profile.voice), screen, Brain.for_profile(profile, CACHE))
        try:
            asyncio.run(_call(conversation))
        except KeyboardInterrupt:
            pass
    if not conversation.log.turns:
        return
    screen.console.print("\n👋 Writing your report card…", style="dim")
    card = asyncio.run(Reporter(profile).report(conversation.talker.history, conversation.log))
    screen.report_card(card)
    path = save_call(profile.sessions_folder, profile.language_name, conversation.talker.history, conversation.log, card)
    screen.console.print(f"Saved to {path}", style="dim")


def _built_in_mic() -> str | None:
    """The laptop mic, so Bluetooth headphones stay in high-quality playback mode instead of switching to headset mode."""
    import sounddevice

    names = [device["name"] for device in sounddevice.query_devices() if device["max_input_channels"] > 0]
    return next((name for name in names if "MacBook" in name and "Microphone" in name), None)


async def _call(conversation: Conversation) -> None:
    try:
        await conversation.run()
    finally:
        await conversation.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="compa", description="Voice chat practice partner.")
    parser.add_argument("language", nargs="?", choices=profile_names(), help="language profile from settings.json")
    parser.add_argument("--mic", help="input device name or index (default: the MacBook microphone, else the system input)")
    parser.add_argument("--end-silence", type=float, default=1.0,
                        help="seconds of silence that end your turn (raise it if Compa jumps in mid-thought)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
