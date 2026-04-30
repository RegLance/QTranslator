# QTranslator

一款智能翻译助手，基于大语言模型提供高质量的翻译服务。

## 功能特性

### 核心功能

- **划词翻译**：选中文本后自动出现翻译按钮，点击即可翻译，支持流式输出
- **翻译窗口**：独立窗口支持输入长文本翻译，可选择目标语言（中文/英文/日文/韩文等）
- **润色功能**：对文本进行润色改进；开启「显示润色差异」时用词/短语级比对展示浅红（删）/浅绿（增）高亮
- **总结功能**：对长文本进行智能总结，快速获取关键信息
- **划词写作**：翻译并直接替换原文，支持保留原文选项

### 辅助功能

- **翻译历史**：自动保存翻译历史记录，方便查阅和管理
- **智能检测**：自动识别源语言并确定翻译方向（中文→英文，其他→中文）
- **单词详解**：单词翻译显示详细释义、音标和例句
- **多主题**：支持深色、浅色及多种彩色主题（海洋蓝/森林绿/皇家紫/暖橙/玫瑰粉/薄荷浅色），也可自定义主题颜色
- **自定义快捷键**：可自定义翻译窗口和划词写作的快捷键
- **翻译窗口设置**：支持固定窗口高度、记忆窗口位置
- **默认功能**：点击「翻译 / 润色 / 总结」按钮时同步设为默认功能，之后按 `Enter` 执行当前默认功能
- **浏览器划词延迟**：可调整浏览器环境下的划词延迟时间，避免与网站悬浮窗冲突
- **开机自启**：支持开机自动启动

## 使用方法

### 首次使用

1. 右键点击托盘图标，选择 **设置**
2. 配置 API Key、Base URL 和 Model
3. 保存设置即可开始使用

### 划词翻译

1. 在任意应用中选中需要翻译的文本
2. 自动出现翻译按钮
3. 点击按钮即可显示翻译结果
4. 支持流式输出，实时显示翻译内容

### 翻译窗口

- 打开方式：右键托盘图标 → **翻译窗口**，或双击托盘图标
- 输入文本后点击以下按钮：
  - **翻译**：将文本翻译为目标语言
  - **润色**：改进文本表达，使其更自然流畅
  - **总结**：生成文本摘要
- 点击「翻译 / 润色 / 总结」按钮会执行对应功能，并同步设为默认功能（按钮高亮）
- 支持快捷键：`Enter` 执行当前默认功能，`Shift+Enter` 换行

### 划词写作

1. 选中文本后按 `Ctrl+I`
2. 翻译结果直接替换原文
3. 可在设置中开启"保留原文"，译文将插入在原文下方

### 快捷键

默认快捷键（可在设置中自定义）：

| 功能 | 快捷键 |
|------|--------|
| 呼出翻译窗口 | `Ctrl+O` |
| 划词写作 | `Ctrl+I` |
| 关闭窗口 | `Esc` |
| 执行当前默认功能 | `Enter` |
| 换行 | `Shift+Enter` |

## 配置说明

配置文件 `config.yaml` 位于应用数据目录（Windows: `%LOCALAPPDATA%\QTranslator`），主要配置项：

```yaml
# 翻译服务配置
translator:
  api_key: "your-api-key"       # API 密钥
  model: "gpt-4o-mini"          # 模型名称
  base_url: "https://api.openai.com/v1"  # API 地址
  timeout: 60                   # 超时时间（秒）
  no_proxy: ""                  # 不使用代理的地址，多个用逗号分隔

# 界面配置
theme:
  popup_style: "dark"           # 窗口样式：dark/light/ocean_blue/forest_green/royal_purple/warm_orange/rose_pink/mint_light/custom
  custom_accent: "#007AFF"      # 自定义主题强调色
  custom_bg: "#2d2d2d"          # 自定义主题背景色
font:
  size: 15                      # 字体大小

# 快捷键配置
hotkey:
  translator_window: "Ctrl+O"
  writing: "Ctrl+I"

# 写作配置
writing:
  keep_original: false          # 是否保留原文

# 翻译窗口配置
translator_window:
  fixed_height_mode: false      # 固定窗口高度（不随内容自动调整）
  remember_window_position: false  # 记忆窗口位置
  default_function: "translate" # 默认功能：translate/polishing/summarize

# 启动配置
startup:
  auto_start: false             # 开机自启
```

## 技术架构

- **UI框架**：PyQt6（无边框设计，支持主题切换）
- **翻译服务**：OpenAI API（支持流式输出）
- **文本捕获**：selection-hook（Node.js原生模块）
- **快捷键**：keyboard 库（全局热键监听）
- **语言检测**：langdetect 库

## 目录结构

```
QTranslator/
├── src/
│   ├── main.py              # 主入口
│   ├── config.py            # 配置管理
│   ├── core/
│   │   ├── translator.py    # 翻译服务
│   │   ├── writing.py       # 写作服务
│   │   ├── text_capture.py  # 文本捕获
│   │   └── selection_detector.py  # 选择检测
│   ├── ui/
│   │   ├── tray_icon.py     # 系统托盘
│   │   ├── popup_window.py  # 划词翻译弹窗
│   │   ├── translator_window.py    # 翻译窗口
│   │   ├── history_window.py       # 历史窗口
│   │   ├── help_window.py          # 帮助窗口
│   │   ├── translate_button.py     # 翻译按钮
│   │   └── splash_screen.py        # 启动画面
│   └── utils/
│       ├── theme.py         # 主题管理
│       ├── logger.py        # 日志管理
│       ├── history.py       # 历史记录
│       ├── hotkey_manager.py        # 快捷键管理
│       ├── tts.py           # 语音朗读
│       └── language_detector.py     # 语言检测
├── native/
│   └── selection-service.js # 文本选择服务
├── assets/
│   └── icon.png             # 应用图标
├── requirements.txt         # Python依赖
└── build.py                 # 构建脚本
```

## 开发与构建

### 环境要求

- Python 3.13+
- Node.js（用于 selection-hook）

### 安装依赖

```bash
pip install -r requirements.txt
cd native && npm install
```

### 运行程序

```bash
python run.py
```

### 构建可执行文件

```bash
python build.py
```

生成的可执行文件位于 `dist/` 目录。

## 注意事项

- 请确保已正确配置 API Key、Base URL 和 Model
- 翻译采用智能检测，中文→英文，其他语言→中文
- 单词翻译会显示详细释义、音标和例句
- 翻译结果仅供参考，请核实重要内容
- 浏览器中划词延迟时间可在设置中调整，避免与网站悬浮窗冲突
- 如遇到问题，可查看日志文件或检查 API 配置

## License

MIT License