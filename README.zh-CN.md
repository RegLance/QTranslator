<p align="center">
  <img src="assets/icon.png" alt="QTranslator" width="96" height="96" />
</p>

<h1 align="center">QTranslator</h1>

<p align="center">
  <strong>你的 AI 翻译助手 — 划词、翻译、润色、对话，一托盘掌控全场景工作流。</strong>
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

**QTranslator** 是一款桌面级 AI 助手，将现代大模型能力无缝融入你的日常工作流。任意窗口划词即译、流式输出译文、润色支持差异高亮、管理生词本、与 AI 对话——无需离开当前窗口。

面向研究者、内容创作者、语言学习者和效率用户，提供**专业级工具**，零摩擦切换。

<div align="center">
  <img src="Animation.gif" alt="演示" width="800" />
</div>

## ✨ 为什么选择 QTranslator？

| 维度 | 体验 |
|------|------|
| **心流** | 全局热键 + 智能划词检测 + 悬浮按钮，比浏览器标签页更少上下文切换 |
| **智能** | 兼容 OpenAI 式 API、流式输出、词级差异高亮、支持 Skills 与 MCP 工具的 AI 对话 |
| **学习** | 词汇管理、短文生成、带音标/释义/例句的单词卡片——让翻译转化为记忆 |
| **可控** | 离线或 Edge 在线朗读；本地或联网语种检测；可自定义主题、快捷键、行为 |

## 🚀 功能特性

### 核心翻译

- **划词翻译**：选中文本后点击翻译按钮，**流式输出**即时呈现
- **选中翻译**：全局快捷键（默认 `Ctrl+Shift+T`）主动取词并弹出窗口；适合 **Excel、PowerPoint** 等不显示划词按钮的场景
- **翻译窗口**：独立窗口支持长文本，目标语言含中文/英文/日文/韩文等
- **润色**：改进表达；开启「显示润色差异」时以浅红（删）/ 浅绿（增）做词或短语级比对
- **总结**：对长文本生成结构化摘要，快速抓取要点
- **划词写作**：翻译并直接替换原文；可开启「保留原文」，译文插在原文下方

### AI 对话

- **多会话管理**：独立对话窗口，支持新建、重命名、删除会话
- **流式输出**：实时逐 token 响应
- **Skills**：顶部选择器注入专项能力
- **MCP 工具**：启用已配置的 MCP 工具扩展功能
- **回退功能**：悬停消息点击 （或右键→回退），丢弃后续对话并从该句重新开始
- **清空上下文**：一键让 AI 忘记之前的对话内容
- **独立 API**：可与翻译共用 API 配置，也可单独设置

### 学习与词汇

- **单词卡片**：双击任意英文单词（应用内/系统范围）查看音标、释义、形态变化、速记；支持收藏和朗读
- **单词收藏**：译文区星标收藏「原文 + 译文」（新增时校验与当前输入一致）
- **收藏窗口**：托盘入口，支持浏览、搜索、删除、导出 JSON、朗读
- **词汇短文**：按复习次数优先选取最多 **50** 条收藏词，选择体裁后生成约 **160 词**短文，流式输出

### 体验增强

- **翻译历史**：持久化保存，便于回顾与管理
- **语种检测**：固定方向（中文→英文，其它→中文）；引擎可选百度/Google/Bing（联网，失败回退本地）或仅本地
- **朗读 (TTS)**：系统离线或 Edge 在线（`edge-tts`，失败回退系统）
- **单词详解**：单词级翻译展示释义、音标、例句
- **多主题**：深色/浅色及多种彩色主题（海洋、森林、紫色、暖橙、玫瑰、薄荷、自定义）
- **自定义快捷键**：唤醒窗口、划词写作、选中翻译均可重绑
- **窗口行为**：可选固定高度、记忆位置
- **默认功能**：点击「翻译/润色/总结」同步设为默认，**Enter** 执行当前默认
- **开机自启**：可选
- **划词黑名单**：指定程序不显示划词按钮，避免与软件自带浮动工具栏冲突
- **更新检查**：自动检测新版本并在标题栏提示；可在设置中关闭

## 🎯 快速开始

1. 托盘 → **设置**，配置 **API Key**、**Base URL**、**Model**（兼容 OpenAI 格式）
2. 在任意应用选中文本，或从托盘打开**翻译窗口**
3. Office 等场景若不见划词按钮，请用**选中翻译**快捷键（`Ctrl+Shift+T`）

## 📖 使用说明

### 首次使用

1. 右键托盘图标 → **设置**
2. 配置 API Key、Base URL、Model
3. 保存后即可使用

### 划词与选中翻译

在支持的应用中选中文本，出现翻译按钮后点击即可（支持流式）。

