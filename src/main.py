"""Translate Copilot - 主入口文件"""
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFormLayout, QComboBox,
    QCheckBox, QGroupBox, QMessageBox, QSizePolicy, QFrame,
    QGraphicsDropShadowEffect, QScrollArea, QMenu, QWidget,
    QSpinBox, QKeySequenceEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QPoint, QTimer, QPropertyAnimation, QRect
from PyQt6.QtGui import QFont, QColor, QCursor, QMouseEvent, QAction, QIcon, QPixmap, QPainter, QPen, QKeySequence

# 设置高 DPI 支持
if sys.platform == 'win32':
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwareness(2)
    except Exception:
        pass

# 支持两种导入方式
try:
    from .config import get_config, APP_NAME
    from .core.text_capture import get_text_capture, capture_text_direct
    from .core.selection_detector import get_selection_detector
    from .core.hover_detector import get_hover_detector
    from .core.translator import get_translator, TranslationResult
    from .core.writing import get_writing_service, WritingResult
    from .ui.popup_window import get_popup_window
    from .ui.translate_button import get_translate_button
    from .ui.tray_icon import get_tray_icon
    from .ui.translator_window import get_translator_window
    from .ui.history_window import get_history_window
    from .ui.help_window import get_help_window
    from .utils.logger import get_logger, log_info, log_error, log_debug
    from .utils.history import add_translation_history
    from .utils.theme import get_theme, get_scrollbar_style, get_lineedit_style, get_combobox_style, get_checkbox_style
    from .utils.hotkey_manager import get_hotkey_manager
except ImportError:
    from config import get_config, APP_NAME
    from core.text_capture import get_text_capture, capture_text_direct
    from core.selection_detector import get_selection_detector
    from core.hover_detector import get_hover_detector
    from core.translator import get_translator, TranslationResult
    from core.writing import get_writing_service, WritingResult
    from ui.popup_window import get_popup_window
    from ui.translate_button import get_translate_button
    from ui.tray_icon import get_tray_icon
    from ui.translator_window import get_translator_window
    from ui.history_window import get_history_window
    from ui.help_window import get_help_window
    from utils.logger import get_logger, log_info, log_error, log_debug
    from utils.history import add_translation_history
    from utils.theme import get_theme, get_scrollbar_style, get_lineedit_style, get_combobox_style, get_checkbox_style
    from utils.hotkey_manager import get_hotkey_manager


def setup_auto_start(enable: bool):
    """设置开机自启（Windows）"""
    if sys.platform != 'win32':
        return False
    
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_id = APP_NAME.replace(" ", "")
        
        if enable:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                main_py = Path(__file__).parent.parent / "__main__.py"
                exe_path = f'"{sys.executable}" "{main_py}"'
            
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, app_id, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            return True
        else:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, app_id)
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
            return True
    except Exception as e:
        log_error(f"设置开机自启失败: {e}")
        return False


