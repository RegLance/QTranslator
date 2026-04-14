"""全局主题管理模块 - QTranslator"""
import colorsys
from collections import OrderedDict
from typing import Dict, Any


# ---------------------------------------------------------------------------
# 颜色工具函数
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple:
    """#RRGGBB -> (r, g, b) 归一化到 0.0-1.0"""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    """(r, g, b) 0.0-1.0 -> #rrggbb"""
    return '#{:02x}{:02x}{:02x}'.format(
        max(0, min(255, int(round(r * 255)))),
        max(0, min(255, int(round(g * 255)))),
        max(0, min(255, int(round(b * 255)))),
    )


def _lighten(hex_color: str, amount: float) -> str:
    """在 HLS 空间增加亮度（amount: 0.0~1.0 的增量）"""
    r, g, b = _hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = min(1.0, l + amount)
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex(r2, g2, b2)


def _darken(hex_color: str, amount: float) -> str:
    """在 HLS 空间降低亮度（amount: 0.0~1.0 的减量）"""
    r, g, b = _hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, l - amount)
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex(r2, g2, b2)


def _luminance(hex_color: str) -> float:
    """计算 WCAG 相对亮度 (0.0 = 黑, 1.0 = 白)"""
    r, g, b = _hex_to_rgb(hex_color)

    def _linearize(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


# ---------------------------------------------------------------------------
# 主题派生函数
# ---------------------------------------------------------------------------

def derive_theme(accent_color: str, bg_color: str) -> Dict[str, Any]:
    """根据强调色和背景色自动派生完整主题字典。

    通过 bg_color 的亮度自动判断深色/浅色变体，然后生成所有 ~30 个颜色键。
    """
    is_dark = _luminance(bg_color) < 0.5

    if is_dark:
        return {
            # 基础颜色
            'bg_color': bg_color,
            'bg_secondary': _darken(bg_color, 0.05),
            'border_color': _lighten(bg_color, 0.08),
            'shadow_color': (0, 0, 0, 100),
            # 文本颜色
            'text_primary': '#ffffff',
            'text_secondary': '#b0b0b0',
            'text_muted': '#888888',
            'text_placeholder': '#666666',
            # 强调色
            'accent_color': accent_color,
            'accent_hover': _lighten(accent_color, 0.10),
            'success_color': '#1a7f37',
            'warning_color': '#d29922',
            'error_color': '#ff6b6b',
            # 交互元素
            'button_bg': _lighten(bg_color, 0.08),
            'button_hover': _lighten(bg_color, 0.15),
            'button_active': _lighten(bg_color, 0.22),
            'input_bg': _darken(bg_color, 0.05),
            'input_border': _lighten(bg_color, 0.08),
            'input_focus': accent_color,
            # 滚动条
            'scrollbar_bg': bg_color,
            'scrollbar_handle': _lighten(bg_color, 0.22),
            'scrollbar_hover': _lighten(bg_color, 0.30),
            # 分隔器
            'splitter_color': _lighten(bg_color, 0.08),
            'splitter_hover': _lighten(bg_color, 0.22),
            # 原文/译文
            'original_bg': _darken(bg_color, 0.05),
            'original_text': '#aaaaaa',
            'result_text': '#ffffff',
            # 列表项
            'list_item_bg': _darken(bg_color, 0.05),
            'list_item_hover': _lighten(bg_color, 0.08),
            'list_item_selected': accent_color,
            # 分组框
            'group_title': accent_color,
            # 关闭按钮悬停
            'close_hover': '#ff6b6b',
        }
    else:
        return {
            # 基础颜色
            'bg_color': bg_color,
            'bg_secondary': _lighten(bg_color, 0.03),
            'border_color': _darken(bg_color, 0.10),
            'shadow_color': (0, 0, 0, 50),
            # 文本颜色
            'text_primary': '#333333',
            'text_secondary': '#666666',
            'text_muted': '#888888',
            'text_placeholder': '#aaaaaa',
            # 强调色
            'accent_color': accent_color,
            'accent_hover': _lighten(accent_color, 0.10),
            'success_color': '#1a7f37',
            'warning_color': '#d29922',
            'error_color': '#d32f2f',
            # 交互元素
            'button_bg': _darken(bg_color, 0.08),
            'button_hover': _darken(bg_color, 0.14),
            'button_active': _darken(bg_color, 0.20),
            'input_bg': _lighten(bg_color, 0.03),
            'input_border': _darken(bg_color, 0.10),
            'input_focus': accent_color,
            # 滚动条
            'scrollbar_bg': _darken(bg_color, 0.03),
            'scrollbar_handle': _darken(bg_color, 0.20),
            'scrollbar_hover': _darken(bg_color, 0.30),
            # 分隔器
            'splitter_color': _darken(bg_color, 0.10),
            'splitter_hover': _darken(bg_color, 0.14),
            # 原文/译文
            'original_bg': _darken(bg_color, 0.04),
            'original_text': '#555555',
            'result_text': '#333333',
            # 列表项
            'list_item_bg': _lighten(bg_color, 0.03),
            'list_item_hover': _darken(bg_color, 0.06),
            'list_item_selected': accent_color,
            # 分组框
            'group_title': accent_color,
            # 关闭按钮悬停
            'close_hover': '#ff6b6b',
        }


# ---------------------------------------------------------------------------
# 主题样式定义（保留原有手工调优的深色/浅色主题）
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# 预置主题注册 (display_name, accent_color, bg_color)
# ---------------------------------------------------------------------------

_THEME_PRESETS = {
    'ocean_blue':   ('海洋蓝',   '#0078D4', '#1b2838'),
    'forest_green': ('森林绿',   '#2ea043', '#1a2b1a'),
    'royal_purple': ('皇家紫',   '#8b5cf6', '#1e1b2e'),
    'warm_orange':  ('暖橙',     '#f97316', '#2a1f14'),
    'rose_pink':    ('玫瑰粉',   '#e11d48', '#2a1520'),
    'mint_light':   ('薄荷浅色', '#10b981', '#f0fdf4'),
}

for _key, (_, _accent, _bg) in _THEME_PRESETS.items():
    THEMES[_key] = derive_theme(_accent, _bg)

# 主题显示名称映射（有序，用于设置界面）
THEME_DISPLAY_NAMES = OrderedDict([
    ('dark',         '深色'),
    ('light',        '浅色'),
    ('ocean_blue',   '海洋蓝'),
    ('forest_green', '森林绿'),
    ('royal_purple', '皇家紫'),
    ('warm_orange',  '暖橙'),
    ('rose_pink',    '玫瑰粉'),
    ('mint_light',   '薄荷浅色'),
    ('custom',       '自定义'),
])


# ---------------------------------------------------------------------------
# 配置读取辅助
# ---------------------------------------------------------------------------

def _get_config():
    """获取全局配置实例"""
    try:
        from ..config import get_config
        return get_config()
    except ImportError:
        from src.config import get_config
        return get_config()


def get_theme(theme_name: str = None) -> Dict[str, Any]:
    """获取主题配置

    Args:
        theme_name: 主题名称，如果为 None 则从配置读取。
                    支持所有预置主题名 + 'custom'（自定义主题）。

    Returns:
        主题字典
    """
    if theme_name is None:
        theme_name = _get_config().get('theme.popup_style', 'dark')

    if theme_name in THEMES:
        return THEMES[theme_name]
    elif theme_name == 'custom':
        config = _get_config()
        accent = config.get('theme.custom_accent', '#007AFF')
        bg = config.get('theme.custom_bg', '#2d2d2d')
        return derive_theme(accent, bg)
    else:
        return THEMES['dark']


def get_theme_name() -> str:
    """获取当前主题名称"""
    return _get_config().get('theme.popup_style', 'dark')


def is_dark_theme() -> bool:
    """判断是否为深色主题（基于当前主题背景色亮度）"""
    theme = get_theme()
    return _luminance(theme['bg_color']) < 0.5


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
            margin: 0px;
            padding: 0px;
            border: none;
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