---
name: qtranslator
description: Headless translation / writing-polish / summarize / image-OCR / text-to-speech core extracted from the QTranslator desktop app. Use when the user asks to translate text between languages (auto-detect), polish or rewrite prose, summarize long text, read text out of a screenshot/image, or synthesize speech to an mp3. Runs as plain CLI calls; no GUI required.
---

# QTranslator (headless core)

QTranslator is a desktop translation app; this skill exposes its **LLM core** as
command-line calls an agent can run directly. It does **not** provide the tray
icon, global hotkeys, or on-screen selection translation — those are desktop-only.

## Requirements (local)

- Python 3.10+ on the machine running the agent.
- `pip install -r requirements.txt` (openai, pyyaml, langdetect, edge-tts).
- An OpenAI-compatible LLM endpoint + key, supplied via environment:
  - `QTRANSLATOR_API_KEY` (or `OPENAI_API_KEY`)
  - `QTRANSLATOR_BASE_URL` (or `OPENAI_BASE_URL`)
  - `QTRANSLATOR_MODEL` (or `OPENAI_MODEL`)
- `ocr` additionally needs a vision-capable model/key configured.
- `tts` uses Microsoft edge-tts (network required); no API key needed.

Everything is vendored under `vendor/`; no clone of the QTranslator repo is needed.

## Commands

Run from the skill root: `python scripts/cli.py <command> ...`

| Command | Purpose | Example |
|---|---|---|
| `translate TEXT [--to LANG] [--stream]` | Translate (auto-detect source) | `python scripts/cli.py translate "hello world" --to 中文` |
| `polish TEXT` | Polish / rewrite prose (streamed) | `python scripts/cli.py polish "me go store yesterday"` |
| `summarize TEXT [--to LANG]` | Summarize (streamed) | `python scripts/cli.py summarize "<long text>" --to English` |
| `ocr IMAGE` | Extract text from image | `python scripts/cli.py ocr shot.png` |
| `tts TEXT --out FILE [--voice V]` | Synthesize speech to mp3 | `python scripts/cli.py tts "你好" --out hi.mp3` |
| `selftest` | Headless import/instantiate check (no network) | `python scripts/cli.py selftest` |

- Add `--dry-run` to `translate` / `polish` to print the prompts **without** any
  network call (useful to inspect behavior or test wiring for free).
- `translate` is synchronous by default; `--stream` prints chunks as they arrive.
- Exit code 0 = success, 1 = error (message on stderr).

## Notes for the agent

- Prefer `translate` for single words/short phrases: it returns dictionary-style
  senses + examples, not just a gloss.
- `polish` preserves meaning and improves style/grammar; it streams the revision.
- Do not attempt screen capture, hotkeys, or clipboard typing — out of scope here.
- Credentials come only from the environment above; never hardcode keys.

## License

Vendored core is the author's own work from the QTranslator project.
See the project repository for licensing terms before redistribution.