class SettingsDialog(QDialog):
    """设置对话框（无边框风格）"""

    def __init__(self, popup_window=None):
        super().__init__()

        # 设置窗口对象名称，用于识别
        self.setObjectName("SettingsDialog")

        # 拖动状态
        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        # 保存 popup_window 引用（可能是 None）
        self._popup_window = popup_window

        # 主题
        self._theme = get_theme()

        # 设置无边框窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(480, 520)
        self.resize(500, 580)

        self._config = get_config()
        self._setup_ui()
        self._load_settings()

        # 应用主题
        self._apply_theme()

        # 居中显示
        self._center_window()

    def _center_window(self):
        """窗口居中显示"""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2 + screen_geo.x()
            y = (screen_geo.height() - self.height()) // 2 + screen_geo.y()
            self.move(x, y)

    def _setup_ui(self):
        """设置UI（无边框风格）- 只创建控件，样式由 _apply_theme 设置"""
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 内容容器
        self._content_frame = QFrame()
        self._content_frame.setObjectName("contentFrame")
        layout.addWidget(self._content_frame)

        # 添加阴影效果
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(shadow)

        # 内容布局
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(12)

        # 标题栏
        self._title_bar = QFrame()
        self._title_bar.setFixedHeight(28)
        # 不设置整体光标，在 mouseMoveEvent 中动态控制

        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 0, 8, 0)

        # 标题文字
        self._title_label = QLabel("设置")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 关闭按钮
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.clicked.connect(self.reject)
        title_layout.addWidget(self._close_btn)

        content_layout.addWidget(self._title_bar)

        # 滚动区域
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 滚动内容容器
        self._scroll_content = QWidget()
        scroll_layout = QVBoxLayout(self._scroll_content)
        scroll_layout.setSpacing(16)
        scroll_layout.setContentsMargins(8, 8, 8, 8)

        # API 设置组
        self._api_group = QGroupBox("API 设置")
        api_layout = QFormLayout(self._api_group)
        api_layout.setSpacing(10)
        api_layout.setContentsMargins(12, 20, 12, 12)
        api_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("输入 API Key")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
        self._api_key_input.setMinimumHeight(32)
        self._api_key_label = QLabel("API Key:")
        api_layout.addRow(self._api_key_label, self._api_key_input)

        self._base_url_input = QLineEdit()
        self._base_url_input.setPlaceholderText("例如: https://api.openai.com/v1")
        self._base_url_input.setMinimumHeight(32)
        self._base_url_label = QLabel("Base URL:")
        api_layout.addRow(self._base_url_label, self._base_url_input)

        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("模型名称")
        self._model_input.setMinimumHeight(32)
        self._model_label = QLabel("模型:")
        api_layout.addRow(self._model_label, self._model_input)

        scroll_layout.addWidget(self._api_group)

        # 翻译设置组
        self._trans_group = QGroupBox("翻译设置")
        trans_layout = QFormLayout(self._trans_group)
        trans_layout.setSpacing(10)
        trans_layout.setContentsMargins(12, 20, 12, 12)
        trans_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._target_lang_combo = QComboBox()
        self._target_lang_combo.addItems(["中文", "英文", "日文", "韩文", "法文", "德文", "西班牙文"])
        self._target_lang_combo.setMinimumHeight(32)
        self._target_lang_label = QLabel("目标语言:")
        trans_layout.addRow(self._target_lang_label, self._target_lang_combo)

        scroll_layout.addWidget(self._trans_group)

        # 外观设置组
        self._theme_group = QGroupBox("外观设置")
        theme_layout = QFormLayout(self._theme_group)
        theme_layout.setSpacing(10)
        theme_layout.setContentsMargins(12, 20, 12, 12)
        theme_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._popup_style_combo = QComboBox()
        self._popup_style_combo.addItems(["深色", "浅色"])
        self._popup_style_combo.setMinimumHeight(32)
        self._popup_style_label = QLabel("窗口样式:")
        theme_layout.addRow(self._popup_style_label, self._popup_style_combo)

        scroll_layout.addWidget(self._theme_group)

        # 字体设置组
        self._font_group = QGroupBox("字体设置")
        font_layout = QFormLayout(self._font_group)
        font_layout.setSpacing(10)
        font_layout.setContentsMargins(12, 20, 12, 12)
        font_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 24)
        self._font_size_spin.setValue(14)
        self._font_size_spin.setMinimumHeight(32)
        self._font_size_spin.setSuffix(" px")
        self._font_size_label = QLabel("字体大小:")
        font_layout.addRow(self._font_size_label, self._font_size_spin)

        scroll_layout.addWidget(self._font_group)

        # 快捷键设置组
        self._hotkey_group = QGroupBox("快捷键设置")
        hotkey_layout = QFormLayout(self._hotkey_group)
        hotkey_layout.setSpacing(10)
        hotkey_layout.setContentsMargins(12, 20, 12, 12)
        hotkey_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._hotkey_edit = QKeySequenceEdit()
        self._hotkey_edit.setMinimumHeight(32)
        self._hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+T"))
        self._hotkey_label = QLabel("唤醒翻译窗口:")
        hotkey_layout.addRow(self._hotkey_label, self._hotkey_edit)

        # 写作快捷键
        self._writing_hotkey_edit = QKeySequenceEdit()
        self._writing_hotkey_edit.setMinimumHeight(32)
        self._writing_hotkey_edit.setKeySequence(QKeySequence("Ctrl+Shift+W"))
        self._writing_hotkey_label = QLabel("划词写作:")
        hotkey_layout.addRow(self._writing_hotkey_label, self._writing_hotkey_edit)

        scroll_layout.addWidget(self._hotkey_group)

        # 写作设置组
        self._writing_group = QGroupBox("写作设置")
        writing_layout = QVBoxLayout(self._writing_group)
        writing_layout.setSpacing(8)
        writing_layout.setContentsMargins(12, 20, 12, 12)

        self._keep_original_check = QCheckBox("保留原文")
        self._keep_original_check.toggled.connect(self._on_checkbox_toggled)
        writing_layout.addWidget(self._keep_original_check)

        # 添加说明文字
        self._writing_hint_label = QLabel("勾选后，写作时会在原文下方另起一行插入翻译结果")
        self._writing_hint_label.setStyleSheet(f"color: {self._theme['text_muted']}; font-size: 11px;")
        self._writing_hint_label.setWordWrap(True)
        writing_layout.addWidget(self._writing_hint_label)

        scroll_layout.addWidget(self._writing_group)

        # 系统设置组
        self._sys_group = QGroupBox("系统设置")
        sys_layout = QVBoxLayout(self._sys_group)
        sys_layout.setSpacing(8)
        sys_layout.setContentsMargins(12, 20, 12, 12)

        self._auto_start_check = QCheckBox("开机自动启动")
        self._auto_start_check.toggled.connect(self._on_checkbox_toggled)
        sys_layout.addWidget(self._auto_start_check)

        scroll_layout.addWidget(self._sys_group)

        self._scroll_area.setWidget(self._scroll_content)
        content_layout.addWidget(self._scroll_area, 1)

        # 底部按钮栏
        self._btn_bar = QFrame()
        btn_layout = QHBoxLayout(self._btn_bar)
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.setFixedHeight(32)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("保存")
        self._save_btn.setFixedHeight(32)
        self._save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(self._save_btn)

        content_layout.addWidget(self._btn_bar)

    def _create_check_icon(self) -> QIcon:
        """创建勾选图标"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制蓝色圆角背景
        painter.setBrush(QColor(self._theme['accent_color']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 18, 18, 4, 4)

        # 绘制白色勾选符号 ✓
        painter.setPen(QPen(QColor(255, 255, 255), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(4, 9, 7, 13)  # 左下到中下
        painter.drawLine(7, 13, 14, 5)  # 中下到右上

        painter.end()

        return QIcon(pixmap)

    def _create_uncheck_icon(self) -> QIcon:
        """创建未勾选图标（空白边框）"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制边框
        painter.setBrush(QColor(self._theme['input_bg']))
        painter.setPen(QPen(QColor(self._theme['scrollbar_handle']), 1.5))
        painter.drawRoundedRect(0, 0, 18, 18, 4, 4)

        painter.end()

        return QIcon(pixmap)

    def _get_groupbox_style(self) -> str:
        """获取分组框样式"""
        return f"""
            QGroupBox {{
                color: {self._theme['group_title']};
                font-size: 14px;
                font-weight: bold;
                border: 1px solid {self._theme['border_color']};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 8px;
                background-color: transparent;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """

    def _create_check_icon(self) -> QIcon:
        """创建勾选图标"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制蓝色圆角背景
        painter.setBrush(QColor(self._theme['accent_color']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 18, 18, 4, 4)

        # 绘制白色勾选符号 ✓
        painter.setPen(QPen(QColor(255, 255, 255), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(4, 9, 7, 14)  # 左下到中下
        painter.drawLine(7, 14, 14, 5)  # 中下到右上

        painter.end()

        return QIcon(pixmap)

    def _apply_theme(self):
        """应用主题样式"""
        # 内容容器
        self._content_frame.setStyleSheet(f"""
            QFrame#contentFrame {{
                background-color: {self._theme['bg_color']};
                border-radius: 8px;
                border: 1px solid {self._theme['border_color']};
            }}
        """)

        # 标题栏
        self._title_bar.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
                border-bottom: 1px solid {self._theme['border_color']};
            }}
            QFrame:hover {{
                background-color: {self._theme['border_color']};
            }}
        """)

        # 标题文字
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {self._theme['text_muted']};
                font-size: 12px;
            }}
        """)

        # 关闭按钮
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {self._theme['text_muted']};
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self._theme['close_hover']};
                color: #ffffff;
            }}
        """)

        # 滚动区域
        self._scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            {get_scrollbar_style(self._theme)}
        """)

        # 滚动内容容器
        self._scroll_content.setStyleSheet("background-color: transparent;")

        # 分组框样式
        groupbox_style = self._get_groupbox_style()
        self._api_group.setStyleSheet(groupbox_style)
        self._trans_group.setStyleSheet(groupbox_style)
        self._theme_group.setStyleSheet(groupbox_style)
        self._font_group.setStyleSheet(groupbox_style)
        self._hotkey_group.setStyleSheet(groupbox_style)
        self._writing_group.setStyleSheet(groupbox_style)
        self._sys_group.setStyleSheet(groupbox_style)

        # 输入框样式
        lineedit_style = get_lineedit_style(self._theme)
        self._api_key_input.setStyleSheet(lineedit_style)
        self._base_url_input.setStyleSheet(lineedit_style)
        self._model_input.setStyleSheet(lineedit_style)

        # 标签样式
        label_style = f"color: {self._theme['text_secondary']}; font-size: 13px;"
        self._api_key_label.setStyleSheet(label_style)
        self._base_url_label.setStyleSheet(label_style)
        self._model_label.setStyleSheet(label_style)
        self._target_lang_label.setStyleSheet(label_style)
        self._popup_style_label.setStyleSheet(label_style)
        self._font_size_label.setStyleSheet(label_style)
        self._hotkey_label.setStyleSheet(label_style)
        self._writing_hotkey_label.setStyleSheet(label_style)

        # 下拉框样式
        combobox_style = get_combobox_style(self._theme)
        self._target_lang_combo.setStyleSheet(combobox_style)
        self._popup_style_combo.setStyleSheet(combobox_style)

        # 字体大小设置
        self._font_size_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {self._theme['input_bg']};
                border: 1px solid {self._theme['input_border']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {self._theme['text_primary']};
                font-size: 13px;
            }}
            QSpinBox:focus {{
                border-color: {self._theme['accent_color']};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 16px;
            }}
        """)

        # 快捷键设置
        hotkey_style = f"""
            QKeySequenceEdit {{
                background-color: {self._theme['input_bg']};
                border: 1px solid {self._theme['input_border']};
                border-radius: 4px;
                padding: 4px 8px;
                color: {self._theme['text_primary']};
                font-size: 13px;
            }}
            QKeySequenceEdit:focus {{
                border-color: {self._theme['accent_color']};
            }}
        """
        self._hotkey_edit.setStyleSheet(hotkey_style)
        self._writing_hotkey_edit.setStyleSheet(hotkey_style)

        # 复选框样式和图标
        checkbox_style = get_checkbox_style(self._theme)
        self._auto_start_check.setStyleSheet(checkbox_style)
        self._keep_original_check.setStyleSheet(checkbox_style)
        check_icon = self._create_check_icon()
        uncheck_icon = self._create_uncheck_icon()
        self._auto_start_check.setIcon(check_icon if self._auto_start_check.isChecked() else uncheck_icon)
        self._keep_original_check.setIcon(check_icon if self._keep_original_check.isChecked() else uncheck_icon)

        # 底部按钮栏
        self._btn_bar.setStyleSheet("QFrame { background-color: transparent; }")

        # 取消按钮
        self._cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._theme['button_bg']};
                color: {self._theme['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 0 20px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {self._theme['button_hover']};
            }}
        """)

        # 保存按钮
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._theme['accent_color']};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 0 20px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self._theme['accent_hover']};
            }}
        """)

    def _on_checkbox_toggled(self, checked: bool):
        """复选框状态改变时更新图标"""
        sender = self.sender()
        if sender:
            check_icon = self._create_check_icon()
            uncheck_icon = self._create_uncheck_icon()
            sender.setIcon(check_icon if checked else uncheck_icon)

    def update_theme(self):
        """更新主题"""
        self._theme = get_theme()
        self._apply_theme()

    def _is_over_title_bar_button(self, pos: QPoint) -> bool:
        """判断鼠标是否在标题栏按钮区域内"""
        title_bar_height = 28
        # 首先检查是否在标题栏区域
        if pos.y() > title_bar_height:
            return False

        # 关闭按钮在标题栏右侧，按钮大小 20x20
        button_width = 20
        right_margin = 8

        # 按钮区域的左边界
        window_width = self.width()
        button_left = window_width - right_margin - button_width - 4  # 额外4px余量

        # 检查鼠标是否在按钮区域内
        return pos.x() >= button_left

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            title_bar_height = 28
            # 只有在标题栏的非按钮区域才开始拖动
            if pos.y() <= title_bar_height and not self._is_over_title_bar_button(pos):
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动事件"""
        pos = event.position().toPoint()

        if self._is_dragging and self._drag_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_window_start_pos + delta
            self.move(new_pos)
        else:
            # 智能光标控制
            title_bar_height = 28
            # 检查是否在标题栏非按钮区域（显示拖动光标）
            if pos.y() <= title_bar_height and not self._is_over_title_bar_button(pos):
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            # 其他区域显示默认箭头光标
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_pos = None

        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        # 鼠标离开窗口时恢复默认光标
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def _load_settings(self):
        """加载设置"""
        self._api_key_input.setText(self._config.get('translator.api_key', ''))
        self._base_url_input.setText(self._config.get('translator.base_url', ''))
        self._model_input.setText(self._config.get('translator.model', ''))

        target_lang = self._config.get('target_language', '中文')
        index = self._target_lang_combo.findText(target_lang)
        if index >= 0:
            self._target_lang_combo.setCurrentIndex(index)

        popup_style = self._config.get('theme.popup_style', 'dark')
        self._popup_style_combo.setCurrentIndex(0 if popup_style == 'dark' else 1)

        # 字体大小
        font_size = self._config.get('font.size', 14)
        self._font_size_spin.setValue(font_size)

        # 快捷键
        hotkey = self._config.get('hotkey.translator_window', 'Ctrl+Shift+T')
        self._hotkey_edit.setKeySequence(QKeySequence(hotkey))

        # 写作快捷键
        writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+Shift+W')
        self._writing_hotkey_edit.setKeySequence(QKeySequence(writing_hotkey))

        # 保留原文选项
        keep_original = self._config.get('writing.keep_original', False)
        self._keep_original_check.setChecked(keep_original)

        self._auto_start_check.setChecked(self._config.get('startup.auto_start', False))

        # 禁用滚轮事件，避免误触
        self._disable_wheel_event(self._target_lang_combo)
        self._disable_wheel_event(self._popup_style_combo)
        self._disable_wheel_event(self._font_size_spin)

    def _disable_wheel_event(self, widget):
        """禁用控件的鼠标滚轮事件，防止误触"""
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器，用于禁用滚轮事件"""
        if event.type() == event.Type.Wheel:
            # 忽略滚轮事件
            return True
        return super().eventFilter(obj, event)

    def _save_settings(self):
        """保存设置"""
        # 暂停鼠标检测器，避免UI重操作期间钩子超时导致鼠标卡顿
        try:
            hover_detector = get_hover_detector()
            hover_detector.pause()
        except Exception:
            pass

        try:
            selection_detector = get_selection_detector()
            selection_detector.pause()
        except Exception:
            pass

        try:
            # 快捷键 - 先获取旧的热键，用于判断是否需要重新注册
            old_hotkey = self._config.get('hotkey.translator_window', 'Ctrl+Shift+T')
            new_hotkey = self._hotkey_edit.keySequence().toString()

            # 写作快捷键
            old_writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+Shift+W')
            new_writing_hotkey = self._writing_hotkey_edit.keySequence().toString()

            self._config.set('translator.api_key', self._api_key_input.text())
            self._config.set('translator.base_url', self._base_url_input.text())
            self._config.set('translator.model', self._model_input.text())
            self._config.set('target_language', self._target_lang_combo.currentText())

            popup_style = 'dark' if self._popup_style_combo.currentIndex() == 0 else 'light'
            self._config.set('theme.popup_style', popup_style)

            # 字体大小
            self._config.set('font.size', self._font_size_spin.value())

            # 快捷键
            self._config.set('hotkey.translator_window', new_hotkey)
            self._config.set('hotkey.writing', new_writing_hotkey)

            # 写作设置
            keep_original = self._keep_original_check.isChecked()
            self._config.set('writing.keep_original', keep_original)

            auto_start = self._auto_start_check.isChecked()
            self._config.set('startup.auto_start', auto_start)
            setup_auto_start(auto_start)

            self._config.save()

            # 如果热键改变了，重新注册热键
            hotkey_manager = get_hotkey_manager()
            if old_hotkey != new_hotkey:
                try:
                    hotkey_manager.update_hotkey(new_hotkey, "translator_window")
                    log_info(f"翻译窗口热键已更新: {old_hotkey} -> {new_hotkey}")
                except Exception as e:
                    log_error(f"更新翻译窗口热键失败: {e}")

            if old_writing_hotkey != new_writing_hotkey:
                try:
                    hotkey_manager.update_hotkey(new_writing_hotkey, "writing")
                    log_info(f"写作热键已更新: {old_writing_hotkey} -> {new_writing_hotkey}")
                except Exception as e:
                    log_error(f"更新写作热键失败: {e}")

            # 更新所有窗口主题
            self._update_all_themes()

            # 使用自定义提示框
            self._show_message_dialog("保存成功", "设置已保存", "info")
        finally:
            # 恢复鼠标检测器
            try:
                hover_detector = get_hover_detector()
                hover_detector.resume()
            except Exception:
                pass

            try:
                selection_detector = get_selection_detector()
                selection_detector.resume()
            except Exception:
                pass

    def _update_all_themes(self):
        """更新所有窗口的主题"""
        # 更新划词翻译弹窗
        if self._popup_window is not None:
            try:
                self._popup_window.update_theme()
            except Exception:
                pass

        # 更新翻译窗口
        try:
            translator_window = get_translator_window()
            if translator_window:
                translator_window.update_theme()
        except Exception:
            pass

        # 更新历史窗口
        try:
            history_window = get_history_window()
            if history_window:
                history_window.update_theme()
        except Exception:
            pass

        # 更新帮助窗口
        try:
            help_window = get_help_window()
            if help_window:
                help_window.update_theme()
        except Exception:
            pass

        # 更新托盘菜单
        try:
            tray_icon = get_tray_icon()
            if tray_icon:
                tray_icon.update_theme()
        except Exception:
            pass

    def _show_message_dialog(self, title: str, message: str, msg_type: str = "info"):
        """显示 toast 消息提示"""
        # 先关闭设置对话框
        self.accept()
        # 延迟显示 Toast（确保对话框已完全关闭）
        QTimer.singleShot(100, lambda: ToastWidget.show_message(title, message, msg_type))


