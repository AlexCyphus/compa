"""compa — pick a language and what to do. compa <language> starts a call straight away; Ctrl-C hangs up."""
import argparse
import asyncio
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
warnings.filterwarnings("ignore")

from rich.console import Console
from rich.text import Text

from compa.account import use_claude_account
from compa.brain import ClaudeUnavailable
from compa.cards import LEVEL_NAMES, progress_card
from compa.catalog import add_language, addable_languages, flag, flag_for_code
from compa.conversation import Brain, Conversation
from compa.friend_memory import FriendMemory
from compa.listen import Listener, MicSource
from compa.menu import pick
from compa.progress import Weakness, estimated_level, grades, weaknesses
from compa.report import ReportCard, Reporter
from compa.screen import Screen
from compa.session_file import save_call
from compa.settings import load_profile, profile_names
from compa.speak import Speaker
from compa.theme import MUTED, TEXT, indented, print_header, show_screen
from compa.topics import WORDS_FOR_COVERED, TopicMemory

CACHE = Path("~/.cache/compa").expanduser()
CONSOLE = Console(file=sys.stdout, highlight=False)  # fixed, so stdout redirects elsewhere can't swallow it
NEXT_LESSONS = 3
CALL, LESSON, PROGRESS, BACK, ADD = "call", "lesson", "progress", "back", "add"
MENU, LANGUAGES, QUIT = "menu", "languages", "quit"


def main() -> None:
    try:
        _run(_arguments())
    except KeyboardInterrupt:
        pass  # Ctrl-C outside a call quits quietly, wherever it lands


def _run(arguments: argparse.Namespace) -> None:
    language = arguments.language
    if arguments.topics or arguments.report:
        profile = load_profile(language or _ask_language())
        _print_once(profile, arguments)
        return
    first_step = (_matching_weakness(load_profile(language), arguments.lesson) if arguments.lesson
                  else CALL if language or arguments.topic else None)
    while True:
        language = language or _ask_language()
        if language is None:
            return
        if _menu(load_profile(language), arguments, first_step) == QUIT:
            return
        language, first_step = None, None


def _print_once(profile, arguments: argparse.Namespace) -> None:
    topics = TopicMemory(profile.sessions_folder, profile.language)
    if arguments.topics:
        _print_topics(topics)
    else:
        print_header(CONSOLE, f"{_language_title(profile)} · progress", "Here's how you're coming along.")
        _print_report(profile, topics)


def _ask_language() -> str | None:
    """The chosen profile name, or one just added; None to quit."""
    while True:
        show_screen(CONSOLE, "", "Howdy! Which language are we speaking today?")
        choice = pick("Language", [(_language_label(name), name) for name in profile_names()]
                      + [("＋  Add language", ADD)])
        if choice != ADD:
            return choice
        added = _add_language()
        if added:
            return added


def _language_label(name: str) -> str:
    profile = load_profile(name)
    level = estimated_level(grades(profile.sessions_folder, profile.language))
    return f"{flag(name) or '  '}  {profile.language_name:<12}{level or ''}"


def _add_language() -> str | None:
    """Pick a language from the catalog and your level in it, then save it as a profile; None to go back."""
    show_screen(CONSOLE, "add language", "Saddle up a new one. Which language?")
    language = pick("Add a language", [(f"{language.flag}  {language.name}", language)
                                       for language in addable_languages()] + [("← Back", BACK)])
    if language in (None, BACK):
        return None
    show_screen(CONSOLE, f"add {language.name}", f"How well do you speak {language.name} already?")
    level = pick(f"Your {language.name} level", [(f"{level}  {name}", level) for level, name in LEVEL_NAMES.items()]
                 + [("← Back", BACK)])
    if level in (None, BACK):
        return None
    add_language(language.key, level)
    return language.key


def _menu(profile, arguments: argparse.Namespace, step=None) -> str:
    """The language's menu and everything reachable from it. Returns LANGUAGES to pick another language, or QUIT.

    step is what to do next: None shows the menu, CALL starts a call, a Weakness starts a lesson on it."""
    topics = TopicMemory(profile.sessions_folder, profile.language)
    while True:
        if step is None:
            show_screen(CONSOLE, _language_context(profile))
            step = pick("What now", [("Start a call", CALL), ("Lesson to improve on a weakness", LESSON),
                                     ("Progress", PROGRESS), ("Change language", LANGUAGES), ("Quit", QUIT)])
        if step in (None, LANGUAGES, QUIT):
            return QUIT if step == QUIT else LANGUAGES
        if step == PROGRESS:
            _show_progress(profile, topics)
            step = None
        elif step == LESSON:
            step = _pick_weakness(profile)
        else:
            step = _start_call(profile, topics, arguments, lesson=step if isinstance(step, Weakness) else None)
            step = None if step == MENU else step


