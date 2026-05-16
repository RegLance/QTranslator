<p align="center">
  <img src="assets/icon.png" alt="QTranslator" width="96" height="96" />
</p>

<h1 align="center">QTranslator</h1>

<p align="center">
  <strong>桌面级大模型翻译助手 — 划词、截图识字、润色、朗读，一托盘掌控全场景工作流。</strong>
</p>

<p align="center">
  <a href="./README.md">English</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="Platform" />
  <img src="https://img.shields.io/badge/python-3.13+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/UI-PyQt6-41CD52?logo=qt&logoColor=white" alt="PyQt6" />
</p>

---

**QTranslator** 是一款常驻系统托盘的跨平台翻译工具，将现代 **LLM API** 接入你的日常操作：任意窗口划词、快捷键取词、框选屏幕 OCR，译文可流式呈现；润色、总结、生词本与 TTS 共享同一套极简交互。

面向需要 **「不打断心流」** 的多语言读者、研发与内容工作者 —— 少一次 Alt+Tab，多一分专注。

<p align="center">
  <img src="assets/Animation.gif" alt="QTranslator 演示" width="800" />
</p>

## 目录

- [产品亮点](#产品亮点)
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [配置说明](#配置说明)
- [技术架构](#技术架构)
- [目录结构](#目录结构)
- [开发与构建](#开发与构建)
- [注意事项](#注意事项)
- [开源协议](#开源协议)

## 产品亮点

| 维度 | 体验 |
|------|------|
| **心流** | 全局热键 + 划词检测 + 可选悬浮按钮，比浏览器标签页更少上下文切换 |
| **智能** | 兼容 OpenAI 式 API、流式输出，润色支持词级差异高亮，长文一键总结 |
| **可控** | 本地 OCR（RapidOCR）、离线或 Edge 在线朗读；语种检测可纯本地，也可联网并自动回退 |

## 功能特性

### 核心能力

- **划词翻译**：选中文本后可出现翻译按钮，点击即译，支持**流式输出**
- **选中翻译**：全局快捷键（默认 **`Ctrl+Shift+T`**）主动取词并弹出翻译窗口；适合 **Excel、PowerPoint** 等不显示划词按钮的场景（见下文说明）
- **翻译窗口**：独立窗口支持长文本，目标语言含中文 / 英文 / 日文 / 韩文等
- **润色**：改进表达；开启「显示润色差异」时以浅红（删）/ 浅绿（增）做词或短语级比对
- **总结**：对长文本生成摘要，快速抓取要点
- **划词写作**：翻译并直接替换原文；可开启「保留原文」，译文插在原文下方
- **截图识字（OCR）**：框选屏幕区域，本地识别后填入翻译窗口（默认 **`Ctrl+Shift+O`** 或托盘）；支持中/英及日/韩/俄等（部分需额外 ONNX 模型，见设置说明）

### 学习与词汇

- **单词收藏**：译文区星标收藏「原文 + 译文」（新增时校验与当前输入一致）
- **单词收藏窗口**：托盘入口，支持浏览、搜索、删除、导出 JSON、朗读等
- **词汇短文**：按复习次数优先选取最多 **50** 条收藏词，选择体裁后由当前翻译 API 生成约 **160 词**短文，流式写入，便于巩固词汇

### 体验增强

- **翻译历史**：自动保存，便于回顾与管理
- **智能检测**：固定方向（中文→英文，其它→中文）；引擎可选百度 / Google / Bing（联网，失败回退本地）或仅本地
- **朗读 (TTS)**：系统离线或 Edge 在线（`edge-tts`，失败回退系统）
- **单词详解**：单词级翻译展示释义、音标、例句
- **多主题**：深色 / 浅色及多种彩色主题，可自定义强调色与背景
- **自定义快捷键**：唤醒翻译窗口、划词写作、选中翻译、截图识字均可重绑
- **窗口行为**：固定高度、记忆位置（可选）
- **默认功能**：点击「翻译 / 润色 / 总结」同步设为默认，**`Enter`** 执行当前默认
- **开机自启**：可选

## 快速开始

1. 托盘 → **设置**，填写 **API Key**、**Base URL**、**Model**
2. 在任意应用选中文本，或从托盘打开 **翻译窗口**
3. 在 Office 等场景若不见划词按钮，请用 **选中翻译** 快捷键

## 使用说明

### 首次使用

1. 右键托盘图标 → **设置**
2. 配置 API Key、Base URL、Model
3. 保存后即可使用

### 划词与选中翻译

在支持的应用中选中文本，出现翻译按钮后点击即可（支持流式）。

为减少与 **Excel、PowerPoint** 等自带划词/浮动工具栏的冲突，这些程序**默认可能不显示**划词按钮。请先**选中**内容，再按 **选中翻译**（默认 **`Ctrl+Shift+T`**，可在设置中修改）。

若未取到选区，可先 **Ctrl+C** 复制后再试，或确认焦点在可读/可编辑区域。取词路径与自动划词一致：编辑器直读、UI Automation、`selection-hook` 主动查询，必要时剪贴板探测。

### 截图识字（OCR）

1. **`Ctrl+Shift+O`** 或托盘 **截图识字**
2. 屏幕变暗后拖选矩形，**`Esc`** 取消
3. 识别完成后通常自动打开翻译窗口并填入原文（多会继续自动翻译）
4. **设置 → 截图识字 (OCR)** 中选择语种；日文、韩文、俄文等需按页面说明准备模型文件

### 单词收藏与词汇短文

**单词收藏**：翻译完成后点击译文区右下角 **星标**；托盘打开 **单词收藏** 集中管理。

**词汇短文**：在收藏窗口下方选择体裁 → **生成短文**；生成中可 **停止**，可用播放按钮朗读（依赖 TTS 设置）。

### 快捷键一览

| 功能 | 默认快捷键 |
|------|------------|
| 唤醒翻译窗口 | `Ctrl+O` |
| 选中翻译 | `Ctrl+Shift+T` |
| 截图识字（OCR） | `Ctrl+Shift+O` |
| 划词写作 | `Ctrl+I` |
| 关闭窗口 | `Esc` |
| 执行当前默认功能 | `Enter` |
| 换行 | `Shift+Enter` |

以上全局快捷键均在 **设置 → 快捷键** 中可自定义。

## 配置说明

配置文件 **`config.yaml`** 位于应用数据目录（**Windows**：`%LOCALAPPDATA%\QTranslator`）。

```yaml
translator:
  api_key: "your-api-key"
  model: "gpt-4o-mini"
  base_url: "https://api.openai.com/v1"
  timeout: 60
  no_proxy: ""

language_detection:
  engine: "baidu"
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

## 技术架构

| 模块 | 技术栈 |
|------|--------|
| 界面 | PyQt6（无边框、主题系统） |
| 翻译 | OpenAI 兼容 API，流式输出 |
| 文本捕获 | selection-hook（Node 原生）等管道 |
| 全局热键 | pynput `GlobalHotKeys` |
| 截图识字 | RapidOCR / ONNX（依设置与模型） |
| 朗读 | 系统语音（SAPI/pyttsx3）或 Edge TTS |
| 语种检测 | 百度 / Google / Bing + **langdetect** 回退，或仅本地 |

## 目录结构

```
QTranslator/
├── run.py
├── build.py
├── requirements.txt
├── src/
│   ├── main.py
│   ├── config.py
│   ├── core/
│   │   ├── translator.py
│   │   ├── writing.py
│   │   ├── text_capture.py
│   │   └── selection_detector.py
│   ├── ui/
│   │   ├── tray_icon.py
│   │   ├── translate_button.py
│   │   ├── translator_window.py
│   │   ├── history_window.py
│   │   ├── vocabulary_window.py
│   │   ├── help_window.py
│   │   ├── screenshot_ocr_overlay.py
│   │   └── splash_screen.py
│   └── utils/
│       ├── theme.py
│       ├── logger.py
│       ├── history.py
│       ├── vocabulary.py
│       ├── hotkey_manager.py
│       ├── tts.py
│       └── language_detector.py
├── native/
│   └── selection-service.js
├── assets/
│   └── icon.png
└── README.md / README.zh-CN.md
```

## 开发与构建

### 环境要求

- Python **3.13+**
- Node.js（用于 selection-hook 相关步骤）

### 安装与运行

```bash
pip install -r requirements.txt
cd native && npm install
python run.py
```

### 构建可执行文件

```bash
python build.py
```

输出位于 **`dist/`** 目录。

## 注意事项

- 使用前请确认 **API Key、Base URL、Model** 配置正确  
- **联网语种检测**会外传短文本；如需更高隐私可改为 **local**  
- 词汇短文、润色、总结等均消耗已配置的 **LLM** 用量；OCR 扩展语种需自行准备模型  
- **Edge 朗读**需网络；异常时可升级 `edge-tts` 或改用系统语音  
- 翻译与生成内容仅供参考，重要信息请人工核实  
- Excel、PowerPoint 等若不见划词按钮，请使用 **选中翻译** 快捷键，勿仅依赖悬浮图标  

## 开源协议

MIT License

---

<p align="center">
  若 QTranslator 帮你少切换一次窗口，欢迎点个 Star，或顺手提一则 Issue / PR。
</p>
