"""compa — pick a language and what to do. compa <language> starts a call straight away; Ctrl-C hangs up."""
import argparse
import asyncio
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
from compa.progress import Weakness, estimated_level, grades, weaknesses
from compa.report import Reporter
from compa.screen import Screen
from compa.session_file import save_call
from compa.settings import load_profile, profile_names
from compa.topics import WORDS_FOR_COVERED, TopicMemory
from compa.speak import Speaker

CACHE = Path("~/.cache/compa").expanduser()
MENU_LESSONS = 3


def main() -> None:
    arguments = _arguments()
    profile = load_profile(arguments.language or _ask_language())
    topics = TopicMemory(profile.sessions_folder, profile.language)
    if arguments.topics:
        _print_topics(topics)
    elif arguments.report:
        _print_report(profile, topics)
    elif arguments.lesson:
        _start_call(profile, topics, arguments, lesson=_matching_weakness(profile, arguments.lesson))
    elif arguments.language or arguments.topic:
        _start_call(profile, topics, arguments)
    else:
        _menu(profile, topics, arguments)


def _ask_language() -> str:
    names = profile_names()
    print("🤠 Compa\n")
    for number, name in enumerate(names, 1):
        print(f"  {number}. {name.capitalize()}")
    return names[_ask_number("\nWhich language? ", len(names)) - 1]


def _menu(profile, topics: TopicMemory, arguments: argparse.Namespace) -> None:
    """Pick what to do: a call, a lesson on a recurring mistake, or a look at your progress."""
    while True:
        level = estimated_level(grades(profile.sessions_folder, profile.language))
        lessons = weaknesses(profile.sessions_folder, profile.language)[:MENU_LESSONS]
        topic = topics.next_topic()
        calls = len(grades(profile.sessions_folder, profile.language))
        print(f"\n🤠 {profile.language_name}" + (f" · your level ≈ {level} (from {calls} calls)" if level else ""))
        options = [(f"Start a call (today's topic: {topic})", lambda: _start_call(profile, topics, arguments, topic=topic))]
        options += [(f"Lesson: {weakness.pattern} (in {weakness.calls} calls)",
                     lambda weakness=weakness: _start_call(profile, topics, arguments, lesson=weakness))
                    for weakness in lessons]
        options += [("Progress and last report card", lambda: _print_report(profile, topics)),
                    ("Topics", lambda: _print_topics(topics))]
        for number, (label, _) in enumerate(options, 1):
            print(f"  {number}. {label}")
        choice = _ask_number("\nWhat now? (Enter to quit) ", len(options), allow_empty=True)
        if choice is None:
            return
        label, action = options[choice - 1]
        action()
        if label.startswith(("Start", "Lesson")):
            return


def _ask_number(question: str, highest: int, allow_empty: bool = False) -> int | None:
    while True:
        answer = input(question).strip()
        if not answer and allow_empty:
            return None
        if answer.isdigit() and 1 <= int(answer) <= highest:
            return int(answer)


def _start_call(profile, topics: TopicMemory, arguments: argparse.Namespace, topic: str | None = None,
                lesson: Weakness | None = None) -> None:
    account = use_claude_account(profile)
    with Screen() as screen:
        screen.console.print(f"🤠 Compa · {profile.language_name} · Claude: {account}", style="dim")
        mic = arguments.mic or _built_in_mic()
        listener = Listener(MicSource(mic), profile.language, profile.whisper_prompt, arguments.end_silence)
        conversation = Conversation(listener, Speaker(profile.voice), screen, Brain.for_profile(profile, CACHE))
        if lesson:
            conversation.talker.set_lesson(lesson.pattern, lesson.examples)
            screen.console.print(f"   🎓 Lesson: {lesson.pattern}", style="dim")
        else:
            topic = topic or (_matching_topic(topics, arguments.topic) if arguments.topic else topics.next_topic())
            conversation.talker.set_focus(topic, topics.words(topic))
            screen.console.print(f"   🎯 Today's topic: {topic} ({len(topics.words(topic))}/{WORDS_FOR_COVERED} words)",
                                 style="dim")
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
        _print_lessons(profile)
    except KeyboardInterrupt:
        card = None
    path = save_call(profile.sessions_folder, profile.language_name, conversation.talker.history, conversation.log, card)
    screen.console.print(f"Saved to {path}", style="dim")


def _matching_weakness(profile, wanted: str) -> Weakness:
    """A recurring mistake whose id or name contains the words asked for, else a lesson on the words as given."""
    found = weaknesses(profile.sessions_folder, profile.language)
    lowered = wanted.lower()
    return next((weakness for weakness in found if lowered in weakness.id.lower() or lowered in weakness.pattern.lower()),
                Weakness(wanted, wanted, 0, []))


def _print_lessons(profile) -> None:
    lessons = weaknesses(profile.sessions_folder, profile.language)[:MENU_LESSONS]
    if lessons:
        print("\nWork on:")
        for weakness in lessons:
            print(f"  • {weakness.pattern} (in {weakness.calls} calls) → compa {profile.language_name.lower()} "
                  f"--lesson {weakness.id}")


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
    past = grades(profile.sessions_folder, profile.language)
    if not past:
        console.print(f"No {profile.language_name} calls yet.")
        return
    console.print(f"[bold]{profile.language_name}[/] · your level ≈ {estimated_level(past)} · {len(past)} calls · grades: "
                  + " → ".join(str(grade["overall"]) for grade in past[-10:]))
    covered = sum(len(topics.words(topic)) >= WORDS_FOR_COVERED for topic in topics.all_topics())
    started = sum(bool(topics.words(topic)) for topic in topics.all_topics())
    console.print(f"Topics: {covered} covered, {started} started, of {len(topics.all_topics())} (compa --topics)\n")
    calls = sorted(profile.sessions_folder.glob(f"* {profile.language_name}*.md"))
    if calls:
        card = calls[-1].read_text().split("# Conversation")[0]
        console.print(Markdown(card))
        console.print(f"\n{calls[-1]}", style="dim")
    _print_lessons(profile)


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
    parser.add_argument("--lesson", help='a lesson on a mistake you keep making, e.g. "subjuntivo" or an id from --report')
    parser.add_argument("--report", action="store_true", help="show your grades over time and the latest report card")
    parser.add_argument("--topics", action="store_true", help="list every topic and how many of its words you've used")
    parser.add_argument("--mic", help="input device name or index (default: the MacBook microphone, else the system input)")
    parser.add_argument("--end-silence", type=float, default=1.0,
                        help="seconds of silence that end your turn (raise it if Compa jumps in mid-thought)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
