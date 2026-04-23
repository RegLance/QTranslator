"""系统托盘模块 - QTranslator"""
import sys
import os
import traceback
import base64
from typing import Optional
from pathlib import Path
from io import BytesIO
from datetime import datetime

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QFont, QPen, QImage
from PyQt6.QtCore import pyqtSignal, QObject, Qt, QBuffer, QTimer

try:
    from ..config import get_config, APP_NAME
    from ..utils.theme import get_theme, get_menu_style
except ImportError:
    from src.config import get_config, APP_NAME
    from src.utils.theme import get_theme, get_menu_style


class TrayIcon(QObject):
    """系统托盘图标管理"""

    # 信号
    enabled_changed = pyqtSignal(bool)
    settings_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    translator_window_requested = pyqtSignal()  # 双击显示翻译窗口
    history_requested = pyqtSignal()  # 显示历史窗口
    help_requested = pyqtSignal()  # 显示帮助窗口

    def __init__(self):
        super().__init__()

        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._is_enabled = True
        self._theme_style = get_config().get('theme.popup_style', 'dark')

        self._create_icon()
        self._create_menu()
        self._create_tray()

        # 连接主题变更信号
        try:
            from ..utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self.update_theme)

    def _create_icon(self):
        """创建托盘图标"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"

        if icon_path.exists():
            self._icon = QIcon(str(icon_path))
        else:
            self._icon = self._create_default_icon()

    def _create_default_icon(self) -> QIcon:
        """创建默认图标 - "Q" 字符（24px）"""
        pixmap = QPixmap(24, 24)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制圆形背景（半透明蓝色）
        painter.setBrush(QColor(0, 122, 255, 180))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 24, 24)

        # 绘制 Q 字符
        painter.setPen(QColor(255, 255, 255, 230))
        font = QFont("Arial", 14, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")

        painter.end()

        return QIcon(pixmap)

    def _create_check_icon(self) -> QIcon:
        """创建勾选图标（使用主题强调色）"""
        theme = get_theme(self._theme_style)
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制圆角背景（使用主题强调色）
        painter.setBrush(QColor(theme['accent_color']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 16, 16, 3, 3)

        # 绘制白色勾选符号 ✓
        painter.setPen(QPen(QColor(255, 255, 255), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(3, 8, 6, 12)  # 左下到中下
        painter.drawLine(6, 12, 13, 4)  # 中下到右上

        painter.end()

        return QIcon(pixmap)

    def _create_uncheck_icon(self) -> QIcon:
        """创建未勾选图标（使用主题输入背景色和边框色）"""
        theme = get_theme(self._theme_style)
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制边框（使用主题输入背景色和边框色）
        painter.setBrush(QColor(theme['input_bg']))
        painter.setPen(QPen(QColor(theme['scrollbar_handle']), 1))
        painter.drawRoundedRect(0, 0, 16, 16, 3, 3)

        painter.end()

        return QIcon(pixmap)

    def _create_menu(self):
        """创建右键菜单"""
        self._menu = QMenu()

        # 设置窗口属性以支持圆角（Windows需要）
        # 仅保留 WA_TranslucentBackground，去掉 FramelessWindowHint 和 NoDropShadowWindowHint：
        # - QMenu 本身就是弹出式无边框窗口，不需要 FramelessWindowHint
        # - FramelessWindowHint 会让 DWM 将窗口视为"非矩形窗口"，增加合成开销
        # - NoDropShadowWindowHint 阻止系统原生阴影，DWM 需要额外处理
        self._menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 创建勾选图标
        self._check_icon = self._create_check_icon()
        self._uncheck_icon = self._create_uncheck_icon()

        # 应用主题样式
        self._apply_menu_style()

        # 启用/禁用选项
        self._enable_action = QAction("启用划词", self._menu)
        self._enable_action.setCheckable(True)
        self._enable_action.setChecked(True)
        self._enable_action.setIcon(self._check_icon)  # 设置勾选图标
        self._enable_action.triggered.connect(self._on_enable_toggle)
        self._menu.addAction(self._enable_action)

        # 菜单显示前更新图标状态
        self._menu.aboutToShow.connect(self._update_action_icon)

        self._menu.addSeparator()

        # 翻译窗口选项
        self._translator_action = QAction("翻译窗口", self._menu)
        self._translator_action.triggered.connect(self._on_translator_window)
        self._menu.addAction(self._translator_action)

        # 历史记录选项
        self._history_action = QAction("翻译历史", self._menu)
        self._history_action.triggered.connect(self._on_history)
        self._menu.addAction(self._history_action)

        # 设置选项
        self._settings_action = QAction("设置...", self._menu)
        self._settings_action.triggered.connect(self._on_settings)
        self._menu.addAction(self._settings_action)

        # 帮助选项
        self._help_action = QAction("帮助...", self._menu)
        self._help_action.triggered.connect(self._on_help)
        self._menu.addAction(self._help_action)

        self._menu.addSeparator()

        # 退出选项
        self._exit_action = QAction("退出", self._menu)
        self._exit_action.triggered.connect(self._on_exit)
        self._menu.addAction(self._exit_action)

    def _apply_menu_style(self):
        """应用菜单样式"""
        theme = get_theme(self._theme_style)
        self._menu.setStyleSheet(get_menu_style(theme))

    def update_theme(self):
        """更新主题"""
        new_theme = get_config().get('theme.popup_style', 'dark')
        # 即使主题名称未变，自定义主题的颜色也可能改变，因此始终更新
        self._theme_style = new_theme
        self._apply_menu_style()
        # 更新勾选图标
        self._check_icon = self._create_check_icon()
        self._uncheck_icon = self._create_uncheck_icon()
        # 更新当前 action 显示的图标
        self._update_action_icon()

    def _create_tray(self):
        """创建托盘图标"""
        self._tray = QSystemTrayIcon(self._icon)
        self._tray.setToolTip(f"{APP_NAME}")

        # 使用 setContextMenu 让系统原生处理右键菜单，避免手动 exec 导致的卡顿
        self._tray.setContextMenu(self._menu)

        # 连接信号
        self._tray.activated.connect(self._on_tray_activated)

    def show(self):
        """显示托盘图标"""
        if self._tray:
            self._tray.show()
            self._tray.showMessage(
                APP_NAME,
                "已启动，选中文本后点击图标即可翻译",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )

    def hide(self):
        """隐藏托盘图标"""
        if self._tray:
            self._tray.hide()

    def set_enabled(self, enabled: bool):
        """设置启用状态"""
        self._is_enabled = enabled
        self._enable_action.setChecked(enabled)

        if enabled:
            self._tray.setToolTip(f"{APP_NAME} - 已启用")
            self._tray.setIcon(self._create_enabled_icon())
        else:
            self._tray.setToolTip(f"{APP_NAME} - 已禁用")
            self._tray.setIcon(self._create_disabled_icon())

        self.enabled_changed.emit(enabled)

    def _create_enabled_icon(self) -> QIcon:
        """创建启用状态图标 - 加载 icon.png"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # 缩放到托盘图标合适大小
                scaled = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                return QIcon(scaled)
        
        # 如果加载失败，绘制备用图标
        return self._create_default_icon()

    def _create_disabled_icon(self) -> QIcon:
        """创建禁用状态图标 - 加载 icon.png 并转换为灰色"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                # 缩放到托盘图标合适大小
                scaled = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                # 转换为灰色
                gray_pixmap = self._convert_to_grayscale(scaled)
                return QIcon(gray_pixmap)
        
        # 如果加载失败，绘制备用灰色图标
        return self._create_default_disabled_icon()

    def _convert_to_grayscale(self, pixmap: QPixmap) -> QPixmap:
        """将 pixmap 转换为灰色

        直接操作内存而非逐像素调用 pixelColor/setPixelColor，
        避免 Python → C++ 跨语言调用开销（64×64 图标从 ~30ms 降到 <1ms）。
        """
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)

        bits = image.bits()
        bits.setsize(image.sizeInBytes())
        data = bytearray(bits)

        # ARGB32 内存布局（小端）：每 4 字节 [B, G, R, A]
        for i in range(0, len(data), 4):
            b, g, r, a = data[i], data[i + 1], data[i + 2], data[i + 3]
            gray = int(r * 0.3 + g * 0.59 + b * 0.11)
            data[i] = gray      # B
            data[i + 1] = gray  # G
            data[i + 2] = gray  # R
            data[i + 3] = a     # A 不变

        result = QImage(data, image.width(), image.height(),
                        image.bytesPerLine(), QImage.Format.Format_ARGB32)
        return QPixmap.fromImage(result.copy())

    def _create_default_disabled_icon(self) -> QIcon:
        """创建备用灰色图标"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(100, 100, 100))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        painter.setPen(QColor(180, 180, 180))
        font = QFont("Arial", 32, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")
        painter.end()

        return QIcon(pixmap)

    def _update_action_icon(self):
        """更新菜单项图标状态"""
        if self._enable_action.isChecked():
            self._enable_action.setIcon(self._check_icon)
        else:
            self._enable_action.setIcon(self._uncheck_icon)

    def _on_enable_toggle(self):
        """启用/禁用切换"""
        try:
            self.set_enabled(self._enable_action.isChecked())
            self._update_action_icon()  # 立即更新图标
        except Exception as e:
            self._log_error("_on_enable_toggle", e)

    def _on_settings(self):
        """打开设置"""
        try:
            self.settings_requested.emit()
        except Exception as e:
            self._log_error("_on_settings", e)

    def _on_translator_window(self):
        """打开翻译窗口"""
        try:
            self.translator_window_requested.emit()
        except Exception as e:
            self._log_error("_on_translator_window", e)

    def _on_history(self):
        """打开历史窗口"""
        try:
            self.history_requested.emit()
        except Exception as e:
            self._log_error("_on_history", e)

    def _on_help(self):
        """打开帮助窗口"""
        try:
            self.help_requested.emit()
        except Exception as e:
            self._log_error("_on_help", e)

    def _on_exit(self):
        """退出应用"""
        try:
            self.exit_requested.emit()
        except Exception as e:
            self._log_error("_on_exit", e)

    def _on_tray_activated(self, reason):
        """托盘图标激活事件"""
        try:
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                # 双击：显示翻译窗口
                self.translator_window_requested.emit()
            # 右键菜单已通过 setContextMenu 由系统原生处理，无需手动 exec
        except Exception as e:
            self._log_error("_on_tray_activated", e)

    def _log_error(self, method_name: str, exc: Exception):
        """安全地记录错误"""
        try:
            error_msg = f"TrayIcon.{method_name} 错误: {exc}\n{traceback.format_exc()}"
            print(error_msg, file=sys.stderr)
            # 尝试写入崩溃日志
            from datetime import datetime
            try:
                from src.config import get_config
                crash_path = get_config().app_dir / "crash.log"
            except Exception:
                if sys.platform == 'win32':
                    base_dir = Path(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')))
                else:
                    base_dir = Path.home()
                crash_path = base_dir / "QTranslator" / "crash.log"
                crash_path.parent.mkdir(parents=True, exist_ok=True)

            with open(crash_path, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n[{timestamp}] {error_msg}\n")
        except Exception:
            pass  # 避免日志写入失败导致程序崩溃

    def show_message(self, title: str, message: str, icon_type: str = "info"):
        """显示托盘消息"""
        if not self._tray:
            return

        icon = QSystemTrayIcon.MessageIcon.Information
        if icon_type == "warning":
            icon = QSystemTrayIcon.MessageIcon.Warning
        elif icon_type == "error":
            icon = QSystemTrayIcon.MessageIcon.Critical

        self._tray.showMessage(title, message, icon, 3000)

    def cleanup(self):
        """清理资源"""
        if self._tray:
            self._tray.hide()
            self._tray = None


# 全局托盘实例
_tray_instance: Optional[TrayIcon] = None


def get_tray_icon() -> TrayIcon:
    """获取全局托盘实例"""
    global _tray_instance
    if _tray_instance is None:
        _tray_instance = TrayIcon()
    return _tray_instance