class ToastWidget(QWidget):
    """Toast 消息提示组件"""

    # 全局列表，保持Toast引用防止被垃圾回收
    _active_toasts = []

    def __init__(self, title: str, message: str, msg_type: str = "info"):
        super().__init__(None)  # 无父窗口

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._setup_ui(title, message, msg_type)
        self._position_window()

        # 自动关闭定时器
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self._fade_out)
        self._close_timer.start(2500)  # 2.5秒后开始消失

        # 淡出动画
        self._opacity = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._do_fade)

    def _setup_ui(self, title: str, message: str, msg_type: str):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        # 根据类型设置颜色
        if msg_type == "success" or msg_type == "info":
            bg_color = "#1a7f37"
            icon = "✓"
        elif msg_type == "warning":
            bg_color = "#d29922"
            icon = "⚠"
        elif msg_type == "error":
            bg_color = "#cf222e"
            icon = "✕"
        else:
            bg_color = "#0078d4"
            icon = "✓"

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border-radius: 8px;
            }}
        """)

        # 标题
        title_label = QLabel(f"{icon} {title}")
        title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        layout.addWidget(title_label)

        # 消息
        msg_label = QLabel(message)
        msg_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 12px;
            }
        """)
        layout.addWidget(msg_label)

        # 设置固定宽度
        self.setFixedWidth(280)
        self.adjustSize()

        # 添加阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

    def _position_window(self):
        """定位窗口 - 屏幕底部中央"""
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2
            y = screen_geo.height() - self.height() - 80
            self.move(x, y)

    def _fade_out(self):
        """开始淡出"""
        self._fade_timer.start(30)  # 30ms间隔

    def _do_fade(self):
        """执行淡出动画"""
        self._opacity -= 0.05
        if self._opacity <= 0:
            self._fade_timer.stop()
            self.close()
            # 从全局列表移除引用
            if self in ToastWidget._active_toasts:
                ToastWidget._active_toasts.remove(self)
            self.deleteLater()
        else:
            self.setWindowOpacity(self._opacity)

    @staticmethod
    def show_message(title: str, message: str, msg_type: str = "info"):
        """静态方法：显示Toast消息"""
        toast = ToastWidget(title, message, msg_type)
        # 添加到全局列表，防止被垃圾回收
        ToastWidget._active_toasts.append(toast)
        toast.show()