def _language_context(profile) -> str:
    """The language for a screen header, with the level once there is one: "Spanish · B2"."""
    level = estimated_level(grades(profile.sessions_folder, profile.language))
    return _language_title(profile) + (f" · {level}" if level else "")


def _language_title(profile) -> str:
    """The language with its flag, for screen headers: "🇪🇸 Spanish"."""
    return f"{flag_for_code(profile.language)} {profile.language_name}".strip()


def _show_progress(profile, topics: TopicMemory) -> None:
    show_screen(CONSOLE, f"{_language_title(profile)} · progress", "Here's how you're coming along.")
    _print_report(profile, topics)
    pick("", [("← Back", BACK)])


def _pick_weakness(profile) -> Weakness | None:
    """A recurring mistake to have a lesson on; None to go back to the menu (Back or Esc)."""
    show_screen(CONSOLE, f"{_language_title(profile)} · lessons", "Pick a mistake and we'll drill it.")
    found = weaknesses(profile.sessions_folder, profile.language)
    if not found:
        CONSOLE.print(indented(Text("No weaknesses yet. They show up after your first call.", style=MUTED), bottom=1))
        pick("", [("← Back", BACK)])
        return None
    lesson = pick("Which one", [(weakness.pattern, weakness) for weakness in found] + [("← Back", BACK)])
    return None if lesson == BACK else lesson


def _start_call(profile, topics: TopicMemory, arguments: argparse.Namespace, lesson: Weakness | None = None):
    """Runs a call, then its report card. Returns what to do next: a Weakness for a lesson, MENU or QUIT."""
    account = use_claude_account(profile)
    with Screen(CONSOLE) as screen:
        mic = arguments.mic or _built_in_mic()
        listener = Listener(MicSource(mic), profile.language, profile.whisper_prompt, arguments.end_silence)
        conversation = Conversation(listener, Speaker(profile.voice), screen, Brain.for_profile(profile, CACHE))
        if lesson:
            conversation.talker.set_lesson(lesson.pattern, lesson.examples)
            focus = _focus_line("Lesson", lesson.pattern)
        else:
            topic = _matching_topic(topics, arguments.topic) if arguments.topic else topics.next_topic()
            conversation.talker.set_focus(topic, topics.words(topic))
            conversation.talker.set_memories(FriendMemory(profile.sessions_folder).facts())
            focus = _focus_line("Topic", topic, f"{len(topics.words(topic))}/{WORDS_FOR_COVERED} words")
        screen.call_header(f"{_language_title(profile)} · call", focus, account)
        try:
            asyncio.run(_call(conversation))
        except KeyboardInterrupt:
            pass
    if not conversation.log.turns:
        return MENU
    if conversation.unavailable:
        CONSOLE.print(indented(Text("Your call is saved, but there's no report card this time: it needs Claude too.",
                                    style=MUTED)))
    card = None if conversation.unavailable else _report_card(profile, conversation, screen)
    path = save_call(profile.sessions_folder, profile.language_name, conversation.talker.history, conversation.log, card)
    CONSOLE.print(indented(Text(f"Saved to {path}", style=MUTED), bottom=1))
    return _pick_next(profile)


def _focus_line(kind: str, focus: str, detail: str = "") -> Text:
    return Text.assemble((f"{kind}: ", MUTED), (focus, TEXT), (f" · {detail}" if detail else "", MUTED))


def _report_card(profile, conversation: Conversation, screen: Screen) -> ReportCard | None:
    context = f"{_language_title(profile)} · report"
    try:
        with screen.writing_report(context):
            card = asyncio.run(Reporter(profile).report(conversation.talker.history, conversation.log))
    except KeyboardInterrupt:
        return None
    except ClaudeUnavailable as reason:
        screen.claude_unavailable(reason)
        return None
    screen.report_card(card, context, estimated_level(grades(profile.sessions_folder, profile.language)))
    return card


def _pick_next(profile):
    """After the report card: a lesson on one of the top recurring mistakes, the menu, or quit. Esc is the menu."""
    lessons = weaknesses(profile.sessions_folder, profile.language)[:NEXT_LESSONS]
    choice = pick("Next", [(f"Lesson on {weakness.pattern}", weakness) for weakness in lessons]
                  + [("Main menu", MENU), ("Quit", QUIT)])
    return MENU if choice is None else choice


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
    past = grades(profile.sessions_folder, profile.language)
    if not past:
        CONSOLE.print(indented(Text(f"No {profile.language_name} calls yet.", style=MUTED), bottom=1))
        return
    covered = sum(len(topics.words(topic)) >= WORDS_FOR_COVERED for topic in topics.all_topics())
    started = sum(bool(topics.words(topic)) for topic in topics.all_topics())
    CONSOLE.print(progress_card(estimated_level(past), past,
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
