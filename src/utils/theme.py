"""全局主题管理模块 - QTranslator"""
from typing import Dict, Any

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
        'accent_color': '#0078d4',
        'accent_hover': '#1084d8',
        'success_color': '#1a7f37',
        'warning_color': '#d29922',
        'error_color': '#ff6b6b',

        # 交互元素
        'button_bg': '#3d3d3d',
        'button_hover': '#4d4d4d',
        'button_active': '#5d5d5d',
        'input_bg': '#252525',
        'input_border': '#3d3d3d',
        'input_focus': '#0078d4',

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
        'list_item_selected': '#0078d4',

        # 分组框
        'group_title': '#0078d4',

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
        'accent_color': '#0078d4',
        'accent_hover': '#1084d8',
        'success_color': '#1a7f37',
        'warning_color': '#d29922',
        'error_color': '#d32f2f',

        # 交互元素
        'button_bg': '#e0e0e0',
        'button_hover': '#d0d0d0',
        'button_active': '#c0c0c0',
        'input_bg': '#ffffff',
        'input_border': '#e0e0e0',
        'input_focus': '#0078d4',

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
        'list_item_selected': '#0078d4',

        # 分组框
        'group_title': '#0078d4',

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
    """获取复选框样式 - 使用图标而非默认指示器"""
    return f"""
        QCheckBox {{
            color: {theme['text_primary']};
            font-size: 13px;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 0px;
            height: 0px;
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