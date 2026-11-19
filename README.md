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

## Setup

```bash
./setup.sh
```

Setup creates `.venv`, installs dependencies, downloads the voice-activity model and links `compa` into `~/.local/bin`. The first call downloads Whisper (large-v3-turbo) and the Kokoro voice into the Hugging Face cache.

Compa uses the `claude` CLI login in `claude_config_dir` from `settings.json` (default `~/.claude-personal`). It prints the account it bills when the call starts.

## Use

```bash
compa              # first language in settings.json
compa german
compa spanish --end-silence 1.4   # wait longer before Compa takes its turn
compa --mic "MacBook Pro Microphone"
```

**Wear headphones.** On speakers, Compa hears itself and cuts itself off.

- **Talk:** just talk. Compa listens on the MacBook mic by default, so AirPods stay in high-quality playback mode (their own mic switches them to muffled headset mode). Compa replies when you stop. If you trail off mid-thought ("compré una…", "pero eh"), it waits longer so you can find the word.
- **Cut it off:** start talking over it and it stops mid-sentence. It remembers only what you actually heard.
- **Don't know a word?** Say it in English. It shows up as `🔤 lawnmower → podadora`, and Compa uses the right word in its reply.
- **Go quiet** and Compa brings up something new after about 30 seconds, plus 10 seconds for each correction or English word it just showed you, so you have time to read them.
- **Hang up** with Ctrl-C. You get a report card in the terminal, and the whole call is saved to `sessions_folder` as Markdown, with the conversation, corrections, English words and report card.

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
| `talker_model` / `corrector_model` | Claude models for the conversation (fast) and the corrections and report (careful) |

To add a language, copy a profile and change these values. Kokoro has voices for Spanish, French, Italian, Portuguese, English, Japanese, Chinese and Hindi. For other languages, use a macOS voice. Premium macOS voices sound much better: System Settings → Accessibility → Spoken Content → System Voice → Manage Voices.

## Develop

```bash
.venv/bin/python -m pytest tests -q            # brain/report tests call the real Claude CLI
.venv/bin/python scripts/simulate.py spanish   # a whole call with a simulated learner (Claude + `say`)
.venv/bin/python scripts/simulate.py spanish --acoustic   # same, out of the speakers into the real mic
```

The simulated learner makes typical mistakes, slips in English words, pauses mid-thought, talks over Compa once and goes quiet once. At the end it prints reply latency, speculation hits, corrections and English words for every turn.
