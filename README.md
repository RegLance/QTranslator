<p align="center">
  <img src="assets/icon.png" alt="QTranslator" width="96" height="96" />
</p>

<h1 align="center">QTranslator</h1>

<p align="center">
  <strong>Desktop LLM translator — capture, OCR, polish, listen. One tray app, infinite contexts.</strong>
</p>

<p align="center">
  <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="Platform" />
  <img src="https://img.shields.io/badge/python-3.13+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/UI-PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6" />
</p>

---

**QTranslator** is a cross‑platform tray utility that plugs your workflow into modern LLM APIs. Select text anywhere, hit a shortcut, or grab a screenshot — translations stream in instantly, while polish, summaries, OCR, vocabulary, and TTS sit behind the same minimal surface.

Designed for researchers, multilingual teams, and power users who want **IDE‑grade ergonomics** without leaving the active window.

<div align="center">
  <img src="assets/Animation.gif" alt="QTranslator demo" width="800" />
</div>

## Table of contents

- [Highlights](#highlights)
- [Features](#features)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Development](#development)
- [Disclaimer](#disclaimer)
- [License](#license)

## Highlights

| Pillar | What you get |
|--------|----------------|
| **Flow** | Global hotkeys + selection detection + optional hover button — less context switching than a browser tab |
| **Intelligence** | OpenAI‑compatible APIs, streaming replies, polishing with optional diff highlighting, summarization |
| **Privacy‑aware** | Local OCR (RapidOCR), optional offline or Edge TTS; language detection can stay local or use remote engines with fallback |

## Features

### Core

- **Hover translate** — After selection, a translate button can appear; results support **streaming**
- **Selection translate** — Global shortcut (default **`Ctrl+Shift+T`**) fetches selection and opens a popup; ideal when **Excel / PowerPoint** hide the hover button (see notes below)
- **Translator window** — Standalone window for longer text; target languages include Chinese / English / Japanese / Korean / etc.
- **Polish** — Improve wording; optional **phrase‑level diff** (soft red removals / soft green additions)
- **Summarize** — Structured summaries for long inputs
- **Selection writing** — Translate and replace in place; optional **keep original** below the result
- **Screenshot OCR** — Region capture (default **`Ctrl+Shift+O`** or tray); local OCR fills the translator (**Chinese / English**, plus **Korean** where an extra ONNX model is configured)

### Learning & vocabulary

- **Starred entries** — Save **source + translation** from the result pane (validated against current translation)
- **Vocabulary hub** — Tray menu: browse, search, delete, export JSON, **TTS**
- **Vocabulary stories** — Up to **50** starred terms (by review count) → short generated passages (~160 words) by genre, streaming

### Quality of life

- **History** — Persistent translation history
- **Language detection** — Fixed direction (Chinese→English, others→Chinese); engines: Baidu / Google / Bing (online, with **local fallback**) or **local only**
- **TTS** — System offline or **Edge online** (`edge-tts`, falls back to system)
- **Word detail** — Definitions, phonetics, examples for word‑level queries
- **Theming** — Dark / light + accent themes (ocean, forest, purple, warm orange, rose, mint, custom)
- **Hotkeys** — Wake window, writing, selection translate, OCR — all **rebindable**
- **Window behavior** — Optional fixed height, remember position
- **Default action** — Clicking Translate / Polish / Summarize sets the **default** for **`Enter`**
- **Launch at login** — Optional autostart

## Quick start

1. **Tray → Settings** — set **API Key**, **Base URL**, and **Model** (OpenAI‑compatible)
2. Select text in any app, or open the **translator window** from the tray
3. Prefer **Selection translate** in Office apps when the hover button is suppressed

## Usage

### First run

1. Right‑click the tray icon → **Settings**
2. Configure **API Key**, **Base URL**, and **Model**
3. Save — you are ready

### Hover vs selection

In some apps (**Excel**, **PowerPoint**), the hover button may be **disabled by default** to avoid conflicts with built‑in selection UI. **Select text**, then press **Selection translate** (`Ctrl+Shift+T` by default).

If nothing is captured, try **Ctrl+C**, or ensure focus is inside editable/readable content. Capture paths include editor hooks, UI Automation, `selection‑hook`, and clipboard probing when needed.

### Screenshot OCR

1. **`Ctrl+Shift+O`** (or tray → **Screenshot OCR**)
2. Drag a rectangle; **`Esc`** cancels
3. OCR result lands in the translator (often continues to translate automatically)
4. **Settings → OCR** — choose language; non default scripts may require additional model files per in‑app docs

### Vocabulary & stories

**Vocabulary**: After translating, tap the **star** in the result pane. Open **Vocabulary** from the tray.

**Stories**: Pick a genre, **Generate story** — up to 50 terms prioritized by review count; streaming output; optional **stop** and **read aloud**.

### Translator window shortcuts

| Action | Default |
|--------|---------|
| Wake translator window | `Ctrl+O` |
| Selection translate | `Ctrl+Shift+T` |
| Screenshot OCR | `Ctrl+Shift+O` |
| Selection writing | `Ctrl+I` |
| Close | `Esc` |
| Run default action | `Enter` |
| New line | `Shift+Enter` |

Customize under **Settings → Hotkeys**.

## Configuration

Configuration file **`config.yaml`** lives in the app data directory (**Windows**: `%LOCALAPPDATA%\QTranslator`).

```yaml
translator:
  api_key: "your-api-key"
  model: "gpt-4o-mini"
  base_url: "https://api.openai.com/v1"
  timeout: 60
  no_proxy: ""

language_detection:
  engine: "baidu"   # baidu | google | bing | local
  timeout: 3

theme:
  popup_style: "dark"
  custom_accent: "#007AFF"
  custom_bg: "#2d2d2d"
font:
  size: 15

hotkey:
  translator_window: "Ctrl+O"
  writing: "Ctrl+I"
  selection_translate: "Ctrl+Shift+T"
  ocr_screenshot: "Ctrl+Shift+O"

ocr:
  language: "ch_en"

tts:
  provider: "edge"
  edge_voice: ""
  edge_rate: "+0%"
  edge_volume: "+0%"

writing:
  keep_original: false

translator_window:
  fixed_height_mode: false
  remember_window_position: false
  default_function: "translate"

startup:
  auto_start: false
```

## Architecture

| Layer | Technology |
|--------|------------|
| UI | PyQt6, borderless layouts, rich theming |
| Translation | OpenAI SDK‑compatible endpoints, SSE streaming |
| Selection | `selection-hook` (Node native) + automation / clipboard pipeline |
| Global shortcuts | `pynput` `GlobalHotKeys` |
| OCR | RapidONNX (+ optional language packs) |
| TTS | pyttsx3 / `edge-tts` |
| Language ID | Remote APIs + `langdetect` fallback |

## Project layout

```
QTranslator/
├── run.py                   # Convenience launcher
├── build.py                  # Freeze / package
├── requirements.txt
├── src/
│   ├── main.py
│   ├── config.py
│   ├── core/
│   │   ├── translator.py
│   │   ├── writing.py
│   │   ├── text_capture.py
│   │   └── selection_detector.py
│   ├── utils/
│   │   ├── theme.py
│   │   ├── history.py
│   │   ├── vocabulary.py
│   │   ├── hotkey_manager.py
│   │   └── …
│   └── ui/
│       ├── tray_icon.py
│       ├── translate_button.py
│       ├── translator_window.py
│       ├── history_window.py
│       ├── vocabulary_window.py
│       ├── help_window.py
│       ├── screenshot_ocr_overlay.py
│       └── splash_screen.py
├── native/
│   └── selection-service.js
└── assets/
```

## Development

**Requirements**: Python **3.13+**, Node.js (for selection‑hook wiring).

```bash
pip install -r requirements.txt
cd native && npm install
python run.py
```

**Portable build**

```bash
python build.py
```

Artifacts under **`dist/`**.

## Disclaimer

- You **must supply** valid API credentials; usage is billed by your provider where applicable  
- Streaming polish, summaries, and vocabulary stories **consume** your configured quota  
- **Online** language detection may transmit short snippets; OCR extra models may be large — plan storage accordingly  
- **Edge TTS** needs network unless you rely on **system** voice  
- Outputs are machine‑generated — verify critical content

## License

MIT License

---

<p align="center">
  If QTranslator saves you a context switch, consider starring the repo and sharing feedback.
</p>
