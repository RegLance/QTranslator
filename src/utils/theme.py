"""全局主题管理模块 - QTranslator"""
import os
import tempfile
from typing import Dict, Any


# 缓存对勾图片路径
_checkmark_path: str = None


def _ensure_checkmark_image() -> str:
    """生成白色对勾 PNG 图片并返回路径（仅生成一次）"""
    global _checkmark_path
    if _checkmark_path and os.path.exists(_checkmark_path):
        return _checkmark_path

    from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
    from PyQt6.QtCore import Qt

    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(
        QColor(255, 255, 255), 2.0,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin
    ))
    painter.drawLine(3, 8, 6, 12)
    painter.drawLine(6, 12, 13, 4)
    painter.end()

    _checkmark_path = os.path.join(tempfile.gettempdir(), 'qtranslator_checkmark.png')
    pixmap.save(_checkmark_path)
    return _checkmark_path

# 主题样式定义
THEMES = {
    'dark': {
        # 基础颜色
        'bg_color': '#2d2d2d',
        'bg_secondary': '#252525',
        'border_color': '#3d3d3d',
        'shadow_color': (0, 0, 0, 100),

        # 文本颜色
        'text_primary': '#ffffff',
        'text_secondary': '#b0b0b0',
        'text_muted': '#888888',
        'text_placeholder': '#666666',

        # 强调色
        'accent_color': '#007AFF',     # macOS 风格现代蓝
        'accent_hover': '#0A84FF',     # iOS 风格亮蓝
        'success_color': '#1a7f37',
        'warning_color': '#d29922',
        'error_color': '#ff6b6b',

        # 交互元素
        'button_bg': '#3d3d3d',
        'button_hover': '#4d4d4d',
        'button_active': '#5d5d5d',
        'input_bg': '#252525',
        'input_border': '#3d3d3d',
        'input_focus': '#007AFF',

        # 滚动条
        'scrollbar_bg': '#2d2d2d',
        'scrollbar_handle': '#5d5d5d',
        'scrollbar_hover': '#6d6d6d',

        # 分隔器
        'splitter_color': '#3d3d3d',
        'splitter_hover': '#5d5d5d',

        # 原文/译文
        'original_bg': '#252525',
        'original_text': '#aaaaaa',
        'result_text': '#ffffff',

        # 列表项
        'list_item_bg': '#252525',
        'list_item_hover': '#3d3d3d',
        'list_item_selected': '#007AFF',

        # 分组框
        'group_title': '#007AFF',

        # 关闭按钮悬停
        'close_hover': '#ff6b6b',
    },
    'light': {
        # 基础颜色
        'bg_color': '#f5f5f5',
        'bg_secondary': '#ffffff',
        'border_color': '#e0e0e0',
        'shadow_color': (0, 0, 0, 50),

        # 文本颜色
        'text_primary': '#333333',
        'text_secondary': '#666666',
        'text_muted': '#888888',
        'text_placeholder': '#aaaaaa',

        # 强调色
        'accent_color': '#007AFF',     # macOS 风格现代蓝
        'accent_hover': '#0A84FF',     # iOS 风格亮蓝
        'success_color': '#1a7f37',
        'warning_color': '#d29922',
        'error_color': '#d32f2f',

        # 交互元素
        'button_bg': '#e0e0e0',
        'button_hover': '#d0d0d0',
        'button_active': '#c0c0c0',
        'input_bg': '#ffffff',
        'input_border': '#e0e0e0',
        'input_focus': '#007AFF',

        # 滚动条
        'scrollbar_bg': '#f0f0f0',
        'scrollbar_handle': '#c0c0c0',
        'scrollbar_hover': '#a0a0a0',

        # 分隔器
        'splitter_color': '#e0e0e0',
        'splitter_hover': '#d0d0d0',

        # 原文/译文
        'original_bg': '#ebebeb',
        'original_text': '#555555',
        'result_text': '#333333',

        # 列表项
        'list_item_bg': '#ffffff',
        'list_item_hover': '#e8e8e8',
        'list_item_selected': '#007AFF',

        # 分组框
        'group_title': '#007AFF',

        # 关闭按钮悬停
        'close_hover': '#ff6b6b',
    }
}


def get_theme(theme_name: str = None) -> Dict[str, Any]:
    """获取主题配置

    Args:
        theme_name: 主题名称 ('dark' 或 'light')，如果为 None 则从配置读取

    Returns:
        主题字典
    """
    if theme_name is None:
        try:
            from ..config import get_config
            theme_name = get_config().get('theme.popup_style', 'dark')
        except ImportError:
            from src.config import get_config
            theme_name = get_config().get('theme.popup_style', 'dark')

    return THEMES.get(theme_name, THEMES['dark'])


def get_theme_name() -> str:
    """获取当前主题名称"""
    try:
        from ..config import get_config
        return get_config().get('theme.popup_style', 'dark')
    except ImportError:
        from src.config import get_config
        return get_config().get('theme.popup_style', 'dark')


def is_dark_theme() -> bool:
    """判断是否为深色主题"""
    return get_theme_name() == 'dark'


# 常用样式模板
def get_scrollbar_style(theme: Dict[str, Any]) -> str:
    """获取滚动条样式"""
    return f"""
        QScrollBar:vertical {{
            background-color: {theme['scrollbar_bg']};
            width: 8px;
            border-radius: 4px;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {theme['scrollbar_handle']};
            border-radius: 4px;
            min-height: 20px;
            border: none;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {theme['scrollbar_hover']};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background-color: transparent;
            border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background-color: transparent;
            border: none;
        }}
        QScrollBar:horizontal {{
            background-color: {theme['scrollbar_bg']};
            height: 8px;
            border-radius: 4px;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {theme['scrollbar_handle']};
            border-radius: 4px;
            min-width: 20px;
            border: none;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {theme['scrollbar_hover']};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
            background-color: transparent;
            border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background-color: transparent;
            border: none;
        }}
    """