class StreamingTranslationWorker(QThread):
    """流式翻译工作线程"""

    # 信号
    chunk_received = pyqtSignal(str)  # 收到翻译片段
    translation_finished = pyqtSignal(str, str)  # 翻译完成 (原文, 译文)
    translation_error = pyqtSignal(str, str)  # 翻译错误 (原文, 错误信息)

    def __init__(self, text: str):
        super().__init__()
        self._text = text
        self._is_cancelled = False

    def run(self):
        try:
            translator = get_translator()
            full_text = ""

            for chunk in translator.translate_stream(self._text):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.translation_finished.emit(self._text, full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.translation_error.emit(self._text, str(e))

    def cancel(self):
        """取消翻译"""
        self._is_cancelled = True


class MainController(QObject):
    """主控制器"""

    def __init__(self):
        super().__init__()

        self._config = get_config()
        self._selection_detector = get_selection_detector()
        self._popup_window = get_popup_window()
        self._translate_button = get_translate_button()
        self._tray_icon = get_tray_icon()
        self._translator = get_translator()
        self._text_capture = get_text_capture()
        self._hotkey_manager = get_hotkey_manager()
        self._writing_service = get_writing_service()

        self._current_worker: StreamingTranslationWorker = None
        self._last_text: str = ""

        self._connect_signals()
        self._check_config()
        self._setup_hotkey()

    def _connect_signals(self):
        self._selection_detector.selection_finished.connect(self._on_selection_finished)
        self._translate_button.clicked.connect(self._on_translate_button_clicked)
        self._tray_icon.enabled_changed.connect(self._on_enabled_changed)
        self._tray_icon.settings_requested.connect(self._on_settings_requested)
        self._tray_icon.exit_requested.connect(self._on_exit_requested)
        self._tray_icon.translator_window_requested.connect(self._on_translator_window_requested)
        self._tray_icon.history_requested.connect(self._on_history_requested)
        self._tray_icon.help_requested.connect(self._on_help_requested)
        self._popup_window.closed.connect(self._on_popup_closed)
        self._hotkey_manager.hotkey_triggered.connect(self._on_hotkey_triggered)
        self._hotkey_manager.writing_hotkey_triggered.connect(self._on_writing_hotkey_triggered)

    def _check_config(self):
        """检查 API 配置是否完整"""
        api_key = self._config.get('translator.api_key', '')
        base_url = self._config.get('translator.base_url', '')
        model = self._config.get('translator.model', '')

        if not api_key or not base_url or not model:
            self._tray_icon.show_message(
                "配置提示",
                "请先在托盘图标右键菜单中打开设置，填写 API Key、Base URL 和 Model",
                "warning"
            )

    def _setup_hotkey(self):
        """设置全局热键"""
        # 翻译窗口热键
        hotkey = self._config.get('hotkey.translator_window', 'Ctrl+Shift+T')
        self._hotkey_manager.register_hotkey(hotkey, name="translator_window")
        log_debug(f"已注册翻译窗口热键: {hotkey}")

        # 写作热键
        writing_hotkey = self._config.get('hotkey.writing', 'Ctrl+Shift+W')
        self._hotkey_manager.register_hotkey(writing_hotkey, name="writing")
        log_debug(f"已注册写作热键: {writing_hotkey}")

    def start(self):
        self._selection_detector.start()
        self._tray_icon.show()
        log_info(f"{APP_NAME} 已启动")

    def stop(self):
        self._selection_detector.stop()
        self._selection_detector.cleanup()

        # 停止热键监听
        self._hotkey_manager.stop()

        # 停止写作服务
        if self._writing_service:
            self._writing_service.stop_writing()

        if self._current_worker:
            self._current_worker.cancel()
            self._current_worker.quit()
            self._current_worker = None

        self._translate_button.hide()
        self._popup_window.hide()
        self._popup_window.destroy()
        self._tray_icon.hide()
        self._tray_icon.cleanup()
        self._text_capture.cleanup()

        log_info(f"{APP_NAME} 已停止")

    def _on_hotkey_triggered(self):
        """热键触发时显示翻译窗口"""
        log_debug("热键触发，显示翻译窗口")
        # 先隐藏划词翻译相关窗口
        self._popup_window.hide()
        self._translate_button.hide()
        self._last_text = ""

        # 显示翻译窗口
        translator_window = get_translator_window()
        translator_window.show_window()

    def _on_writing_hotkey_triggered(self):
        """写作热键触发时执行写作功能

        获取文本的方式：
        1. 优先使用 selection-hook 获取用户选中的文本（与划词翻译一致）
        2. 如果没有选中，则使用 ctrl+a + ctrl+c 获取全文
        """
        log_debug("写作热键触发")

        # 检查是否已在写作中
        if self._writing_service.is_writing:
            log_debug("写作正在进行中，跳过")
            return

        # 检查是否启用了翻译功能
        if not self._tray_icon._is_enabled:
            log_debug("翻译功能已禁用，跳过写作")
            return

        try:
            import keyboard

            # 释放热键相关的按键（Ctrl/Shift 可能仍处于按下状态）
            keyboard.release('ctrl')
            keyboard.release('shift')
            time.sleep(0.05)

            # 方式1：使用 selection-hook 获取选中文本
            # 检查最近 3 秒内是否有新的选择（用户选中后按热键，时间应该很近）
            current_time = time.time()
            selection_threshold = 3.0  # 3秒内认为是"当前选中"

            if self._text_capture.has_new_selection(current_time - selection_threshold):
                # 有最近的选中内容，直接使用
                selected_text = self._text_capture.capture_direct()
                if selected_text and selected_text.strip():
                    log_info(f"通过 selection-hook 获取选中文本: '{selected_text[:100]}...'")
                    self._start_writing(selected_text.strip(), has_selection=True)
                    return

            # 方式2：selection-hook 没有有效选中，尝试获取全文
            log_info("没有检测到最近的选中文本，尝试获取全文")
            self._get_all_text_for_writing_async()

        except Exception as e:
            log_error(f"写作热键处理失败: {e}")

    def _get_all_text_for_writing_async(self):
        """异步获取全文并开始写作"""
        try:
            import keyboard
            import pyperclip

            # 保存当前剪贴板内容
            saved_clipboard = ""
            try:
                saved_clipboard = pyperclip.paste()
            except Exception:
                pass

            # 再次确保按键状态正确
            keyboard.release('ctrl')
            keyboard.release('shift')
            time.sleep(0.05)

            # 全选并复制
            keyboard.press('ctrl')
            time.sleep(0.02)
            keyboard.press('a')
            time.sleep(0.02)
            keyboard.release('a')
            time.sleep(0.02)
            keyboard.release('ctrl')
            time.sleep(0.05)

            keyboard.press('ctrl')
            time.sleep(0.02)
            keyboard.press('c')
            time.sleep(0.02)
            keyboard.release('c')
            time.sleep(0.02)
            keyboard.release('ctrl')

            # 等待剪贴板更新
            QTimer.singleShot(200, lambda: self._process_full_text_for_writing(saved_clipboard))

        except Exception as e:
            log_error(f"获取全文失败: {e}")

    def _process_full_text_for_writing(self, saved_clipboard: str):
        """处理全文获取结果并开始写作"""
        try:
            import pyperclip
            import keyboard

            text = pyperclip.paste()
            log_info(f"全文内容: '{text[:100] if text else '(空)'}'")

            if text and text.strip():
                # 取消选中（按左箭头移动光标到开头）
                keyboard.release('ctrl')
                keyboard.release('shift')
                time.sleep(0.05)
                keyboard.press_and_release('left')

                # 延迟恢复剪贴板
                QTimer.singleShot(500, lambda: self._restore_clipboard(saved_clipboard))

                # 开始写作（全文模式）
                self._start_writing(text.strip(), has_selection=False)
            else:
                self._restore_clipboard(saved_clipboard)
                log_debug("没有可用的文本进行写作")

        except Exception as e:
            log_error(f"处理全文失败: {e}")
            self._restore_clipboard(saved_clipboard)

    def _restore_clipboard(self, saved_clipboard: str):
        """恢复剪贴板内容"""
        if saved_clipboard:
            try:
                import pyperclip
                pyperclip.copy(saved_clipboard)
                log_debug("剪贴板已恢复")
            except Exception:
                pass

    def _start_writing(self, text: str, has_selection: bool = True):
        """开始写作

        Args:
            text: 待写作的文本
            has_selection: 是否有选中文本（True=只替换选中，False=替换全部）
        """
        if not text or not text.strip():
            return

        log_info(f"开始写作 - 文本内容: '{text[:100]}...' (has_selection={has_selection})")

        # 获取保留原文设置
        keep_original = self._config.get('writing.keep_original', False)

        # 不显示 Toast 提示，避免获取焦点导致选中状态消失

        # 开始写作
        def on_complete(result: WritingResult):
            if result.error:
                ToastWidget.show_message("写作失败", result.error, "error")
            else:
                ToastWidget.show_message("写作完成", "文本已处理完成", "success")
                log_info(f"写作完成: {result.source_language} -> {result.target_language}")

        self._writing_service.start_writing(
            text,
            has_selection=has_selection,
            keep_original=keep_original,
            on_complete=on_complete
        )

    def _on_selection_finished(self):
        if not self._tray_icon._is_enabled:
            return

        text = capture_text_direct()

        if not text or not text.strip():
            self._translate_button.hide()
            return

        mouse_pos = self._selection_detector.get_last_position()

        if mouse_pos is None:
            from PyQt6.QtGui import QCursor
            cursor = QCursor.pos()
            mouse_pos = (cursor.x(), cursor.y())

        self._translate_button.set_selected_text(text.strip())

        # 获取来源程序名（用于判断是否是浏览器）
        try:
            from .core.text_capture import get_last_program_name
            program_name = get_last_program_name()
        except ImportError:
            from core.text_capture import get_last_program_name
            program_name = get_last_program_name()

        # 强制处理所有待处理事件，确保窗口显示
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        # 传递程序名，让按钮根据环境决定显示方式
        self._translate_button.show_at_position(mouse_pos, text.strip(), program_name)

        # 再次强制处理事件
        QApplication.processEvents()

    def _on_translate_button_clicked(self):
        if self._current_worker and self._current_worker.isRunning():
            return

        text = self._translate_button.get_selected_text()
        if not text or not text.strip():
            return

        if text == self._last_text and self._popup_window.isVisible():
            return

        self._last_text = text

        button_pos = self._translate_button.pos()
        mouse_pos = (button_pos.x() + 20, button_pos.y() + 20)

        # 使用流式翻译
        self._popup_window.show_at_mouse(mouse_pos)
        self._popup_window.show_streaming_start(text[:200])

        self._current_worker = StreamingTranslationWorker(text)
        self._current_worker.chunk_received.connect(self._on_translation_chunk)
        self._current_worker.translation_finished.connect(self._on_translation_finished)
        self._current_worker.translation_error.connect(self._on_translation_error)
        self._current_worker.start()

    def _on_translation_chunk(self, chunk: str):
        """收到翻译片段"""
        self._popup_window.append_translation_text(chunk)

    def _on_translation_finished(self, original_text: str, translated_text: str):
        """翻译完成"""
        self._popup_window.finish_streaming()
        self._current_worker = None

        # 保存翻译历史
        if translated_text:
            target_lang = self._config.get('target_language', '中文')
            add_translation_history(original_text, translated_text, target_lang, "selection")

    def _on_translation_error(self, original_text: str, error: str):
        """翻译错误"""
        result = TranslationResult(
            original_text=original_text,
            translated_text="",
            error=error
        )
        self._popup_window.show_result(result)
        self._current_worker = None

    def _on_enabled_changed(self, enabled: bool):
        self._selection_detector.set_enabled(enabled)

        if enabled:
            self._tray_icon.show_message(APP_NAME, "已启用", "info")
        else:
            self._tray_icon.show_message(APP_NAME, "已禁用", "info")
            self._translate_button.hide()
            self._popup_window.hide()

    def _on_popup_closed(self):
        self._last_text = ""

    def _on_settings_requested(self):
        dialog = SettingsDialog(self._popup_window)
        dialog.exec()

    def _on_translator_window_requested(self):
        """双击托盘显示翻译窗口"""
        # 先隐藏划词翻译相关窗口
        self._popup_window.hide()
        self._translate_button.hide()
        self._last_text = ""

        # 显示翻译窗口
        translator_window = get_translator_window()
        translator_window.show_window()

    def _on_history_requested(self):
        """显示翻译历史窗口"""
        # 先隐藏其他窗口
        self._popup_window.hide()
        self._translate_button.hide()
        self._last_text = ""

        # 显示历史窗口
        history_window = get_history_window()
        history_window.show_window()

    def _on_help_requested(self):
        """显示帮助窗口"""
        # 先隐藏其他窗口
        self._popup_window.hide()
        self._translate_button.hide()

        # 显示帮助窗口
        help_window = get_help_window()
        help_window.show()
        help_window.activateWindow()
        help_window.raise_()

    def _on_exit_requested(self):
        self.stop()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    # 设置应用图标（任务栏图标）
    icon_path = Path(__file__).parent.parent / "assets" / "icon.png"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    controller = MainController()
    controller.start()

    exit_code = app.exec()
    
    controller.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()