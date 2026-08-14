<p align="center">
  <img src="assets/icon.png" alt="QTranslator" width="96" height="96" />
</p>

<h1 align="center">QTranslator</h1>

<p align="center">
  <strong>Your AI-powered translation companion — capture, translate, polish, converse. One tray app, infinite possibilities.</strong>
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

**QTranslator** is a desktop AI assistant that seamlessly integrates modern LLM capabilities into your daily workflow. Select text anywhere, get instant translations with streaming output, polish your writing with diff highlighting, manage vocabulary, and chat with AI — all without leaving your current window.

Built for researchers, content creators, language learners, and power users who demand **professional-grade tools** without the friction of context switching.

<div align="center">
  <img src="Animation.gif" alt="QTranslator demo" width="800" />
</div>

## ✨ Why QTranslator?

| Dimension | Experience |
|-----------|------------|
| **Flow** | Global hotkeys + smart selection detection + hover button — fewer context switches than a browser tab |
| **Intelligence** | OpenAI-compatible APIs, streaming replies, phrase-level diff highlighting, AI chat with Skills & MCP tools |
| **Learning** | Vocabulary management, story generation, word cards with phonetics & examples — turn translations into retention |
| **Control** | Offline or Edge TTS; local or remote language detection; customizable themes, hotkeys, and behaviors |

##  Features

### Core Translation

- **Hover Translate** — Select text, click the translate button, get **streaming** results instantly
- **Selection Translate** — Global shortcut (`Ctrl+Shift+T` by default) captures selection and opens a popup; perfect for **Excel, PowerPoint** where hover button is suppressed
- **Translator Window** — Standalone window for longer texts; supports Chinese, English, Japanese, Korean, and more
- **Polish** — Improve wording with optional **phrase-level diff** (soft red removals / soft green additions)
- **Summarize** — Generate structured summaries for long inputs
- **Selection Writing** — Translate and replace in place; optional **keep original** below the result

### AI Chat

- **Multi-session Chat** — Independent chat window with session management (create, rename, delete)
- **Streaming Output** — Real-time token-by-token responses
- **Skills** — Inject specialized capabilities via top selector
- **MCP Tools** — Enable configured MCP tools for extended functionality
- **Rewind** — Click ↵ on any message (or right-click → rewind) to discard subsequent conversation and restart from that point
- **Clear Context** — Let AI forget previous conversation with one click
- **Independent API** — Share translation API config or set separate credentials for chat

### Vocabulary & Learning

- **Word Cards** — Double-click any English word (in-app or system-wide) to see phonetics, definitions, forms, mnemonics; supports favorites and TTS
- **Starred Entries** — Save source + translation from result pane (validated against current input)
- **Vocabulary Hub** — Browse, search, delete, export JSON, TTS from tray menu
- **Vocabulary Stories** — Up to **50** starred terms (by review count) → generate short passages (~160 words) by genre, streaming output

### Quality of Life

- **Translation History** — Persistent history for review and management
- **Language Detection** — Fixed direction (Chinese→English, others→Chinese); engines: Baidu / Google / Bing (online with **local fallback**) or **local only**
- **TTS** — System offline or **Edge online** (`edge-tts`, falls back to system)
- **Word Detail** — Definitions, phonetics, examples for word-level queries
- **Theming** — Dark / light + accent themes (ocean, forest, purple, warm orange, rose, mint, custom)
- **Hotkeys** — Wake window, writing, selection translate — all **rebindable**
- **Window Behavior** — Optional fixed height, remember position
- **Default Action** — Clicking Translate / Polish / Summarize sets the **default** for **Enter**
- **Launch at Login** — Optional autostart
- **Selection Blacklist** — Exclude specific apps from hover button to avoid conflicts with built-in toolbars
- **Update Check** — Auto-detect new versions with title bar notification; disable in settings

## 🎯 Quick Start

1. **Tray → Settings** — configure **API Key**, **Base URL**, and **Model** (OpenAI-compatible)
2. Select text in any app, or open the **translator window** from tray
3. Prefer **Selection Translate** (`Ctrl+Shift+T`) in Office apps when hover button is suppressed

