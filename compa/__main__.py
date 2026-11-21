"""compa [language] — start a voice call. Ctrl-C hangs up and saves the call."""
import argparse
import asyncio
import json
import os
import warnings
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
warnings.filterwarnings("ignore")

from rich.console import Console
from rich.markdown import Markdown

from compa.account import use_claude_account
from compa.conversation import Brain, Conversation
from compa.listen import Listener, MicSource
from compa.report import Reporter
from compa.screen import Screen
from compa.session_file import save_call
from compa.settings import load_profile, profile_names
from compa.topics import WORDS_FOR_COVERED, TopicMemory
from compa.speak import Speaker

CACHE = Path("~/.cache/compa").expanduser()


def main() -> None:
    arguments = _arguments()
    profile = load_profile(arguments.language)
    topics = TopicMemory(profile.sessions_folder, profile.language)
    if arguments.topics:
        _print_topics(topics)
        return
    if arguments.report:
        _print_report(profile, topics)
        return
    account = use_claude_account(profile)
    with Screen() as screen:
        screen.console.print(f"🤠 Compa · {profile.language_name} · Claude: {account}", style="dim")
        mic = arguments.mic or _built_in_mic()
        listener = Listener(MicSource(mic), profile.language, profile.whisper_prompt, arguments.end_silence)
        conversation = Conversation(listener, Speaker(profile.voice), screen, Brain.for_profile(profile, CACHE))
        topic = _matching_topic(topics, arguments.topic) if arguments.topic else topics.next_topic()
        conversation.talker.set_focus(topic, topics.words(topic))
        screen.console.print(f"   🎯 Today's topic: {topic} ({len(topics.words(topic))}/{WORDS_FOR_COVERED} words)", style="dim")
        try:
            asyncio.run(_call(conversation))
        except KeyboardInterrupt:
            pass
    if not conversation.log.turns:
        return
    screen.console.print("\n👋 Writing your report card (about 20s, Ctrl-C again to skip it)…", style="dim")
    try:
        card = asyncio.run(Reporter(profile).report(conversation.talker.history, conversation.log))
        screen.report_card(card)
    except KeyboardInterrupt:
        card = None
    path = save_call(profile.sessions_folder, profile.language_name, conversation.talker.history, conversation.log, card)
    screen.console.print(f"Saved to {path}", style="dim")


def _matching_topic(topics: TopicMemory, wanted: str) -> str:
    """A listed topic containing the words asked for ("fishing" → "fishing and hunting"), else the words as given."""
    return next((topic for topic in topics.all_topics() if wanted.lower() in topic.lower()), wanted)


def _print_topics(topics: TopicMemory) -> None:
    for topic in topics.all_topics():
        used = len(topics.words(topic))
        mark = "✓" if used >= WORDS_FOR_COVERED else ("·" if used else " ")
        print(f"{mark} {topic:<40} {min(used, WORDS_FOR_COVERED):>2}/{WORDS_FOR_COVERED}")


def _print_report(profile, topics: TopicMemory) -> None:
    """Your grade over time, how far through the topics you are, and the latest call's report card."""
    console = Console()
    grades_file = profile.sessions_folder / f"grades-{profile.language}.json"
    grades = json.loads(grades_file.read_text()) if grades_file.exists() else []
    if not grades:
        console.print(f"No {profile.language_name} calls yet.")
        return
    console.print(f"[bold]{profile.language_name}[/] · {len(grades)} calls · grades: "
                  + " → ".join(str(grade["overall"]) for grade in grades[-10:]))
    covered = sum(len(topics.words(topic)) >= WORDS_FOR_COVERED for topic in topics.all_topics())
    started = sum(bool(topics.words(topic)) for topic in topics.all_topics())
    console.print(f"Topics: {covered} covered, {started} started, of {len(topics.all_topics())} (compa --topics)\n")
    calls = sorted(profile.sessions_folder.glob(f"* {profile.language_name}*.md"))
    if calls:
        card = calls[-1].read_text().split("# Conversation")[0]
        console.print(Markdown(card))
        console.print(f"\n{calls[-1]}", style="dim")


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
    parser.add_argument("--topic", help='talk about this topic today, e.g. "fishing" (default: one you haven\'t covered)')
    parser.add_argument("--report", action="store_true", help="show your grades over time and the latest report card")
    parser.add_argument("--topics", action="store_true", help="list every topic and how many of its words you've used")
    parser.add_argument("--mic", help="input device name or index (default: the MacBook microphone, else the system input)")
    parser.add_argument("--end-silence", type=float, default=1.0,
                        help="seconds of silence that end your turn (raise it if Compa jumps in mid-thought)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
