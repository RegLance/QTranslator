#!/usr/bin/env python3
"""QTranslator headless CLI — thin wrapper over the vendored QTranslator core.

Exposes the desktop app's LLM core (translate / polish / summarize / OCR / TTS)
as plain command-line calls for AI agents (Claude Code, Codex, Cursor, ...).
No GUI, no tray, no global hotkeys, no screen selection: those are desktop-only
and intentionally NOT part of this skill.

Credentials: set env QTRANSLATOR_API_KEY / QTRANSLATOR_BASE_URL / QTRANSLATOR_MODEL
(or OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL). They are injected into the
local QTranslator config before the client is built; the core is unmodified.

No network call is made by `selftest` or `--dry-run`.
"""
import argparse
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "vendor"))


def _apply_env_credentials():
    """Inject env-provided credentials into config (no core change)."""
    from src.config import get_config
    cfg = get_config()
    pairs = (
        ("translator.api_key", ("QTRANSLATOR_API_KEY", "OPENAI_API_KEY")),
        ("translator.base_url", ("QTRANSLATOR_BASE_URL", "OPENAI_BASE_URL")),
        ("translator.model", ("QTRANSLATOR_MODEL", "OPENAI_MODEL")),
    )
    for key, envs in pairs:
        for env in envs:
            val = os.environ.get(env, "").strip()
            if val:
                cfg.set(key, val)
                break


def _translator():
    _apply_env_credentials()
    from src.core.translator import get_translator
    return get_translator()


def _emit_stream(gen):
    for chunk in gen:
        sys.stdout.write(chunk)
        sys.stdout.flush()
    sys.stdout.write("\n")


def cmd_translate(a):
    t = _translator()
    if a.dry_run:
        sp, up = t._build_translation_prompt(a.text, "auto", a.to or "auto")
        print("--- system ---\n" + sp + "\n--- user ---\n" + up)
        return 0
    if a.stream:
        _emit_stream(t.translate_stream(a.text, target_language=a.to))
        return 0
    r = t.translate_sync(a.text, target_language=a.to)
    if r.error:
        print(r.error, file=sys.stderr)
        return 1
    print(r.translated_text)
    return 0


def cmd_polish(a):
    t = _translator()
    if a.dry_run:
        sp, up = t._build_polishing_prompt(a.text)
        print("--- system ---\n" + sp + "\n--- user ---\n" + up)
        return 0
    _emit_stream(t.polishing_stream(a.text))
    return 0


def cmd_summarize(a):
    t = _translator()
    _emit_stream(t.summarize_stream(a.text, target_language=a.to))
    return 0


def cmd_ocr(a):
    t = _translator()
    p = Path(a.image)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    text, err = t.recognize_image(p.read_bytes(), mime)
    if err:
        print(err, file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_tts(a):
    import edge_tts
    from src.utils.tts import _edge_save_audio_to_file
    communicate = edge_tts.Communicate(a.text, a.voice)
    _edge_save_audio_to_file(communicate, a.out)
    print(a.out)
    return 0


def cmd_selftest(a):
    _apply_env_credentials()
    from src.core.translator import get_translator
    from src.core.writing import WritingService
    t = get_translator()
    sp, up = t._build_translation_prompt("hello world", "auto", "中文")
    w = WritingService()
    print("selftest OK: headless import + instantiate + prompt build")
    print("  translation prompt chars:", len(sp), len(up))
    print("  entries:", ", ".join(n for n in (
        "translate_sync", "translate_stream", "polishing_stream",
        "summarize_stream", "recognize_image") if callable(getattr(t, n, None))))
    print("  writing_stream:", callable(getattr(w, "writing_stream", None)))
    print("  (no network call made)")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="qtranslator-cli",
                                 description="QTranslator headless core for AI agents")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("translate", help="translate text")
    p.add_argument("text")
    p.add_argument("--to", default=None, help="target language (default: auto)")
    p.add_argument("--stream", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print prompts, no network")
    p.set_defaults(fn=cmd_translate)

    p = sub.add_parser("polish", help="polish/rewrite writing (streamed)")
    p.add_argument("text")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_polish)

    p = sub.add_parser("summarize", help="summarize text (streamed)")
    p.add_argument("text")
    p.add_argument("--to", default="中文")
    p.set_defaults(fn=cmd_summarize)

    p = sub.add_parser("ocr", help="extract text from an image (needs vision key)")
    p.add_argument("image")
    p.set_defaults(fn=cmd_ocr)

    p = sub.add_parser("tts", help="synthesize speech to an mp3 file (edge-tts)")
    p.add_argument("text")
    p.add_argument("--out", default="out.mp3")
    p.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    p.set_defaults(fn=cmd_tts)

    p = sub.add_parser("selftest", help="headless import/instantiate check, no network")
    p.set_defaults(fn=cmd_selftest)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # surface errors to the agent
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