def get_splitter_style(theme: Dict[str, Any]) -> str:
    """获取分隔器样式"""
    return f"""
        QSplitter::handle {{
            background-color: {theme['splitter_color']};
            height: 6px;
            margin: 2px 0px;
            border-radius: 3px;
        }}
        QSplitter::handle:hover {{
            background-color: {theme['splitter_hover']};
        }}
        QSplitter::handle:pressed {{
            background-color: {theme['button_active']};
        }}
    """


def get_list_style(theme: Dict[str, Any]) -> str:
    """获取列表样式"""
    return f"""
        QListWidget {{
            background-color: {theme['list_item_bg']};
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
            background-color: {theme['list_item_selected']};
            color: #ffffff;
        }}
        QListWidget::item:hover {{
            background-color: {theme['list_item_hover']};
        }}
        {get_scrollbar_style(theme)}
    """


def get_menu_style(theme: Dict[str, Any]) -> str:
    """获取菜单样式"""
    return f"""
        QMenu {{
            background-color: {theme['bg_color']};
            border: 1px solid {theme['border_color']};
            border-radius: 8px;
            padding: 8px 4px;
        }}
        QMenu::item {{
            color: {theme['text_primary']};
            padding: 8px 24px 8px 8px;
            font-size: 13px;
            border-radius: 6px;
            margin: 2px 4px;
        }}
        QMenu::item:selected {{
            background-color: {theme['accent_color']};
            color: #ffffff;
            border-radius: 6px;
        }}
        QMenu::item:disabled {{
            color: {theme['text_muted']};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {theme['border_color']};
            margin: 6px 12px;
        }}
        QMenu::icon {{
            padding-left: 8px;
        }}
    """


def get_combobox_style(theme: Dict[str, Any]) -> str:
    """获取下拉框样式"""
    return f"""
        QComboBox {{
            background-color: {theme['input_bg']};
            color: {theme['text_primary']};
            border: 1px solid {theme['input_border']};
            border-radius: 4px;
            padding: 6px 10px;
            font-size: 13px;
        }}
        QComboBox:hover {{
            border-color: {theme['accent_color']};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {theme['bg_color']};
            color: {theme['text_primary']};
            selection-background-color: {theme['accent_color']};
            selection-color: #ffffff;
            border: 1px solid {theme['border_color']};
            border-radius: 4px;
            padding: 2px;
        }}
    """


def get_lineedit_style(theme: Dict[str, Any]) -> str:
    """获取输入框样式"""
    return f"""
        QLineEdit {{
            background-color: {theme['input_bg']};
            border: 1px solid {theme['input_border']};
            border-radius: 4px;
            padding: 6px 10px;
            color: {theme['text_primary']};
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border-color: {theme['input_focus']};
        }}
    """


def get_checkbox_style(theme: Dict[str, Any]) -> str:
    """获取复选框样式 - 直接样式化原生指示器"""
    checkmark_url = _ensure_checkmark_image().replace('\\', '/')
    return f"""
        QCheckBox {{
            color: {theme['text_primary']};
            font-size: 13px;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1.5px solid {theme['scrollbar_handle']};
            background-color: {theme['input_bg']};
        }}
        QCheckBox::indicator:hover {{
            border-color: {theme['accent_color']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {theme['accent_color']};
            border-color: {theme['accent_color']};
            image: url({checkmark_url});
        }}
    """


def get_spinbox_style(theme: Dict[str, Any]) -> str:
    """获取数字输入框(SpinBox)样式 - 按钮部分样式"""
    return f"""
        QSpinBox {{
            background-color: {theme['input_bg']};
            border: 1px solid {theme['input_border']};
            border-radius: 6px;
            padding: 4px 8px;
            padding-right: 32px;
            color: {theme['text_primary']};
            font-size: 13px;
        }}
        QSpinBox:focus {{
            border-color: {theme['accent_color']};
        }}
        QSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: right top;
            width: 24px;
            height: 14px;
            border: none;
            border-top-right-radius: 5px;
            border-left: 1px solid {theme['input_border']};
            background-color: transparent;
        }}
        QSpinBox::up-button:hover {{
            background-color: {theme['button_hover']};
        }}
        QSpinBox::up-button:pressed {{
            background-color: {theme['accent_color']};
        }}
        QSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: right bottom;
            width: 24px;
            height: 14px;
            border: none;
            border-bottom-right-radius: 5px;
            border-left: 1px solid {theme['input_border']};
            background-color: transparent;
        }}
        QSpinBox::down-button:hover {{
            background-color: {theme['button_hover']};
        }}
        QSpinBox::down-button:pressed {{
            background-color: {theme['accent_color']};
        }}
    """


def get_hidden_scrollbar_style(theme: Dict[str, Any]) -> str:
    """获取隐藏滚动条的样式（用于流式输出时）"""
    return f"""
        QScrollBar:vertical {{
            background-color: transparent;
            width: 0px;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background-color: transparent;
            border: none;
            min-height: 0px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background-color: transparent;
            border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background-color: transparent;
            border: none;
        }}
        QScrollBar:horizontal {{
            background-color: transparent;
            height: 0px;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: transparent;
            border: none;
            min-width: 0px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
            background-color: transparent;
            border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background-color: transparent;
            border: none;
        }}
    """