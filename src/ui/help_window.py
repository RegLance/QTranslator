"""帮助窗口模块 - 显示软件功能和使用说明"""
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QScrollArea,
    QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QCursor, QDesktopServices, QMouseEvent, QIcon
import subprocess
from pathlib import Path

try:
    from ..config import get_config, APP_NAME, APP_VERSION, BUILD_TIME, CONTACT_URL, UPDATE_INFO_TEXT
    from ..utils.theme import get_theme, get_scrollbar_style
except ImportError:
    from src.config import get_config, APP_NAME, APP_VERSION, BUILD_TIME, CONTACT_URL, UPDATE_INFO_TEXT
    from src.utils.theme import get_theme, get_scrollbar_style


class HelpWindow(QWidget):
    """帮助窗口
    
    特性：
    - 无边框设计
    - 圆角设计
    - 支持深色/浅色主题
    - 显示软件功能和使用说明
    """

    closed = pyqtSignal()

    def __init__(self):
        """初始化帮助窗口"""
        super().__init__()

        self.setObjectName("HelpWindow")

        # 加载配置
        config = get_config()
        self._theme_style = config.get('theme.popup_style', 'dark')
        self._applied_theme_signature = None

        # 拖动相关
        self._is_dragging = False
        self._drag_start_pos = None
        self._drag_window_start_pos = None

        # 窗口属性
        # 不常驻置顶：「始终置顶」设置只控制翻译窗口
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 用时置顶、切走降级：「始终置顶」设置只控制翻译窗口
        try:
            from ..utils.window_front import install_activation_topmost
        except ImportError:
            from src.utils.window_front import install_activation_topmost
        install_activation_topmost(self)
        self._enable_windows_window_management()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 任务栏图标
        self._set_window_icon()

        self.setMinimumSize(500, 450)
        self.resize(560, 520)

        self._setup_ui()
        self._applied_theme_signature = self._get_theme_signature()

        # 连接主题变更信号
        try:
            from ..utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self.update_theme)

    def _setup_ui(self):
        """创建UI"""
        theme = get_theme(self._theme_style)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 内容框架
        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 10px;
                border: 1px solid {theme['border_color']};
            }}
        """)
        main_layout.addWidget(self._content_frame)

        # 阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(*theme['shadow_color']))
        shadow.setOffset(0, 4)
        self._content_frame.setGraphicsEffect(shadow)

        # 内容内部布局
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        content_layout.setSpacing(15)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setStyleSheet("background: transparent;")
        title_bar_layout = QHBoxLayout(self._title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        self._title_label = QLabel(f"{APP_NAME} - 帮助")
        self._title_label.setStyleSheet(f"""
            color: {theme['text_primary']};
            font-size: 18px;
            font-weight: bold;
            background: transparent;
        """)

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 1px;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)
        self._close_btn.clicked.connect(self.close)

        title_bar_layout.addWidget(self._title_label)
        title_bar_layout.addStretch()
        title_bar_layout.addWidget(self._close_btn)

        content_layout.addWidget(self._title_bar)

        # 版本信息区域
        self._version_frame = QFrame()
        self._version_frame.setObjectName("versionFrame")
        self._version_frame.setStyleSheet(f"""
            QFrame#versionFrame {{
                background-color: {theme['button_bg']};
                border-radius: 8px;
            }}
        """)
        version_layout = QVBoxLayout(self._version_frame)
        version_layout.setContentsMargins(12, 10, 12, 10)
        version_layout.setSpacing(4)

        self._version_label = QLabel(f"v{APP_VERSION}  |  {BUILD_TIME}  |  by SQAG")
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_label.setStyleSheet(f"""
            color: {theme['text_primary']};
            font-size: 14px;
            font-weight: bold;
            background: transparent;
        """)
        version_layout.addWidget(self._version_label)

        content_layout.addWidget(self._version_frame)

        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            {get_scrollbar_style(theme)}
        """)

        # 帮助内容
        self._help_content = QWidget()
        self._help_content.setStyleSheet(f"background-color: transparent;")
        self._help_layout = QVBoxLayout(self._help_content)
        self._help_layout.setSpacing(12)
        self._help_layout.setContentsMargins(5, 0, 5, 0)

        # 功能介绍
        self._add_section(self._help_layout, "功能介绍", theme)
        self._add_text(self._help_layout, f"""
{APP_NAME} 是一款智能翻译助手，基于大语言模型提供高质量的翻译服务。

主要功能：
• 划词翻译：选中文本后自动出现翻译按钮，点击即可翻译
• 快捷键翻译：按快捷键主动翻译当前选中内容（适合 Excel、PowerPoint 等划词按钮不出现的场景）
• 润色功能：对文本进行润色改进，可在设置中开启差异标记
• 总结功能：对长文本进行智能总结
• 划词写作：翻译并直接替换原文，支持保留原文选项
• 翻译历史：自动保存历史记录，方便查阅和管理
• 单词收藏：译文区点击星标收藏单词，支持浏览、搜索、删除、导出 JSON、朗读
• 词汇短文：按复习次数选取收藏词，选择体裁后由 API 生成英语短文，辅助词汇巩固
• 多主题：支持深色、浅色及多种彩色主题，也可自定义主题
• 语种检测：语种联网（百度 / Google / Bing）或本地检测，联网检查失败则退回本地检查方式
• 朗读：翻译窗口、历史记录窗口、单词收藏窗口均可朗读
• 默认功能：点击功能按钮时会同步设为 Enter 键执行的默认功能
• 单词卡片：双击选中单个英文单词自动弹出卡片，显示音标、释义、形态变化、速记，支持收藏和朗读
• AI 对话：独立的多会话对话窗口，流式输出，支持 Skills 与 MCP 工具，可回退到历史某句对话
• 更新检查：自动检测新版本并在标题栏提示，可在设置中关闭
• 开机自启：可在设置中开启，更换 exe 后启动路径自动修复
• 划词黑名单：指定程序中不出现划词按钮，避免与软件自带浮动工具栏冲突，支持手动管理
        """, theme)

        # 使用方法
        self._add_section(self._help_layout, "使用方法", theme)
        self._add_text(self._help_layout, """
1. 首次使用
   • 右键点击托盘图标 → 设置，配置 API Key、Base URL 和 Model。

2. 划词翻译
   • 选中文本后会出现翻译按钮
   • 点击按钮即可显示翻译结果
   • 支持流式输出，实时显示翻译内容
   • 在 Excel、PowerPoint 等部分应用中默认不出现划词按钮（避免与其自带浮动工具栏冲突），请改用「选中翻译」快捷键

3. 翻译窗口
   • 右键托盘图标 → 翻译窗口，或双击托盘图标
   • 输入文本后点击"翻译"、"润色"或"总结"按钮
   • 按 Enter 键执行当前选中的默认功能，Shift+Enter 换行
   • 点击功能按钮会执行对应功能，并同步设为默认功能（选中按钮高亮显示）
   • 可在设置中开启"固定窗口高度"或"记忆窗口位置"

4. 默认功能设置
   • 左键点击"翻译"、"润色"或"总结"按钮中的任意一个
   • 该按钮会执行对应功能，并被设为默认功能、以高亮颜色显示
   • 按 Enter 键时会自动执行选中的默认功能
   • 设置会持久化保存，程序重启后依然有效

5. 选中翻译（快捷键）
   • 在当前应用先选中需要翻译的文字，然后按下快捷键（默认 Ctrl+`，Esc 下方键）
   • 程序会读取当前选中内容并在鼠标附近打开翻译窗口，取词优先级与自动划词一致
   • 若未检测到选中内容，可先使用 Ctrl+C 复制后再试或确认输入焦点在正文区域
   • 快捷键可在设置 → 「选中翻译」中修改

6. 划词写作
   • 选中文本后按 Ctrl+I
   • 翻译结果会直接替换原文或插入在原文下方
   • 可在设置中开启"保留原文"选项

7. 润色差异
   • 在设置中勾选"显示润色差异"后，程序将原文与润色结果做词/短语级比对并高亮
   • 浅红背景表示相对原文删除或替换前的片段，浅绿背景表示新增或替换后的片段

8. 单词收藏与词汇短文
   • 翻译完成后，点击译文区右下角的星标按钮即可收藏单词（原文+译文配对保存）
   • 右键托盘图标 → 单词收藏，打开收藏窗口
   • 收藏窗口支持：浏览、搜索、双击条目在翻译窗口中打开、删除、导出 JSON
   • 点击条目旁的朗读按钮可朗读单词，点击短文区的朗读按钮可朗读短文
   • 词汇短文：在收藏窗口下方选择体裁（小故事/简报/歌词/诗等），点击「生成短文」
   • 程序按复习次数从高到低取最多 50 条收藏词，由 API 生成约 160 词英语短文
   • 生成过程中可点击「停止」中断

9. 快捷键（可在设置中自定义）
   • Ctrl+O：唤醒翻译窗口
   • Ctrl+`：选中翻译（Esc 下方、Tab 上方的 ` 键）
   • Ctrl+I：划词写作
   • Esc：关闭窗口（翻译窗口等）

10. 语种检测与朗读（均在设置中）
   • 「语种检测」：联网（百度 / Google / Bing）或「本地」；联网失败则用本地检查
   • 「朗读 (TTS)」：Edge TTS或系统离线TTS；Edge TTS失败则自动回退系统离线TTS ；

11. 单词卡片（划词查词）
   • 应用内：设置 → 翻译窗口设置勾选「启用划词查词（应用内）」，在原文框或译文框中双击选中单个英文单词
   • 应用外：勾选「启用划词查词（应用外）」后，在桌面任意位置（浏览器、文档等）双击选中单词
   • 卡片显示单词、音标、释义、形态变化和速记；⭐ 按钮收藏到单词本，喇叭按钮朗读发音
   • 点击卡片外任意位置关闭；查询中双击新单词会直接切换为新单词的卡片

12. AI 对话
   • 入口：翻译窗口标题栏「AI」按钮，或右键托盘图标 → AI 对话
   • 左侧会话列表支持新建、重命名、删除会话，对话内容与上下文保存在本地
   • Skills：顶部选择 Skill 注入专项能力；MCP：勾选启用已配置的 MCP 工具
   • 点击「清空上下文」可让 AI 忘记之前的对话内容
   • 回退：鼠标悬停某条消息，点击气泡右下角 ↵（或右键消息 → 回退到这条消息），丢弃之后的对话并从该句重新开始
   • 右键消息可复制内容；设置 → AI 对话中可取消「与翻译共用 API 配置」单独配置模型

13. 更新检查与开机自启
   • 检测到新版本时标题栏出现 ⬆️ 按钮，点击即可更新；设置中勾选「禁用更新检查」可关闭
   • 设置中勾选「开机自动启动」后重启自动运行；更换或移动 exe 后下次启动会自动修复启动路径

14. 划词黑名单
   • 黑名单中的程序不显示划词按钮（避免与 Excel、PowerPoint 等软件自带的浮动工具栏冲突），可改用「选中翻译」快捷键
   • 设置 → 划词黑名单：左侧为生效中的黑名单，点「→」移出；右侧为已移出的条目，点「←」重新加入
   • 在下方输入框输入进程名（如 EXCEL.EXE）可手动添加；进程名可在任务管理器「详细信息」页查看
        """, theme)

        # 注意事项
        self._add_section(self._help_layout, "注意事项", theme)
        self._add_text(self._help_layout, """
• 请确保已正确配置 API Key、Base URL 和 Model
• 翻译方向：中文→英文，其它→中文等
• 单词翻译会显示详细释义、音标和例句
• 翻译结果仅供参考，请核实重要内容
• 词汇短文、润色、总结等均消耗 LLM 用量
• 单词收藏数据存储在本地，卸载前可先用导出 JSON 备份
• 如遇到问题，可查看日志文件或检查API配置
• 若某应用不出现划词按钮，通常属于有意规避冲突的设计，请使用「选中翻译」快捷键
• 单词卡片仅对单个英文单词生效，选中多个单词或句子不会弹出，请使用正常翻译
        """, theme)

        # 更新信息
        self._add_section(self._help_layout, "更新信息", theme)
        self._add_text(self._help_layout, f"""
{UPDATE_INFO_TEXT}
        """, theme)

        self._help_layout.addStretch()

        self._scroll_area.setWidget(self._help_content)
        content_layout.addWidget(self._scroll_area, 1)

        # 底部按钮
        self._btn_bar = QFrame()
        self._btn_bar.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(self._btn_bar)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        # 联系我们按钮
        self._contact_btn = QPushButton("联系我们")
        self._contact_btn.setObjectName("contactBtn")
        self._contact_btn.setFixedSize(100, 36)
        self._contact_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._contact_btn.setStyleSheet(f"""
            QPushButton#contactBtn {{
                background-color: transparent;
                color: {theme['text_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton#contactBtn:hover {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
            }}
        """)

        def open_url():
            subprocess.Popen(f'start "" "{CONTACT_URL}"', shell=True)
        self._contact_btn.clicked.connect(open_url)

        btn_layout.addWidget(self._contact_btn)

        btn_layout.addStretch()

        self._ok_btn = QPushButton("知道了")
        self._ok_btn.setFixedSize(100, 36)
        self._ok_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._ok_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: none;
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        self._ok_btn.clicked.connect(self.close)

        btn_layout.addWidget(self._ok_btn)
        content_layout.addWidget(self._btn_bar)

    def _add_section(self, layout, title, theme):
        """添加章节标题"""
        label = QLabel(title)
        label.setStyleSheet(f"""
            color: {theme['text_primary']};
            font-size: 15px;
            font-weight: bold;
            padding: 5px 0;
        """)
        layout.addWidget(label)

    @staticmethod
    def _to_rich_text(text: str) -> str:
        """帮助纯文本转富文本。

        '•' 项目行用两列表格实现悬挂缩进：换行后的第二行从符号
        右侧位置开始，而不是回到行首；其余行保持原样（行首空格
        转为不换行空格，防止富文本压缩空白）。
        """
        import re as _re

        def _esc(s: str) -> str:
            return (s.replace('&', '&amp;')
                     .replace('<', '&lt;')
                     .replace('>', '&gt;'))

        parts = []
        _prev_bullet = False  # 上一条非空行是否为 • 子项
        for raw in text.lstrip('\n').split('\n'):
            line = raw.rstrip()
            if not line.strip():
                parts.append('&nbsp;<br/>')
                _prev_bullet = False
                continue
            m = _re.match(r'^(\s*)•\s*(.*)$', line)
            if m:
                indent = '&nbsp;' * len(m.group(1))
                parts.append(
                    '<table cellspacing="0" cellpadding="0"><tr>'
                    '<td valign="top">' + indent + '&bull;&nbsp;</td>'
                    '<td>' + _esc(m.group(2)) + '</td></tr></table>')
                _prev_bullet = True
                continue
            esc = _esc(line)
            lead = len(esc) - len(esc.lstrip(' '))
            # 数字编号条目（如 "2. 划词翻译"）：段首 nbsp 行保证上方空行，
            # 段尾换行产生下方空行，确保每条使用方法上下都有空行
            if _re.match(r'^\d+\.\s', line):
                parts.append('&nbsp;<br/>' + '&nbsp;' * lead
                             + esc[lead:] + '<br/>')
            else:
                # 普通段落紧跟 • 子项后也需要上空行（如更新信息中的版本号）
                # Qt 会吞掉 table 后的第一个空段落，所以需要两个 &nbsp;<br/>
                if _prev_bullet:
                    prefix = '&nbsp;<br/>&nbsp;<br/>'
                else:
                    prefix = ''
                parts.append(prefix + '&nbsp;' * lead + esc[lead:] + '<br/>')
            _prev_bullet = False
        return ''.join(parts)

    def _add_text(self, layout, text, theme):
        """添加文本内容（富文本，项目符号行悬挂缩进）"""
        label = QLabel(self._to_rich_text(text))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet(f"""
            color: {theme['text_secondary']};
            font-size: 13px;
        """)
        label.setWordWrap(True)
        layout.addWidget(label)


    def _enable_windows_window_management(self):
        """Windows Win32 样式：确保任务栏图标 + 系统快捷键"""
        try:
            if not __import__("sys").platform.startswith("win"):
                return
            import ctypes
            hwnd = int(self.winId())
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )
        except Exception:
            pass

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标），Win32 API 兜底确保打包后可用"""
        import sys
        # 解析资源路径（兼容打包环境）
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent.parent
        icon_png = base / "assets" / "icon.png"
        icon_ico = base / "assets" / "icon.ico"
        # Qt 层设置（开发模式通常够用）
        if icon_png.exists():
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_png)))
        # Win32 API 兜底：直接加载 ICO 并设置 WM_SETICON
        try:
            import ctypes
            hwnd = int(self.winId())
            LR_LOADFROMFILE = 0x0010
            IMAGE_ICON = 1
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            hicon = None
            # 优先加载 ICO（包含多尺寸，任务栏效果最好）
            if icon_ico.exists():
                hicon = ctypes.windll.user32.LoadImageW(
                    None, str(icon_ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            # 回退到 PNG
            if not hicon and icon_png.exists():
                hicon = ctypes.windll.user32.LoadImageW(
                    None, str(icon_png), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
        except Exception:
            pass


    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件 - 支持标题栏拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # 标题栏区域（标题栏高度约28px）
            if pos.y() <= 28:
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件 - 拖动窗口"""
        if self._is_dragging and self._drag_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_window_start_pos + delta
            self.move(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件 - 结束拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        """关闭事件"""
        self.closed.emit()
        event.accept()

    def show_window(self):
        """显示窗口并居中"""
        from PyQt6.QtWidgets import QApplication
        self.update_theme()
        # 设置明确的窗口大小，确保居中计算正确
        self.resize(560, 520)
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2 + screen_geo.x()
            y = (screen_geo.height() - self.height()) // 2 + screen_geo.y()
            self.move(x, y)
        self.show()
        # 唤醒时刻短暂置前一次
        try:
            from ..utils.window_front import bring_to_front_once
        except ImportError:
            from src.utils.window_front import bring_to_front_once
        bring_to_front_once(self)

    def update_theme(self):
        """更新主题"""
        new_signature = self._get_theme_signature()
        if self._applied_theme_signature == new_signature:
            return
        self._theme_style = new_signature[0]
        self._apply_theme()
        self._applied_theme_signature = new_signature

    def _get_theme_signature(self):
        """获取影响帮助窗口样式的主题签名。"""
        config = get_config()
        return (
            config.get('theme.popup_style', 'dark'),
            config.get('theme.custom_accent', '#007AFF'),
            config.get('theme.custom_bg', '#2d2d2d'),
        )

    def _apply_theme(self):
        """应用主题"""
        theme = get_theme(self._theme_style)

        # 更新内容框架
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 10px;
                border: 1px solid {theme['border_color']};
            }}
        """)

        # 更新标题
        self._title_label.setStyleSheet(f"""
            color: {theme['text_primary']};
            font-size: 18px;
            font-weight: bold;
            background: transparent;
        """)

        # 更新关闭按钮
        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 14px;
                font-weight: bold;
                padding-bottom: 1px;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)

        # 更新版本信息区域
        self._version_frame.setStyleSheet(f"""
            QFrame#versionFrame {{
                background-color: {theme['button_bg']};
                border-radius: 8px;
            }}
        """)
        self._version_label.setStyleSheet(f"""
            color: {theme['text_primary']};
            font-size: 14px;
            font-weight: bold;
            background: transparent;
        """)

        # 更新滚动区域
        self._scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新确定按钮
        self._ok_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: none;
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)

        # 更新联系我们按钮
        self._contact_btn.setStyleSheet(f"""
            QPushButton#contactBtn {{
                background-color: transparent;
                color: {theme['text_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 6px;
                font-size: 14px;
            }}
            QPushButton#contactBtn:hover {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
            }}
        """)

        # 更新帮助内容中的所有标签
        self._update_help_content_labels(theme)

    def _update_help_content_labels(self, theme):
        """更新帮助内容中的标签样式"""
        # 遍历帮助内容中的所有控件
        for i in range(self._help_layout.count()):
            item = self._help_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, QLabel):
                    # 根据字体粗细判断是标题还是正文
                    font = widget.font()
                    if font.bold():
                        widget.setStyleSheet(f"""
                            color: {theme['text_primary']};
                            font-size: 15px;
                            font-weight: bold;
                            padding: 5px 0;
                        """)
                    else:
                        widget.setStyleSheet(f"""
                            color: {theme['text_secondary']};
                            font-size: 13px;
                        """)


# 单例实例
_help_window_instance: Optional[HelpWindow] = None


def get_help_window() -> HelpWindow:
    """获取帮助窗口单例"""
    global _help_window_instance
    if _help_window_instance is None:
        _help_window_instance = HelpWindow()
    return _help_window_instance