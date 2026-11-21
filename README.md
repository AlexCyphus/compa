# 🤠 Compa

A voice-call language partner that runs on your Mac. You talk, and Compa talks back like a curious friend. It brings up the day's news, shares opinions, asks follow-up questions and keeps the conversation going. Corrections and English words appear in the terminal while you talk, and a report card follows when you hang up.

Everything runs locally except Claude: speech recognition (Whisper), voice detection (Silero) and the voice itself (Kokoro or macOS). Claude runs through your own Claude subscription via the Claude Agent SDK, with no API key.

```
🤠 Compa
   ¡Qué más, Alex! Oye, ¿viste que Barranquilla recibe la final de la Sudamericana?
   ¿Tú la vas a ver?

🗣  You  Sí, con mis primos, aunque me gustaría que estamos en el… stadium.
   🔤 stadium → estadio

🤠 Compa
   ¡Uy, en el estadio debe ser una locura! ¿Por quién vas, Boca o el Mineiro?

   📝 your last turn
   ✏️  que estamos → que estuviéramos  Subjuntivo tras 'me gustaría que'
```

## Languages

🇪🇸 Spanish · 🇫🇷 French · 🇩🇪 German · 🇮🇹 Italian · 🇧🇷 Portuguese · 🇳🇱 Dutch · 🇵🇱 Polish · 🇷🇺 Russian · 🇺🇦 Ukrainian · 🇸🇪 Swedish · 🇳🇴 Norwegian · 🇩🇰 Danish · 🇹🇷 Turkish · 🇬🇷 Greek · 🇯🇵 Japanese · 🇰🇷 Korean · 🇨🇳 Mandarin · 🇮🇩 Indonesian · 🇻🇳 Vietnamese · 🇮🇳 Hindi · Catalan · 🇺🇸 English

Spanish, German, French, Catalan and English (for Spanish speakers) come with a profile in `settings.json`. For the others, add one (see [Settings](#settings)).

## Setup

```bash
./setup.sh
```

Setup creates `.venv`, installs dependencies, downloads the voice-activity model and links `compa` into `~/.local/bin`. The first call downloads Whisper (large-v3-turbo) and the Kokoro voice into the Hugging Face cache.

Compa uses the `claude` CLI login in `claude_config_dir` from `settings.json` (default `~/.claude-personal`). It prints the account it bills when the call starts.

## Use

```bash
compa              # menu: pick a language, then a call, a lesson or your progress
compa german       # straight into a call
compa spanish --topic fishing          # pick today's topic
compa spanish --lesson subjuntivo      # a lesson on a mistake you keep making
compa spanish --report                 # level, grades over time, latest report card, what to work on
compa spanish --topics                 # every topic and how many of its words you've used
compa spanish --end-silence 1.4   # wait longer before Compa takes its turn
compa --mic "MacBook Pro Microphone"
```

**Wear headphones.** On speakers, Compa hears itself and cuts itself off.

- **Talk:** just talk. Compa listens on the MacBook mic by default, so AirPods stay in high-quality playback mode (their own mic switches them to muffled headset mode). Compa replies when you stop. If you trail off mid-thought ("compré una…", "pero eh"), it waits longer so you can find the word.
- **Cut it off:** start talking over it and it stops mid-sentence. It remembers only what you actually heard.
- **Don't know a word?** Say it in English. It shows up as `🔤 lawnmower → podadora`, and Compa uses the right word in its reply.
- **Take your time:** after its hello, Compa only talks when you do. If you go quiet it just waits; say "pregúntame otra cosa" when you want a new question.
- **Save a word:** say "guarda esa palabra en Clozemaster" (or name the word) and it's added as a cloze sentence to `clozemaster_collection` (`💾 Saved to Books!: …`). This uses the Clozemaster connector on your claude.ai account.
- **Out of Claude usage?** Compa says so in the terminal (with when it resets, if Claude says), hangs up and saves the call. There's no report card that time, because it needs Claude too.
- **Hang up** with Ctrl-C. You get a report card in the terminal, and the whole call is saved to `sessions_folder` as Markdown, with the conversation, corrections, English words and report card.

## Topics, level and lessons

- **Topics:** about 130 everyday topics, from fishing and hunting to taxes and paperwork. Every call has a focus topic you haven't covered yet, and Compa steers towards its vocabulary you haven't used. After the call, the topic words you used yourself are remembered (`topics-<lang>.json`). A topic is covered at 30 words.
- **Level:** an approximate CEFR level from the range score of your last 5 calls.
- **Lessons:** your recurring mistakes (subjunctive, gender agreement…) are listed in the menu and after each report card. A lesson is a call where Compa acts as your teacher: it explains the rule in a sentence, gets you using it, corrects that one structure out loud and has you say it again.

## How it stays snappy

- **Speculative replies:** when you pause for 0.4s, Compa sends what you've said so far to Claude. If you really have finished (about 1s of silence), the reply is already on its way. If you carry on, the draft is thrown away.
- **Warm Claude clients:** a small pool of `claude` processes is kept connected, with tools, MCP connectors and skills turned off, so each reply starts in about 0.5s.
- **Sentence streaming:** Compa starts speaking as soon as its first sentence is complete, and renders the next sentence while that one plays.
- **Corrections run alongside:** a second Claude (Sonnet) checks each of your turns while Compa answers.
- **News before you need it:** once a day per language, a Claude run with web search gathers about 12 stories (world, tech, business, science, culture, plus a little local news). Compa brings them up the way a friend would.

## Report card

After each call:

- **Accuracy:** errors per 100 words.
- **Range:** Claude's CEFR-anchored judgement of the grammar and vocabulary you used.
- **Fluency:** words per minute while talking, minus a little for each English word.
- **Grade:** the overall score, and the change since your last call.
- **Recurring errors:** each common error shows how many calls it has appeared in.
- **Also listed:** the English words you used, phrases to try next time, and what went well.

History is kept in `sessions_folder` as `grades-<lang>.json` and `common-errors-<lang>.json`.

## Settings

`settings.json` has shared keys plus one profile per language:

| key | what |
| --- | --- |
| `language`, `language_name` | Whisper code and name |
| `variety` | e.g. "Colombian Spanish": the persona, phrasing and corrections follow it |
| `level` | CEFR level the questions push towards |
| `voice` | `kokoro:<voice>` (e.g. `kokoro:ef_dora`), or any macOS voice name (`say -v '?'`) |
| `news_from` | where the local slice of the news comes from |
| `whisper_prompt` | filler words in the language, so Whisper keeps disfluencies instead of tidying them |
| `clozemaster_collection` | optional: the Clozemaster collection (in this language) that "save that word" adds to |
| `talker_model` / `corrector_model` | Claude models for the conversation (fast) and the corrections and report (careful) |

To add a language, copy a profile and change these values. Kokoro has voices for Spanish, French, Italian, Portuguese, English and Hindi. For other languages (including Japanese and Chinese), use a macOS voice. Premium macOS voices sound much better: System Settings → Accessibility → Spoken Content → System Voice → Manage Voices.

## Develop

```bash
.venv/bin/python -m pytest tests -q            # brain/report tests call the real Claude CLI
.venv/bin/python scripts/simulate.py spanish   # a whole call with a simulated learner (Claude + `say`)
.venv/bin/python scripts/simulate.py spanish --acoustic   # same, out of the speakers into the real mic
```

The simulated learner makes typical mistakes, slips in English words, pauses mid-thought and talks over Compa once. At the end it prints reply latency, speculation hits, corrections and English words for every turn.
