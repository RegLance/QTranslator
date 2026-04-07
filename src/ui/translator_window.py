"""独立翻译窗口模块 - Translate Copilot（无边框风格，支持主题切换、纯文本显示）"""
from typing import Optional
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QComboBox, QFrame,
    QGraphicsDropShadowEffect, QApplication, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QKeySequence, QIcon, QFont

try:
    from ..utils.theme import get_theme, get_scrollbar_style, get_splitter_style, get_menu_style, get_combobox_style
    from ..config import get_config
except ImportError:
    from utils.theme import get_theme, get_scrollbar_style, get_splitter_style, get_menu_style, get_combobox_style
    from config import get_config


class StreamingTranslationWorker(QThread):
    """流式翻译工作线程"""

    chunk_received = pyqtSignal(str)
    translation_finished = pyqtSignal(str)
    translation_error = pyqtSignal(str)

    def __init__(self, text: str, target_language: str = None):
        super().__init__()
        self._text = text
        self._target_language = target_language
        self._is_cancelled = False

    def run(self):
        try:
            from core.translator import get_translator
            translator = get_translator()
            full_text = ""

            # 使用智能翻译（自动检测语言）
            for chunk in translator.translate_stream(self._text, self._target_language, auto_detect=True):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.translation_finished.emit(full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.translation_error.emit(str(e))

    def cancel(self):
        """取消翻译"""
        self._is_cancelled = True


class TranslatorWindow(QWidget):
    """独立翻译窗口（无边框，支持调整大小、主题切换、纯文本显示）"""

    def __init__(self):
        super().__init__()

        # 设置窗口对象名称
        self.setObjectName("TranslatorWindow")

        self._current_worker: Optional[StreamingTranslationWorker] = None

        # 窗口状态
        self._is_maximized = False
        self._normal_geometry: Optional[QRect] = None

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 调整大小状态
        self._is_resizing = False
        self._resize_edge: Optional[str] = None
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geometry: Optional[QRect] = None

        # 加载主题
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        
        # 字体大小
        self._font_size = get_config().get('font.size', 14)

        self._setup_window_properties()
        self._setup_ui()

    def _setup_window_properties(self):
        """设置窗口属性"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(450, 350)
        self.resize(500, 400)

        # 开启鼠标追踪
        self.setMouseTracking(True)

    def _setup_ui(self):
        """设置 UI"""
        theme = get_theme(self._theme_style)

        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 内容容器
        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)
        layout.addWidget(self._content_frame)

        # 添加阴影效果
        self._shadow_effect = QGraphicsDropShadowEffect()
        self._shadow_effect.setBlurRadius(15)
        self._shadow_effect.setColor(QColor(*theme['shadow_color']))
        self._shadow_effect.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(self._shadow_effect)

        # 内容布局
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(10)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setObjectName("titleBar")
        self._title_bar.setFixedHeight(28)
        self._title_bar.setStyleSheet(f"""
            QFrame#titleBar {{
                background-color: transparent;
                border-bottom: 1px solid {theme['border_color']};
            }}
            QFrame#titleBar:hover {{
                background-color: {theme['button_bg']};
            }}
        """)
        # 不设置整体光标，在 mouseMoveEvent 中动态控制

        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 0, 8, 0)

        # 标题文字
        self._title_label = QLabel("翻译窗口")
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 最小化按钮
        self._minimize_btn = QPushButton("─")
        self._minimize_btn.setObjectName("minimizeBtn")
        self._minimize_btn.setFixedSize(20, 20)
        self._minimize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._minimize_btn.setStyleSheet(f"""
            QPushButton#minimizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton#minimizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)
        self._minimize_btn.clicked.connect(self._on_minimize)
        title_layout.addWidget(self._minimize_btn)

        # 最大化按钮
        self._maximize_btn = QPushButton("□")
        self._maximize_btn.setObjectName("maximizeBtn")
        self._maximize_btn.setFixedSize(20, 20)
        self._maximize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._maximize_btn.setStyleSheet(f"""
            QPushButton#maximizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#maximizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)
        self._maximize_btn.clicked.connect(self._on_maximize)
        title_layout.addWidget(self._maximize_btn)

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)
        self._close_btn.clicked.connect(self.hide)
        title_layout.addWidget(self._close_btn)

        content_layout.addWidget(self._title_bar)

        # 控制栏（语言选择 + 按钮）
        self._control_bar = QFrame()
        self._control_bar.setStyleSheet("QFrame { background-color: transparent; }")
        control_layout = QHBoxLayout(self._control_bar)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(10)

        # 语言选择
        self._lang_label = QLabel("目标语言：")
        self._lang_label.setStyleSheet(f"QLabel {{ color: {theme['text_secondary']}; font-size: 13px; }}")
        control_layout.addWidget(self._lang_label)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["自动检测", "中文", "英文", "日文", "韩文"])
        self._lang_combo.setFixedHeight(28)
        self._lang_combo.setStyleSheet(get_combobox_style(theme))
        control_layout.addWidget(self._lang_combo)
        control_layout.addStretch()

        # 清空按钮
        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        self._clear_btn.clicked.connect(self._clear_all)
        control_layout.addWidget(self._clear_btn)

        # 翻译按钮
        self._translate_btn = QPushButton("翻译")
        self._translate_btn.setFixedHeight(28)
        self._translate_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._translate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._translate_btn.clicked.connect(self._start_translation)
        control_layout.addWidget(self._translate_btn)

        content_layout.addWidget(self._control_bar)

        # 分割器
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setStyleSheet(get_splitter_style(theme))
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(False)

        # 原文输入区域 - 纯文本显示
        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText("输入要翻译的文本...")
        self._input_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            QTextEdit:focus {{
                border-color: {theme['accent_color']};
            }}
            {get_scrollbar_style(theme)}
        """)
        self._input_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._input_text.customContextMenuRequested.connect(self._show_input_context_menu)
        self._input_text.setAcceptRichText(False)  # 禁用富文本
        self._splitter.addWidget(self._input_text)

        # 翻译结果显示区域 - 纯文本显示
        self._output_text = QTextEdit()
        self._output_text.setReadOnly(True)
        self._output_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._output_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._output_text.setPlaceholderText("翻译结果...")
        self._output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            {get_scrollbar_style(theme)}
        """)
        self._output_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._output_text.customContextMenuRequested.connect(self._show_output_context_menu)
        self._output_text.setAcceptRichText(False)  # 禁用富文本
        self._splitter.addWidget(self._output_text)

        # 设置分割器初始比例
        self._splitter.setSizes([150, 150])
        content_layout.addWidget(self._splitter, 1)

    def _on_minimize(self):
        """最小化窗口"""
        self.showMinimized()

    def _on_maximize(self):
        """最大化/还原窗口"""
        if self._is_maximized:
            # 还原
            if self._normal_geometry:
                self.setGeometry(self._normal_geometry)
            self._is_maximized = False
            self._maximize_btn.setText("□")
        else:
            # 最大化
            self._normal_geometry = self.geometry()
            screen = QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.availableGeometry())
            self._is_maximized = True
            self._maximize_btn.setText("❐")

    def update_theme(self):
        """更新主题"""
        new_theme = get_config().get('theme.popup_style', 'dark')
        new_font_size = get_config().get('font.size', 14)
        if new_theme != self._theme_style or new_font_size != self._font_size:
            self._theme_style = new_theme
            self._font_size = new_font_size
            self._apply_theme()

    def _apply_theme(self):
        """应用主题"""
        theme = get_theme(self._theme_style)

        # 更新内容框架
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)

        # 更新阴影
        self._shadow_effect.setColor(QColor(*theme['shadow_color']))

        # 更新标题栏
        self._title_bar.setStyleSheet(f"""
            QFrame#titleBar {{
                background-color: transparent;
                border-bottom: 1px solid {theme['border_color']};
            }}
            QFrame#titleBar:hover {{
                background-color: {theme['button_bg']};
            }}
        """)

        # 更新标题标签
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)

        # 更新按钮样式
        self._minimize_btn.setStyleSheet(f"""
            QPushButton#minimizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton#minimizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)

        self._maximize_btn.setStyleSheet(f"""
            QPushButton#maximizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#maximizeBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)

        self._close_btn.setStyleSheet(f"""
            QPushButton#closeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton#closeBtn:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)

        # 更新语言标签
        self._lang_label.setStyleSheet(f"QLabel {{ color: {theme['text_secondary']}; font-size: 13px; }}")

        # 更新下拉框
        self._lang_combo.setStyleSheet(get_combobox_style(theme))

        # 更新清空按钮
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)

        # 更新翻译按钮
        self._translate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新分割器
        self._splitter.setStyleSheet(get_splitter_style(theme))

        # 更新输入框
        self._input_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            QTextEdit:focus {{
                border-color: {theme['accent_color']};
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新输出框
        self._output_text.setFont(QFont("Microsoft YaHei", self._font_size))
        self._output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-size: {self._font_size}px;
            }}
            {get_scrollbar_style(theme)}
        """)

    def _clear_all(self):
        """清空所有内容"""
        self._input_text.clear()
        self._output_text.clear()

    def _start_translation(self):
        """开始翻译"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        # 取消之前的翻译
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._streaming_text = ""

        # 禁用按钮
        self._translate_btn.setEnabled(False)
        self._translate_btn.setText("翻译中...")

        # 获取目标语言
        target_language = self._lang_combo.currentText()
        if target_language == "自动检测":
            target_language = None  # 使用自动检测

        # 启动翻译线程
        self._current_worker = StreamingTranslationWorker(text, target_language)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.translation_finished.connect(self._on_translation_finished)
        self._current_worker.translation_error.connect(self._on_translation_error)
        self._current_worker.start()

    def _on_chunk_received(self, chunk: str):
        """收到翻译片段"""
        if not hasattr(self, '_streaming_text'):
            self._streaming_text = ""
        self._streaming_text += chunk
        self._output_text.setPlainText(self._streaming_text)

    def _on_translation_finished(self, result: str):
        """翻译完成"""
        self._translate_btn.setEnabled(True)
        self._translate_btn.setText("翻译")
        self._current_worker = None

        # 保存翻译历史
        if result:
            try:
                from utils.history import add_translation_history
                target_lang = self._lang_combo.currentText()
                if target_lang == "自动检测":
                    target_lang = "中文"  # 默认
                add_translation_history(
                    self._input_text.toPlainText(),
                    result,
                    target_lang,
                    "manual"
                )
            except Exception:
                pass

    def _on_translation_error(self, error: str):
        """翻译错误"""
        self._output_text.setPlainText(f"翻译失败: {error}")
        self._translate_btn.setEnabled(True)
        self._translate_btn.setText("翻译")
        self._current_worker = None

    def _show_input_context_menu(self, pos):
        """显示输入框右键菜单"""
        from PyQt6.QtWidgets import QMenu
        theme = get_theme(self._theme_style)

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_style(theme))

        undo_action = menu.addAction("撤销")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._input_text.undo)

        redo_action = menu.addAction("重做")
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self._input_text.redo)

        menu.addSeparator()

        cut_action = menu.addAction("剪切")
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(self._input_text.cut)

        copy_action = menu.addAction("复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._input_text.copy)

        paste_action = menu.addAction("粘贴")
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self._input_text.paste)

        menu.addSeparator()

        delete_action = menu.addAction("删除")
        delete_action.triggered.connect(self._input_text.textCursor().removeSelectedText)

        menu.addSeparator()

        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self._input_text.selectAll)

        clear_action = menu.addAction("清空")
        clear_action.triggered.connect(self._input_text.clear)

        menu.exec(self._input_text.mapToGlobal(pos))

    def _show_output_context_menu(self, pos):
        """显示输出框右键菜单"""
        from PyQt6.QtWidgets import QMenu
        theme = get_theme(self._theme_style)

        menu = QMenu(self)
        menu.setStyleSheet(get_menu_style(theme))

        copy_action = menu.addAction("复制")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self._output_text.copy)

        copy_all_action = menu.addAction("复制全部译文")
        copy_all_action.triggered.connect(lambda: QApplication.clipboard().setText(self._output_text.toPlainText()))

        menu.addSeparator()

        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self._output_text.selectAll)

        menu.exec(self._output_text.mapToGlobal(pos))

    def _is_over_title_bar_buttons(self, pos: QPoint) -> bool:
        """判断鼠标是否在标题栏按钮区域内（包括按钮之间的间距）"""
        title_bar_height = 28
        # 首先检查是否在标题栏区域
        if pos.y() > title_bar_height:
            return False

        # 计算按钮区域（三个按钮都在标题栏右侧）
        # 按钮大小 20x20
        button_width = 20
        total_buttons_width = button_width * 3 + 8  # 三个按钮，额外8px间距余量

        # 标题栏右边距
        right_margin = 8

        # 按钮区域的左边界
        window_width = self.width()
        buttons_left = window_width - right_margin - total_buttons_width

        # 检查鼠标是否在按钮区域内
        return pos.x() >= buttons_left

    def _get_resize_edge(self, pos: QPoint) -> Optional[str]:
        """判断鼠标位置对应的调整边缘"""
        # 增大边缘检测区域，提高灵敏度（从8px增加到12px）
        margin = 12
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()

        edge = None

        if x <= margin and y <= margin:
            edge = 'top-left'
        elif x >= w - margin and y <= margin:
            edge = 'top-right'
        elif x <= margin and y >= h - margin:
            edge = 'bottom-left'
        elif x >= w - margin and y >= h - margin:
            edge = 'bottom-right'
        elif x <= margin:
            edge = 'left'
        elif x >= w - margin:
            edge = 'right'
        elif y <= margin:
            edge = 'top'
        elif y >= h - margin:
            edge = 'bottom'

        return edge

    def _update_cursor_for_edge(self, edge: Optional[str]):
        """根据边缘更新鼠标光标"""
        cursor_shape = Qt.CursorShape.ArrowCursor
        if edge == 'top-left' or edge == 'bottom-right':
            cursor_shape = Qt.CursorShape.SizeFDiagCursor
        elif edge == 'top-right' or edge == 'bottom-left':
            cursor_shape = Qt.CursorShape.SizeBDiagCursor
        elif edge == 'left' or edge == 'right':
            cursor_shape = Qt.CursorShape.SizeHorCursor
        elif edge == 'top' or edge == 'bottom':
            cursor_shape = Qt.CursorShape.SizeVerCursor

        self.setCursor(QCursor(cursor_shape))

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            title_bar_height = 28
            # 只有在标题栏的非按钮区域才开始拖动
            if pos.y() <= title_bar_height and not self._is_over_title_bar_buttons(pos):
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()
            else:
                edge = self._get_resize_edge(pos)
                if edge:
                    self._is_resizing = True
                    self._resize_edge = edge
                    self._resize_start_pos = event.globalPosition().toPoint()
                    self._resize_start_geometry = self.geometry()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        pos = event.position().toPoint()

        if self._is_dragging and self._drag_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_window_start_pos + delta
            self.move(new_pos)
        elif self._is_resizing and self._resize_start_pos:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geo = self._resize_start_geometry

            new_x, new_y, new_w, new_h = geo.x(), geo.y(), geo.width(), geo.height()

            edge = self._resize_edge
            if 'left' in edge:
                new_w = geo.width() - delta.x()
                new_x = geo.x() + delta.x()
            if 'right' in edge:
                new_w = geo.width() + delta.x()
            if 'top' in edge:
                new_h = geo.height() - delta.y()
                new_y = geo.y() + delta.y()
            if 'bottom' in edge:
                new_h = geo.height() + delta.y()

            new_w = max(self.minimumWidth(), new_w)
            new_h = max(self.minimumHeight(), new_h)

            if 'left' in edge:
                new_x = geo.x() + geo.width() - new_w
            if 'top' in edge:
                new_y = geo.y() + geo.height() - new_h

            self.setGeometry(new_x, new_y, new_w, new_h)
        else:
            # 智能光标控制
            title_bar_height = 28
            # 1. 首先检查边框调整区域
            edge = self._get_resize_edge(pos)
            if edge:
                self._update_cursor_for_edge(edge)
            # 2. 检查是否在标题栏非按钮区域（显示拖动光标）
            elif pos.y() <= title_bar_height and not self._is_over_title_bar_buttons(pos):
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            # 3. 其他区域显示默认箭头光标
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_pos = None
            self._is_resizing = False
            self._resize_edge = None

        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        # 鼠标离开窗口时恢复默认光标
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def closeEvent(self, event):
        """窗口关闭事件"""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        event.ignore()
        self.hide()

    def show_window(self):
        """显示窗口"""
        self.update_theme()

        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2
            y = (screen_geo.height() - self.height()) // 2
            self.move(x, y)

        self.show()
        self.raise_()
        self.activateWindow()
        self._input_text.setFocus()

    def keyPressEvent(self, event):
        """键盘事件处理"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return

        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self._start_translation()
                return

        super().keyPressEvent(event)


# 全局翻译窗口实例
_translator_window_instance: Optional[TranslatorWindow] = None


def get_translator_window() -> TranslatorWindow:
    """获取全局翻译窗口实例"""
    global _translator_window_instance
    if _translator_window_instance is None:
        _translator_window_instance = TranslatorWindow()
    return _translator_window_instance