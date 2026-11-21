"""compa — pick a language and what to do. compa <language> starts a call straight away; Ctrl-C hangs up."""
import argparse
import asyncio
import os
import warnings
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
warnings.filterwarnings("ignore")

from rich.console import Console
from rich.text import Text

from compa.account import use_claude_account
from compa.brain import ClaudeUnavailable
from compa.cards import ACCENT, MUTED, progress_card
from compa.conversation import Brain, Conversation
from compa.listen import Listener, MicSource
from compa.menu import pick
from compa.progress import Weakness, estimated_level, grades, weaknesses
from compa.report import ReportCard, Reporter
from compa.screen import Screen
from compa.session_file import save_call
from compa.settings import load_profile, profile_names
from compa.topics import WORDS_FOR_COVERED, TopicMemory
from compa.speak import Speaker

CACHE = Path("~/.cache/compa").expanduser()
NEXT_LESSONS = 3
CALL, LESSON, PROGRESS = "call", "lesson", "progress"


def main() -> None:
    arguments = _arguments()
    language = arguments.language or _ask_language()
    if language is None:
        return
    profile = load_profile(language)
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


def _ask_language() -> str | None:
    """The chosen profile name, each one shown with its level; None to quit."""
    print()
    return pick("Language", [(_language_label(name), name) for name in profile_names()])


def _language_label(name: str) -> str:
    profile = load_profile(name)
    level = estimated_level(grades(profile.sessions_folder, profile.language))
    return f"{profile.language_name:<12}{level or ''}"


def _menu(profile, topics: TopicMemory, arguments: argparse.Namespace) -> None:
    """Pick what to do: a call, a lesson on a recurring mistake, or a look at your progress. Esc quits."""
    while True:
        choice = pick("What now?", [("Start a call", CALL), ("Lesson to improve on a weakness", LESSON),
                                    ("Progress", PROGRESS)])
        if choice is None:
            return
        if choice == PROGRESS:
            _print_report(profile, topics)
            continue
        lesson = _pick_weakness(profile) if choice == LESSON else None
        if choice == LESSON and lesson is None:
            continue
        _start_call(profile, topics, arguments, lesson=lesson)
        return


def _pick_weakness(profile) -> Weakness | None:
    """A recurring mistake to have a lesson on; None to go back to the menu."""
    found = weaknesses(profile.sessions_folder, profile.language)
    if not found:
        Console().print(Text("  No weaknesses yet. They show up after your first call.\n", style=MUTED))
        return None
    return pick("Which one?", [(weakness.pattern, weakness) for weakness in found] + [("← Back", None)])


def _start_call(profile, topics: TopicMemory, arguments: argparse.Namespace, lesson: Weakness | None = None) -> None:
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
            topic = _matching_topic(topics, arguments.topic) if arguments.topic else topics.next_topic()
            conversation.talker.set_focus(topic, topics.words(topic))
            screen.console.print(f"   🎯 Today's topic: {topic} ({len(topics.words(topic))}/{WORDS_FOR_COVERED} words)",
                                 style="dim")
        try:
            asyncio.run(_call(conversation))
        except KeyboardInterrupt:
            pass
    if not conversation.log.turns:
        return
    if conversation.unavailable:
        screen.console.print("   Your call is saved, but there's no report card this time: it needs Claude too.", style="dim")
    card = None if conversation.unavailable else _report_card(profile, conversation, screen)
    path = save_call(profile.sessions_folder, profile.language_name, conversation.talker.history, conversation.log, card)
    screen.console.print(Text(f"  Saved to {path}\n", style=MUTED))
    lesson = _pick_next_lesson(profile) if card else None
    if lesson:
        _start_call(profile, topics, arguments, lesson=lesson)


def _report_card(profile, conversation: Conversation, screen: Screen) -> ReportCard | None:
    print()
    try:
        with screen.console.status(Text("Writing your report card  ·  Ctrl-C to skip", style=MUTED),
                                   spinner_style=ACCENT):
            card = asyncio.run(Reporter(profile).report(conversation.talker.history, conversation.log))
    except KeyboardInterrupt:
        return None
    except ClaudeUnavailable as reason:
        screen.claude_unavailable(reason)
        return None
    screen.report_card(card, profile.language_name, estimated_level(grades(profile.sessions_folder, profile.language)))
    return card


def _pick_next_lesson(profile) -> Weakness | None:
    """After the report card: a lesson on one of the top recurring mistakes, or None to finish."""
    lessons = weaknesses(profile.sessions_folder, profile.language)[:NEXT_LESSONS]
    if not lessons:
        return None
    return pick("Next", [(f"Lesson: {weakness.pattern}", weakness) for weakness in lessons] + [("Done", None)])


def _matching_weakness(profile, wanted: str) -> Weakness:
    """A recurring mistake whose id or name contains the words asked for, else a lesson on the words as given."""
    found = weaknesses(profile.sessions_folder, profile.language)
    lowered = wanted.lower()
    return next((weakness for weakness in found if lowered in weakness.id.lower() or lowered in weakness.pattern.lower()),
                Weakness(wanted, wanted, 0, []))


def _matching_topic(topics: TopicMemory, wanted: str) -> str:
    """A listed topic containing the words asked for ("fishing" → "fishing and hunting"), else the words as given."""
    return next((topic for topic in topics.all_topics() if wanted.lower() in topic.lower()), wanted)


def _print_topics(topics: TopicMemory) -> None:
    for topic in topics.all_topics():
        used = len(topics.words(topic))
        mark = "✓" if used >= WORDS_FOR_COVERED else ("·" if used else " ")
        print(f"{mark} {topic:<40} {min(used, WORDS_FOR_COVERED):>2}/{WORDS_FOR_COVERED}")


def _print_report(profile, topics: TopicMemory) -> None:
    """Your level, how your grade has gone, the latest scores and the mistakes to work on."""
    console = Console()
    past = grades(profile.sessions_folder, profile.language)
    if not past:
        console.print(Text(f"\n  No {profile.language_name} calls yet.\n", style=MUTED))
        return
    covered = sum(len(topics.words(topic)) >= WORDS_FOR_COVERED for topic in topics.all_topics())
    started = sum(bool(topics.words(topic)) for topic in topics.all_topics())
    console.print(progress_card(profile.language_name, estimated_level(past), past,
                                weaknesses(profile.sessions_folder, profile.language), covered, started))


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
    parser.add_argument("--lesson", help='a lesson on a mistake you keep making, e.g. "subjuntivo"')
    parser.add_argument("--report", action="store_true", help="show your level, your grade over time and what to work on")
    parser.add_argument("--topics", action="store_true", help="list every topic and how many of its words you've used")
    parser.add_argument("--mic", help="input device name or index (default: the MacBook microphone, else the system input)")
    parser.add_argument("--end-silence", type=float, default=1.0,
                        help="seconds of silence that end your turn (raise it if Compa jumps in mid-thought)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
