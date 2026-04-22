"""帮助窗口模块 - 显示软件功能和使用说明"""
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QScrollArea,
    QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QCursor, QDesktopServices, QMouseEvent
import subprocess

try:
    from ..config import get_config, APP_NAME, APP_VERSION, BUILD_TIME
    from ..utils.theme import get_theme, get_scrollbar_style
except ImportError:
    from src.config import get_config, APP_NAME, APP_VERSION, BUILD_TIME
    from src.utils.theme import get_theme, get_scrollbar_style

# 联系我们网址
CONTACT_URL = "xxxx"


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

        # 拖动相关
        self._is_dragging = False
        self._drag_start_pos = None
        self._drag_window_start_pos = None

        # 窗口属性
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(500, 450)

        self._setup_ui()

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
• 翻译窗口：独立窗口支持输入长文本，可选择目标语言
• 润色功能：对文本进行润色改进，可在设置中开启差异标记
• 总结功能：对长文本进行智能总结
• 划词写作：翻译并直接替换原文，支持保留原文选项
• 翻译历史：自动保存历史记录，方便查阅和管理
• 多主题：支持深色、浅色及多种彩色主题，也可自定义主题
• 智能检测：自动识别源语言并确定翻译方向
• 默认功能：可自定义 Enter 键执行的默认功能，右键点击功能按钮即可设置
        """, theme)

        # 使用方法
        self._add_section(self._help_layout, "使用方法", theme)
        self._add_text(self._help_layout, """
1. 首次使用
   右键点击托盘图标 → 设置，配置 API Key、Base URL 和 Model。

2. 划词翻译
   • 选中文本后会出现翻译按钮
   • 点击按钮即可显示翻译结果
   • 支持流式输出，实时显示翻译内容

3. 翻译窗口
   • 右键托盘图标 → 翻译窗口，或双击托盘图标
   • 输入文本后点击"翻译"、"润色"或"总结"按钮
   • 按 Enter 键执行当前选中的默认功能，Shift+Enter 换行
   • 右键点击功能按钮可设置默认功能（选中按钮高亮显示）
   • 可在设置中开启"固定窗口高度"或"记忆窗口位置"

4. 默认功能设置
   • 右键点击"翻译"、"润色"或"总结"按钮中的任意一个
   • 该按钮将被设为默认功能，并以高亮颜色显示
   • 按 Enter 键时会自动执行选中的默认功能
   • 设置会持久化保存，程序重启后依然有效
   • 左键点击按钮仍执行对应功能，不受默认设置影响

5. 划词写作
   • 选中文本后按 Ctrl+I
   • 翻译结果会直接替换原文或插入在原文下方
   • 可在设置中开启"保留原文"选项

6. 润色差异
   • 在设置中勾选"显示润色差异"后，润色结果将标记修改部分
   • 删除线（~~删除~~）标记被删除的文字
   • 粗体（**新增**）标记新增或修改的文字

7. 快捷键（可在设置中自定义）
   • Ctrl+O：唤醒翻译窗口
   • Ctrl+I：划词写作
   • Esc：关闭窗口
        """, theme)

        # 注意事项
        self._add_section(self._help_layout, "注意事项", theme)
        self._add_text(self._help_layout, """
• 请确保已正确配置 API Key、Base URL 和 Model
• 翻译采用智能检测，中文→英文，其他语言→中文
• 单词翻译会显示详细释义、音标和例句
• 翻译结果仅供参考，请核实重要内容
• 如遇到问题，可查看日志文件或检查API配置
• 浏览器中划词延迟时间可在设置中调整
        """, theme)

        # 更新信息
        self._add_section(self._help_layout, "更新信息", theme)
        self._add_text(self._help_layout, """
暂无更新信息
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

    def _add_text(self, layout, text, theme):
        """添加文本内容"""
        label = QLabel(text)
        label.setStyleSheet(f"""
            color: {theme['text_secondary']};
            font-size: 13px;
            line-height: 1.6;
        """)
        label.setWordWrap(True)
        layout.addWidget(label)

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

    def update_theme(self):
        """更新主题"""
        new_theme = get_config().get('theme.popup_style', 'dark')
        # 即使主题名称未变，自定义主题的颜色也可能改变，因此始终更新
        self._theme_style = new_theme
        self._apply_theme()

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
                            line-height: 1.6;
                        """)


# 单例实例
_help_window_instance: Optional[HelpWindow] = None


def get_help_window() -> HelpWindow:
    """获取帮助窗口单例"""
    global _help_window_instance
    if _help_window_instance is None:
        _help_window_instance = HelpWindow()
    return _help_window_instance