# CLI reference & vendoring notes

## Entry points used (from vendored core, unmodified)

- `src.core.translator.Translator`
  - `translate_sync(text, target_language=None, auto_detect=True) -> TranslationResult`
    (`TranslationResult.translated_text / .error / .source_language / .target_language`)
  - `translate_stream(text, target_language=None, on_chunk=None, ...) -> Generator[str]`
  - `polishing_stream(text, on_chunk=None) -> Generator[str]`
  - `summarize_stream(text, target_language="中文", on_chunk=None) -> Generator[str]`
  - `recognize_image(image_bytes, mime) -> (text, error)`
  - prompt builders (for `--dry-run`): `_build_translation_prompt(text, src, tgt)`,
    `_build_polishing_prompt(text)`
- `src.core.writing.WritingService.writing_stream(text, on_chunk=None) -> Generator[str]`
- `src.utils.tts._edge_save_audio_to_file(communicate, path)` + `edge_tts.Communicate`

## Vendor closure (why these files)

Preserves the original `src/` package layout so relative imports resolve:

```
vendor/src/__init__.py
vendor/src/config.py                  # pure-python config (yaml/json)
vendor/src/core/__init__.py
vendor/src/core/translator.py         # OpenAI SDK, generators; no Qt
vendor/src/core/writing.py            # OpenAI SDK, generators; no Qt
vendor/src/core/phonetic.py           # local IPA (reads vendor/assets/phonetic)
vendor/src/utils/__init__.py
vendor/src/utils/logger.py
vendor/src/utils/language_detector.py # langdetect (local) + optional online fallback
vendor/src/utils/tts.py               # edge-tts synth; Qt only lazy for playback (unused)
vendor/assets/phonetic/en_US.txt      # ipa-dict (MIT)
vendor/assets/phonetic/en_UK.txt      # ipa-dict (MIT)
```

Excluded (desktop-bound): `selection_detector`, `text_capture`, tray/hotkeys,
`ui/*` QThread workers, writing's clipboard/keystroke typing, TTS playback
(QMediaPlayer). The CLI never imports these.

## Credentials

`scripts/cli.py` maps env → config keys `translator.api_key / base_url / model`
via `get_config().set(...)` before `get_translator()`. Core is untouched.

## Packaging for Agensi

Zip the skill root (`SKILL.md` at root, `scripts/`, `vendor/`, `references/`,
`requirements.txt`). Self-contained: no repo clone required at runtime.