为减少与 **Excel、PowerPoint** 等自带划词/浮动工具栏的冲突，这些程序**默认不显示**划词按钮。请先**选中**内容，再按**选中翻译**（默认 `Ctrl+Shift+T`，可在设置中修改）。

若未取到选区，可先 **Ctrl+C** 复制后再试，或确认焦点在可读/可编辑区域。取词路径包括：编辑器直读、UI Automation、`selection-hook` 主动查询，必要时剪贴板探测。

### 单词卡片

- **应用内**：设置 → 翻译窗口设置 → 勾选「启用划词查词（应用内）」，在原文框或译文框中双击选中单个英文单词
- **应用外**：勾选「启用划词查词（应用外）」后，在桌面任意位置（浏览器、文档等）双击选中单词
- 卡片显示音标、释义、形态变化、速记；支持收藏和朗读
- 点击卡片外任意位置关闭；查询中双击新单词会直接切换为新单词的卡片

### AI 对话

- **入口**：翻译窗口标题栏「AI」按钮，或右键托盘图标 → AI 对话
- **会话管理**：左侧会话列表支持新建、重命名、删除会话，对话内容与上下文保存在本地
- **Skills**：顶部选择 Skill 注入专项能力
- **MCP**：勾选启用已配置的 MCP 工具
- **回退**：鼠标悬停某条消息，点击气泡右下角 ↵（或右键消息 → 回退到这条消息），丢弃之后的对话并从该句重新开始
- **清空上下文**：点击按钮可让 AI 忘记之前的对话内容
- **API 配置**：设置 → AI 对话中可取消「与翻译共用 API 配置」单独配置模型

### 单词收藏与词汇短文

**单词收藏**：翻译完成后点击译文区右下角**星标**；托盘打开**单词收藏**集中管理。

**词汇短文**：在收藏窗口下方选择体裁 → **生成短文**；生成中可**停止**，可用播放按钮朗读（依赖 TTS 设置）。

### 划词黑名单

- 黑名单中的程序不显示划词按钮（避免与 Excel、PowerPoint 等软件自带的浮动工具栏冲突），可改用「选中翻译」快捷键
- 设置 → 划词黑名单：左侧为生效中的黑名单，点「→」移出；右侧为已移出的条目，点「←」重新加入
- 支持手动添加：直接输入进程名

### 快捷键一览

| 功能 | 默认快捷键 |
|------|------------|
| 唤醒翻译窗口 | `Ctrl+O` |
| 选中翻译 | `Ctrl+Shift+T` |
| 划词写作 | `Ctrl+I` |
| 关闭窗口 | `Esc` |
| 执行当前默认功能 | `Enter` |
| 换行 | `Shift+Enter` |

以上全局快捷键均在**设置 → 快捷键**中可自定义。

## ⚙️ 配置说明

配置文件 **`config.yaml`** 位于应用数据目录（**Windows**：`%LOCALAPPDATA%\QTranslator`）。

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

## ️ 技术架构

| 模块 | 技术栈 |
|------|--------|
| 界面 | PyQt6（无边框、主题系统） |
| 翻译 | OpenAI 兼容 API，SSE 流式输出 |
| 文本捕获 | selection-hook（Node 原生）+ 自动化/剪贴板管道 |
| 全局热键 | pynput `GlobalHotKeys` |
| 朗读 | 系统语音（SAPI/pyttsx3）或 Edge TTS |
| 语种检测 | 百度/Google/Bing + **langdetect** 回退，或仅本地 |

## 📁 目录结构

```
QTranslator/
├── run.py                   # 便捷启动器
├── build.py                  # 打包构建
├── requirements.txt
── src/
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
│       ├── chat_window.py
│       ├── word_popup.py
│       ├── history_window.py
│       ├── vocabulary_window.py
│       ├── help_window.py
│       └── splash_screen.py
├── native/
│   └── selection-service.js
└── assets/
```

## 🛠️ 开发与构建

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

## ⚠️ 注意事项

- 使用前请确认 **API Key、Base URL、Model** 配置正确
- 流式润色、总结、词汇短文、AI 对话等均消耗已配置的 **LLM** 用量
- **联网语种检测**会外传短文本；如需更高隐私可改为 **local**
- **Edge 朗读**需网络；异常时可升级 `edge-tts` 或改用系统语音
- 翻译与生成内容仅供参考，重要信息请人工核实
- Excel、PowerPoint 等若不见划词按钮，请使用**选中翻译**快捷键，勿仅依赖悬浮图标

## 📄 开源协议

MIT License

---

<p align="center">
  若 QTranslator 帮你少切换一次窗口，欢迎点个 Star，或顺手提一则 Issue / PR。
</p>