##  Usage Guide

### First Run

1. Right-click tray icon → **Settings**
2. Configure **API Key**, **Base URL**, and **Model**
3. Save — you're ready

### Hover vs Selection

In some apps (**Excel**, **PowerPoint**), the hover button is **disabled by default** to avoid conflicts with built-in selection UI. **Select text**, then press **Selection Translate** (`Ctrl+Shift+T`).

If nothing is captured, try **Ctrl+C** first, or ensure focus is inside editable/readable content. Capture paths include editor hooks, UI Automation, `selection-hook`, and clipboard probing.

### Word Cards

- **In-app**: Settings → Translator Window → enable "Enable word lookup (in-app)", double-click single English word in source/target text
- **System-wide**: Enable "Enable word lookup (system-wide)", double-click word anywhere on desktop (browser, documents, etc.)
- Card shows phonetics, definitions, forms, mnemonics; supports favorites and TTS
- Click outside card to close; double-click new word during lookup switches directly

### AI Chat

- **Entry**: Title bar "AI" button in translator window, or tray → AI Chat
- **Sessions**: Left sidebar supports create, rename, delete; conversations saved locally
- **Skills**: Top selector injects specialized capabilities
- **MCP**: Enable configured MCP tools
- **Rewind**: Hover message → click ↵ (or right-click → rewind) to discard subsequent conversation
- **Clear Context**: Button to let AI forget previous conversation
- **API**: Settings → AI Chat → uncheck "Share API config with translation" for separate credentials

### Vocabulary & Stories

**Vocabulary**: After translating, tap the **star** in result pane. Open **Vocabulary** from tray.

**Stories**: Pick genre → **Generate story** — up to 50 terms prioritized by review count; streaming output; optional **stop** and **read aloud**.

### Selection Blacklist

- Blacklisted apps won't show hover button (avoids conflicts with Excel, PowerPoint built-in toolbars)
- Settings → Selection Blacklist: left = active blacklist (click → to remove), right = removed items (click ← to re-add)
- Manual entry: type process name directly

### Translator Window Shortcuts

| Action | Default |
|--------|---------|
| Wake translator window | `Ctrl+O` |
| Selection translate | `Ctrl+Shift+T` |
| Selection writing | `Ctrl+I` |
| Close | `Esc` |
| Run default action | `Enter` |
| New line | `Shift+Enter` |

Customize under **Settings → Hotkeys**.

## ⚙️ Configuration

Configuration file **`config.yaml`** lives in app data directory (**Windows**: `%LOCALAPPDATA%\QTranslator`).

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

## 🏗️ Architecture

| Layer | Technology |
|-------|------------|
| UI | PyQt6, borderless layouts, rich theming |
| Translation | OpenAI SDK-compatible endpoints, SSE streaming |
| Selection | `selection-hook` (Node native) + automation / clipboard pipeline |
| Global shortcuts | `pynput` `GlobalHotKeys` |
| TTS | pyttsx3 / `edge-tts` |
| Language ID | Remote APIs + `langdetect` fallback |

## 📁 Project Layout

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
│   │   ── selection_detector.py
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
│       ├── chat_window.py
│       ├── word_popup.py
│       ├── history_window.py
│       ├── vocabulary_window.py
│       ├── help_window.py
│       └── splash_screen.py
├── native/
│   └── selection-service.js
── assets/
```

## 🛠️ Development

**Requirements**: Python **3.13+**, Node.js (for selection-hook wiring).

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

## ⚠️ Disclaimer

- You **must supply** valid API credentials; usage is billed by your provider where applicable
- Streaming polish, summaries, vocabulary stories, and AI chat **consume** your configured quota
- **Online** language detection may transmit short snippets
- **Edge TTS** needs network unless you rely on **system** voice
- Outputs are machine-generated — verify critical content

## 📄 License

MIT License

---

<p align="center">
  If QTranslator saves you a context switch, consider starring the repo and sharing feedback.
</p>
