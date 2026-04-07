"""翻译历史窗口模块 - 显示和管理翻译历史"""
from typing import Optional, List
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QFrame,
    QGraphicsDropShadowEffect, QLineEdit, QDialog,
    QAbstractItemView, QSplitter, QScrollArea
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QRect
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QIcon

try:
    from ..utils.history import get_history, HistoryItem
    from ..utils.theme import get_theme, get_scrollbar_style, get_splitter_style
    from ..config import APP_NAME, get_config
except ImportError:
    from utils.history import get_history, HistoryItem
    from utils.theme import get_theme, get_scrollbar_style, get_splitter_style
    from config import APP_NAME, get_config


class HistoryWindow(QWidget):
    """翻译历史窗口（无边框风格，支持调整大小和主题切换）"""

    # 信号
    item_selected = pyqtSignal(str, str)  # 原文, 译文

    def __init__(self):
        super().__init__()

        # 设置窗口对象名称，用于识别
        self.setObjectName("HistoryWindow")

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

        # 设置无边框窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(550, 450)
        self.resize(700, 600)

        # 开启鼠标追踪
        self.setMouseTracking(True)

        self._history = get_history()
        self._setup_ui()
        self._load_history()

    def _setup_ui(self):
        """设置UI"""
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
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(*theme['shadow_color']))
        shadow.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(shadow)

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

        self._title_label = QLabel("翻译历史")
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 清空按钮
        self._clear_btn = QPushButton("清空")
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                font-size: 12px;
                padding: 2px 8px;
            }}
            QPushButton:hover {{
                color: {theme['close_hover']};
            }}
        """)
        self._clear_btn.clicked.connect(self._clear_history)
        title_layout.addWidget(self._clear_btn)

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

        # 搜索栏
        search_bar = QFrame()
        search_bar.setStyleSheet("QFrame { background-color: transparent; }")
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索历史...")
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['input_border']};
                border-radius: 4px;
                padding: 8px;
                color: {theme['text_primary']};
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {theme['accent_color']}; }}
        """)
        self._search_input.textChanged.connect(self._search_history)
        search_layout.addWidget(self._search_input)

        content_layout.addWidget(search_bar)

        # 分割器 - 历史列表和详情
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setStyleSheet(get_splitter_style(theme))
        self._splitter.setHandleWidth(8)
        self._splitter.setChildrenCollapsible(False)

        # 历史列表
        self._history_list = QListWidget()
        self._history_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                color: {theme['text_primary']};
                font-size: 13px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
                margin: 2px;
            }}
            QListWidget::item:selected {{
                background-color: {theme['accent_color']};
                color: #ffffff;
            }}
            QListWidget::item:hover {{
                background-color: {theme['list_item_hover']};
            }}
            {get_scrollbar_style(theme)}
        """)
        self._history_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._history_list.itemClicked.connect(self._on_item_clicked)
        self._history_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._splitter.addWidget(self._history_list)

        # 详情面板 - 使用滚动区域
        self._detail_scroll = QScrollArea()
        self._detail_scroll.setWidgetResizable(True)
        self._detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._detail_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
            {get_scrollbar_style(theme)}
        """)

        # 详情内容容器
        self._detail_container = QWidget()
        self._detail_container.setStyleSheet(f"background-color: {theme['bg_secondary']};")
        detail_layout = QVBoxLayout(self._detail_container)
        detail_layout.setContentsMargins(15, 12, 15, 12)
        detail_layout.setSpacing(10)

        # 详情标题
        self._detail_title = QLabel("详情")
        self._detail_title.setStyleSheet(f"""
            QLabel {{
                color: {theme['accent_color']};
                font-size: 13px;
                font-weight: bold;
            }}
        """)
        detail_layout.addWidget(self._detail_title)

        # 原文标签
        self._original_label_title = QLabel("原文：")
        self._original_label_title.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)
        detail_layout.addWidget(self._original_label_title)

        # 原文显示
        self._original_detail = QLabel()
        self._original_detail.setStyleSheet(f"""
            QLabel {{
                color: {theme['original_text']};
                font-size: 13px;
                line-height: 1.5;
            }}
        """)
        self._original_detail.setWordWrap(True)
        self._original_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_layout.addWidget(self._original_detail)

        # 分隔线
        self._separator1 = QFrame()
        self._separator1.setFixedHeight(1)
        self._separator1.setStyleSheet(f"QFrame {{ background-color: {theme['border_color']}; margin: 5px 0; }}")
        detail_layout.addWidget(self._separator1)

        # 译文标签
        self._translated_label_title = QLabel("译文：")
        self._translated_label_title.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)
        detail_layout.addWidget(self._translated_label_title)

        # 译文显示
        self._translated_detail = QLabel()
        self._translated_detail.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_primary']};
                font-size: 14px;
                line-height: 1.6;
            }}
        """)
        self._translated_detail.setWordWrap(True)
        self._translated_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_layout.addWidget(self._translated_detail, 1)

        # 分隔线
        self._separator2 = QFrame()
        self._separator2.setFixedHeight(1)
        self._separator2.setStyleSheet(f"QFrame {{ background-color: {theme['border_color']}; margin: 5px 0; }}")
        detail_layout.addWidget(self._separator2)

        # 时间和语言信息
        self._meta_label = QLabel()
        self._meta_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 13px;
            }}
        """)
        detail_layout.addWidget(self._meta_label)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # 复制原文按钮
        self._copy_original_btn = QPushButton("复制原文")
        self._copy_original_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        self._copy_original_btn.clicked.connect(self._copy_original)
        btn_layout.addWidget(self._copy_original_btn)

        # 复制译文按钮
        self._copy_btn = QPushButton("复制译文")
        self._copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
        """)
        self._copy_btn.clicked.connect(self._copy_translated)
        btn_layout.addWidget(self._copy_btn)

        btn_layout.addStretch()
        detail_layout.addLayout(btn_layout)

        self._detail_scroll.setWidget(self._detail_container)
        self._splitter.addWidget(self._detail_scroll)
        self._splitter.setSizes([250, 350])

        content_layout.addWidget(self._splitter, 1)

        # 底部状态栏
        self._status_label = QLabel()
        self._status_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
                padding: 4px;
            }}
        """)
        content_layout.addWidget(self._status_label)

        # 当前选中的历史条目
        self._current_item: Optional[HistoryItem] = None

    def update_theme(self):
        """更新主题"""
        new_theme = get_config().get('theme.popup_style', 'dark')
        if new_theme != self._theme_style:
            self._theme_style = new_theme
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

        # 更新关闭按钮
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

        # 更新最小化按钮
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

        # 更新最大化按钮
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

        # 更新搜索框
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['input_border']};
                border-radius: 4px;
                padding: 8px;
                color: {theme['text_primary']};
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {theme['accent_color']}; }}
        """)

        # 更新分割器
        self._splitter.setStyleSheet(get_splitter_style(theme))

        # 更新历史列表
        self._history_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                color: {theme['text_primary']};
                font-size: 13px;
                padding: 4px;
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
                margin: 2px;
            }}
            QListWidget::item:selected {{
                background-color: {theme['accent_color']};
                color: #ffffff;
            }}
            QListWidget::item:hover {{
                background-color: {theme['list_item_hover']};
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新详情区域
        self._detail_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
            }}
            {get_scrollbar_style(theme)}
        """)

        self._detail_container.setStyleSheet(f"background-color: {theme['bg_secondary']};")

        # 更新详情标题
        self._detail_title.setStyleSheet(f"""
            QLabel {{
                color: {theme['accent_color']};
                font-size: 13px;
                font-weight: bold;
            }}
        """)

        # 更新原文标签
        self._original_label_title.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)

        # 更新原文显示
        self._original_detail.setStyleSheet(f"""
            QLabel {{
                color: {theme['original_text']};
                font-size: 13px;
                line-height: 1.5;
            }}
        """)

        # 更新分隔线
        self._separator1.setStyleSheet(f"QFrame {{ background-color: {theme['border_color']}; margin: 5px 0; }}")
        self._separator2.setStyleSheet(f"QFrame {{ background-color: {theme['border_color']}; margin: 5px 0; }}")

        # 更新译文标签
        self._translated_label_title.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)

        # 更新译文显示
        self._translated_detail.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_primary']};
                font-size: 14px;
                line-height: 1.6;
            }}
        """)

        # 更新元信息标签
        self._meta_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 13px;
            }}
        """)

        # 更新按钮
        self._copy_original_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)

        self._copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
        """)

        # 更新状态栏
        self._status_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
                padding: 4px;
            }}
        """)

        # 更新清空按钮
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                font-size: 12px;
                padding: 2px 8px;
            }}
            QPushButton:hover {{
                color: {theme['close_hover']};
            }}
        """)

    def _load_history(self):
        """加载历史记录"""
        self._history_list.clear()
        items = self._history.get_history()

        for item in items:
            # 显示原文前50字符作为列表项
            display_text = item.original_text[:50]
            if len(item.original_text) > 50:
                display_text += "..."

            list_item = QListWidgetItem(f"[{item.timestamp}] {display_text}")
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._history_list.addItem(list_item)

        self._status_label.setText(f"共 {len(items)} 条记录")

    def _search_history(self, keyword: str):
        """搜索历史"""
        self._history_list.clear()

        if keyword.strip():
            items = self._history.search_history(keyword)
        else:
            items = self._history.get_history()

        for item in items:
            display_text = item.original_text[:50]
            if len(item.original_text) > 50:
                display_text += "..."

            list_item = QListWidgetItem(f"[{item.timestamp}] {display_text}")
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._history_list.addItem(list_item)

        self._status_label.setText(f"找到 {len(items)} 条记录")

    def _on_item_clicked(self, list_item: QListWidgetItem):
        """单击选中条目"""
        self._current_item = list_item.data(Qt.ItemDataRole.UserRole)
        if self._current_item:
            self._original_detail.setText(self._current_item.original_text)
            self._translated_detail.setText(self._current_item.translated_text)
            self._meta_label.setText(
                f"时间: {self._current_item.timestamp}  |  "
                f"语言: {self._current_item.target_language}  |  "
                f"来源: {self._current_item.source}"
            )

    def _on_item_double_clicked(self, list_item: QListWidgetItem):
        """双击选中条目 - 发送信号"""
        item = list_item.data(Qt.ItemDataRole.UserRole)
        if item:
            self.item_selected.emit(item.original_text, item.translated_text)

    def _copy_original(self):
        """复制原文"""
        if self._current_item:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self._current_item.original_text)
            self._status_label.setText("原文已复制到剪贴板")

    def _copy_translated(self):
        """复制译文"""
        if self._current_item:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self._current_item.translated_text)
            self._status_label.setText("译文已复制到剪贴板")

    def _clear_history(self):
        """清空历史"""
        theme = get_theme(self._theme_style)

        # 使用无边框确认框
        dialog = QDialog()
        dialog.setObjectName("ConfirmDialog")
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setMinimumSize(320, 180)
        dialog.setModal(True)

        # 内容框架
        content_frame = QFrame(dialog)
        content_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {theme['border_color']};
            }}
        """)
        content_frame.setFixedSize(320, 180)

        # 布局
        layout = QVBoxLayout(content_frame)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(12)

        # 标题栏
        title_bar = QFrame()
        title_bar.setFixedHeight(24)
        title_bar.setStyleSheet("QFrame { background-color: transparent; }")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        icon_label = QLabel("●")
        icon_label.setStyleSheet("color: #ff9800; font-size: 20px;")
        icon_label.setFixedSize(24, 24)

        title_label = QLabel("确认清空")
        title_label.setStyleSheet(f"color: {theme['text_primary']}; font-size: 14px; font-weight: bold;")

        title_layout.addWidget(icon_label)
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        # 关闭按钮
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['close_hover']};
                color: #ffffff;
            }}
        """)
        close_btn.clicked.connect(dialog.reject)
        title_layout.addWidget(close_btn)

        layout.addWidget(title_bar)

        # 消息内容
        msg_label = QLabel("确定要清空所有翻译历史吗？\n此操作不可撤销。")
        msg_label.setStyleSheet(f"color: {theme['text_secondary']}; font-size: 13px;")
        msg_label.setWordWrap(True)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 32)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        cancel_btn.clicked.connect(dialog.reject)

        ok_btn = QPushButton("确定")
        ok_btn.setFixedSize(80, 32)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        ok_btn.clicked.connect(dialog.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addSpacing(10)
        btn_layout.addWidget(ok_btn)

        layout.addWidget(msg_label, 1)
        layout.addLayout(btn_layout)

        # 显示并居中
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - 320) // 2 + screen_geo.x()
            y = (screen_geo.height() - 180) // 2 + screen_geo.y()
            dialog.move(x, y)

        # 使用 exec() 等待用户确认
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._history.clear_history()
            self._load_history()
            self._current_item = None
            self._original_detail.clear()
            self._translated_detail.clear()
            self._meta_label.clear()

    def _is_over_title_bar_buttons(self, pos: QPoint) -> bool:
        """判断鼠标是否在标题栏按钮区域内（包括按钮之间的间距）"""
        title_bar_height = 28
        # 首先检查是否在标题栏区域
        if pos.y() > title_bar_height:
            return False

        # history_window 的按钮区域包括：清空按钮、最小化、最大化、关闭按钮
        # 清空按钮在左侧，三个窗口控制按钮在右侧
        # 窗口控制按钮大小 20x20，右侧有三个按钮
        button_width = 20
        total_buttons_width = button_width * 3 + 8  # 三个按钮，额外8px间距余量

        # 标题栏右边距
        right_margin = 8

        # 右侧按钮区域的左边界
        window_width = self.width()
        buttons_left = window_width - right_margin - total_buttons_width

        # 左侧的清空按钮区域（大约 40px 左右）
        clear_button_width = 40
        left_margin = 8
        clear_button_right = left_margin + clear_button_width + 8  # 额外8px余量

        # 检查鼠标是否在按钮区域内（左侧清空按钮或右侧三个控制按钮）
        return pos.x() >= buttons_left or (pos.x() <= clear_button_right)

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

    def show_window(self):
        """显示窗口"""
        # 检查并更新主题
        self.update_theme()

        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2 + screen_geo.x()
            y = (screen_geo.height() - self.height()) // 2 + screen_geo.y()
            self.move(x, y)

        self._load_history()  # 刷新历史
        self.show()
        self.raise_()
        self.activateWindow()

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


# 全局历史窗口实例
_history_window_instance: Optional[HistoryWindow] = None


def get_history_window() -> HistoryWindow:
    """获取全局历史窗口实例"""
    global _history_window_instance
    if _history_window_instance is None:
        _history_window_instance = HistoryWindow()
    return _history_window_instance