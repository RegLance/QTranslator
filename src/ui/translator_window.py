"""独立翻译窗口模块 - QTranslator（无边框风格，支持主题切换、纯文本显示）"""
import sys
import math
import webbrowser
from datetime import datetime
from typing import Optional
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QComboBox, QFrame,
    QGraphicsDropShadowEffect, QApplication, QSplitter, QSplitterHandle
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QRectF, QPointF, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QColor, QCursor, QMouseEvent, QKeySequence, QIcon, QFont, QPixmap, QPainter, QPen, QBrush, QLinearGradient

try:
    from ..utils.theme import (
        get_theme,
        get_scrollbar_style,
        get_splitter_style,
        get_menu_style,
        get_combobox_style,
        get_hidden_scrollbar_style,
        _luminance,
        polish_diff_highlight_colors,
    )
    from ..config import get_config, APP_VERSION, VERSION_AUTHOR
    from ..utils.tts import get_tts
except ImportError:
    from src.utils.theme import (
        get_theme,
        get_scrollbar_style,
        get_splitter_style,
        get_menu_style,
        get_combobox_style,
        get_hidden_scrollbar_style,
        _luminance,
        polish_diff_highlight_colors,
    )
    from src.config import get_config, APP_VERSION, VERSION_AUTHOR
    from src.utils.tts import get_tts


class AnimatedSplitterHandle(QSplitterHandle):
    """带动画效果的分隔线手柄

    当操作进行时显示从左到右流动的渐变效果，作为视觉提示。
    """

    def __init__(self, orientation: Qt.Orientation, splitter: QSplitter):
        super().__init__(orientation, splitter)
        self._animation_active = False
        self._animation_phase = 0.0  # 流动进度 (0.0 - 1.0)
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._update_animation)
        self._animation_timer.setInterval(16)  # 16ms ≈ 60fps

        # 主题颜色缓存
        self._base_color = QColor('#3d3d3d')
        self._ripple_color = QColor('#5a5a5a')  # 灰色波纹

        # 流动参数 - 更慢的速度
        self._flow_speed = 0.006  # 约2.5秒完成一个周期

        # 开启鼠标追踪
        self.setMouseTracking(True)

    def set_theme_colors(self, base_color: QColor, accent_color: QColor):
        """设置主题颜色"""
        self._base_color = base_color
        # 波纹颜色：比基础色亮一点的灰色
        if base_color.lightness() < 128:  # 深色主题
            self._ripple_color = QColor(
                min(255, base_color.red() + 45),
                min(255, base_color.green() + 45),
                min(255, base_color.blue() + 45)
            )
        else:  # 浅色主题
            self._ripple_color = QColor(
                max(0, base_color.red() - 45),
                max(0, base_color.green() - 45),
                max(0, base_color.blue() - 45)
            )
        self.update()

    def start_animation(self):
        """启动动画"""
        if not self._animation_active:
            self._animation_active = True
            self._animation_phase = 0.0
            self._animation_timer.start()

    def stop_animation(self):
        """停止动画"""
        if self._animation_active:
            self._animation_active = False
            self._animation_timer.stop()
            self._animation_phase = 0.0
            self.update()

    def is_animating(self) -> bool:
        """检查是否正在动画"""
        return self._animation_active

    def _update_animation(self):
        """更新动画帧"""
        self._animation_phase += self._flow_speed
        if self._animation_phase > 1.0:
            self._animation_phase = 0.0
        self.update()

    def paintEvent(self, event):
        """绘制分隔线（带从左到右流动渐变效果）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        handle_height = 6
        y_offset = (rect.height() - handle_height) // 2
        draw_rect = QRect(rect.x() + 2, y_offset, rect.width() - 4, handle_height)

        # 绘制基础分隔线背景
        painter.setBrush(QBrush(self._base_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(draw_rect, 3, 3)

        # 如果动画激活，绘制从左到右流动的渐变光带
        if self._animation_active:
            width = draw_rect.width()
            
            # 流动渐变光带的宽度（约占分隔线宽度的40%）
            band_width = int(width * 0.4)
            
            # 计算光带的起始位置（从左到右流动）
            # phase 从 0 到 1，光带从左边移动到右边
            start_x = draw_rect.x() + int((width + band_width) * self._animation_phase) - band_width
            
            # 创建渐变：左边缘暗 -> 中间亮 -> 右边缘暗
            gradient = QLinearGradient()
            
            # 计算渐变的绝对坐标
            gradient_start = start_x
            gradient_end = start_x + band_width
            
            gradient.setStart(gradient_start, 0)
            gradient.setFinalStop(gradient_end, 0)
            
            # 渐变颜色：边缘透明，中间明亮
            gradient.setColorAt(0.0, QColor(self._ripple_color.red(),
                                            self._ripple_color.green(),
                                            self._ripple_color.blue(), 0))
            gradient.setColorAt(0.15, QColor(self._ripple_color.red(),
                                            self._ripple_color.green(),
                                            self._ripple_color.blue(), 50))
            gradient.setColorAt(0.5, QColor(self._ripple_color.red(),
                                            self._ripple_color.green(),
                                            self._ripple_color.blue(), 200))  # 中间最亮
            gradient.setColorAt(0.85, QColor(self._ripple_color.red(),
                                            self._ripple_color.green(),
                                            self._ripple_color.blue(), 50))
            gradient.setColorAt(1.0, QColor(self._ripple_color.red(),
                                            self._ripple_color.green(),
                                            self._ripple_color.blue(), 0))
            
            # 计算绘制区域（限制在分隔线范围内）
            draw_start = max(draw_rect.x(), start_x)
            draw_end = min(draw_rect.x() + width, start_x + band_width)
            band_draw_width = draw_end - draw_start
            
            if band_draw_width > 0:
                # 调整渐变范围以匹配实际绘制区域
                actual_gradient = QLinearGradient()
                actual_gradient.setStart(draw_start, 0)
                actual_gradient.setFinalStop(draw_end, 0)
                
                # 计算渐变位置在裁剪区域内的相对位置
                rel_start = (draw_start - start_x) / band_width if band_width > 0 else 0
                rel_end = (draw_end - start_x) / band_width if band_width > 0 else 1
                
                # 映射渐变颜色到裁剪区域
                positions = [0.0, 0.15, 0.5, 0.85, 1.0]
                alphas = [0, 50, 200, 50, 0]
                
                for pos, alpha in zip(positions, alphas):
                    mapped_pos = rel_start + pos * (rel_end - rel_start)
                    if 0 <= mapped_pos <= 1:
                        actual_gradient.setColorAt(mapped_pos, 
                            QColor(self._ripple_color.red(),
                                   self._ripple_color.green(),
                                   self._ripple_color.blue(), alpha))
                
                painter.setBrush(QBrush(actual_gradient))
                painter.setPen(Qt.PenStyle.NoPen)
                
                band_rect = QRect(draw_start, draw_rect.y(), band_draw_width, draw_rect.height())
                painter.drawRoundedRect(band_rect, 3, 3)

    def setGeometry(self, rect: QRect):
        """设置几何形状，保持高度不变"""
        super().setGeometry(rect)


class AnimatedSplitter(QSplitter):
    """带动画分隔线效果的分割器"""

    def __init__(self, orientation: Qt.Orientation):
        super().__init__(orientation)
        self._animated_handle: Optional[AnimatedSplitterHandle] = None
        self._base_color: Optional[QColor] = None
        self._accent_color: Optional[QColor] = None
        self.setHandleWidth(10)  # 分隔线宽度（包含可拖拽区域）

    def createHandle(self) -> QSplitterHandle:
        """创建自定义的动画分隔线手柄"""
        self._animated_handle = AnimatedSplitterHandle(self.orientation(), self)
        # 如果已经设置了主题颜色，立即应用到新创建的 handle
        if self._base_color and self._accent_color:
            self._animated_handle.set_theme_colors(self._base_color, self._accent_color)
        return self._animated_handle

    def get_animated_handle(self) -> Optional[AnimatedSplitterHandle]:
        """获取动画分隔线手柄"""
        return self._animated_handle

    def set_theme_colors(self, base_color: QColor, accent_color: QColor):
        """设置主题颜色"""
        # 保存颜色以便后续创建的 handle 使用
        self._base_color = base_color
        self._accent_color = accent_color
        if self._animated_handle:
            self._animated_handle.set_theme_colors(base_color, accent_color)

    def start_animation(self):
        """启动动画"""
        if self._animated_handle:
            self._animated_handle.start_animation()

    def stop_animation(self):
        """停止动画"""
        if self._animated_handle:
            self._animated_handle.stop_animation()

    def is_animating(self) -> bool:
        """检查是否正在动画"""
        return self._animated_handle and self._animated_handle.is_animating()


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
            from src.core.translator import get_translator
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


class StreamingPolishingWorker(QThread):
    """流式润色工作线程"""

    chunk_received = pyqtSignal(str)
    polishing_finished = pyqtSignal(str)
    polishing_error = pyqtSignal(str)

    def __init__(self, text: str):
        super().__init__()
        self._text = text
        self._is_cancelled = False

    def run(self):
        try:
            from src.core.translator import get_translator
            translator = get_translator()
            full_text = ""

            for chunk in translator.polishing_stream(self._text):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.polishing_finished.emit(full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.polishing_error.emit(str(e))

    def cancel(self):
        """取消润色"""
        self._is_cancelled = True


class StreamingSummarizeWorker(QThread):
    """流式总结工作线程"""

    chunk_received = pyqtSignal(str)
    summarize_finished = pyqtSignal(str)
    summarize_error = pyqtSignal(str)

    def __init__(self, text: str, target_language: str = "中文"):
        super().__init__()
        self._text = text
        self._target_language = target_language
        self._is_cancelled = False

    def run(self):
        try:
            from src.core.translator import get_translator
            translator = get_translator()
            full_text = ""

            for chunk in translator.summarize_stream(self._text, self._target_language):
                if self._is_cancelled:
                    return

                if chunk:
                    full_text += chunk
                    self.chunk_received.emit(chunk)

            if not self._is_cancelled:
                self.summarize_finished.emit(full_text)

        except Exception as e:
            if not self._is_cancelled:
                self.summarize_error.emit(str(e))

    def cancel(self):
        """取消总结"""
        self._is_cancelled = True


class UpdateCheckWorker(QThread):
    """版本更新检查工作线程"""

    update_available = pyqtSignal(str)   # 有新版本，参数为新版本号
    no_update = pyqtSignal()             # 无新版本
    check_error = pyqtSignal()           # 检查失败

    def run(self):
        try:
            from ..utils.update_checker import check_for_update
        except ImportError:
            from src.utils.update_checker import check_for_update

        try:
            new_version = check_for_update()
            if new_version:
                self.update_available.emit(new_version)
            else:
                self.no_update.emit()
        except Exception:
            self.check_error.emit()


class TranslatorWindow(QWidget):
    """独立翻译窗口（无边框，支持调整大小、主题切换、纯文本显示）

    同时支持：
    1. 手动输入翻译模式
    2. 划词自动翻译模式（自动填充原文并翻译）
    """

    # CJK 字体回退链（中文、韩文、日文 + 通用 sans-serif）
    _FONT_FAMILIES = ["Microsoft YaHei", "Malgun Gothic", "Yu Gothic UI", "Noto Sans CJK SC", "sans-serif"]
    _FONT_FAMILY_CSS = '"Microsoft YaHei", "Malgun Gothic", "Yu Gothic UI", "Noto Sans CJK SC", sans-serif'

    # 信号
    closed = pyqtSignal()
    settings_requested = pyqtSignal()
    translation_completed = pyqtSignal(str, str)  # 原文, 译文 - 翻译完成信号

    def __init__(self):
        super().__init__()

        # 设置窗口对象名称
        self.setObjectName("TranslatorWindow")

        self._current_worker: Optional[StreamingTranslationWorker] = None

        # 窗口状态
        self._is_maximized = False
        self._is_minimized = False  # 最小化状态
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
        self._applied_style_signature = None

        # 划词翻译相关
        self._auto_mode = False  # 是否处于自动翻译模式
        self._pending_original_text = ""  # 待翻译的原文

        # 流式翻译高度调整相关
        self._height_animation = None  # 高度调整动画
        self._last_adjusted_height = 0  # 上一次调整的高度（避免重复调整）
        self._height_adjust_timer = None  # 高度调整定时器（延迟调整，减少频繁更新）
        self._is_streaming = False  # 是否正在流式输出
        self._scrollbar_hidden = False  # 滚动条是否被隐藏（流式输出高度增长时）
        self._user_resized_during_streaming = False  # 用户在流式期间手动调整了窗口大小
        self._user_manually_resized = False  # 用户手动调整了窗口大小（非流式输出自动变大）

        # 逐字输出相关
        self._char_queue = []  # 待输出的字符缓冲区
        self._char_timer = QTimer()  # 逐字输出定时器
        self._char_timer.setInterval(10)  # 每个字符间隔 10ms（快速打字效果）
        self._char_timer.timeout.connect(self._flush_char)
        self._pending_finish_callback = None  # 缓冲区清空后的完成回调

        # 润色差异：勾选「显示润色差异」时由客户端做词/短语级 diff，模型只返回纯文本
        self._polishing_diff_mode = False
        self._polishing_source_for_diff = ""
        self._polish_diff_snapshot = None  # (原文, 润色结果) — 主题切换时重绘高亮色

        # 固定高度模式（从配置读取）
        self._fixed_height_mode = get_config().get('translator_window.fixed_height_mode', False)

        # 记忆窗口位置（从配置读取，仅在当前会话内记忆，程序重启后重置）
        self._remember_window_position = get_config().get('translator_window.remember_window_position', False)
        self._saved_window_pos = None  # 保存的窗口位置 (QPoint)
        
        # 记忆窗口大小（从配置读取，跨会话记忆用户最后一次调整的大小）
        self._remember_window_size = get_config().get('translator_window.remember_window_size', False)
        self._saved_window_size = None  # 保存的窗口大小 (QSize)，从配置加载
        
        # 如果启用了记忆窗口大小，尝试从配置加载保存的大小
        if self._remember_window_size:
            saved_width = get_config().get('translator_window.last_window_width', None)
            saved_height = get_config().get('translator_window.last_window_height', None)
            if saved_width is not None and saved_height is not None:
                self._saved_window_size = QSize(saved_width, saved_height)

        # 始终置顶（从配置读取）
        self._always_on_top = get_config().get('translator_window.always_on_top', False)

        # 默认功能选择（从配置读取）
        self._default_function = get_config().get('translator_window.default_function', 'translate')

        # 版本更新检查相关
        self._update_check_worker: Optional[UpdateCheckWorker] = None
        self._update_available = False  # 是否有新版本
        self._daily_check_timer = QTimer(self)
        self._daily_check_timer.setSingleShot(True)
        self._daily_check_timer.timeout.connect(self._on_daily_check_timer)
        self._last_check_date: Optional[str] = None  # 上次检查日期 (YYYY-MM-DD)

        self._setup_window_properties()
        self._setup_ui()

        # 连接主题变更信号
        try:
            from ..utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self.update_theme)

        # 首次启动时检查更新
        QTimer.singleShot(3000, self._check_for_update)

        # 调度下一次中午12点的检查
        self._schedule_next_daily_check()

    def _create_text_font(self) -> QFont:
        """创建支持中日韩多语言的文本字体"""
        font = QFont()
        font.setFamilies(self._FONT_FAMILIES)
        font.setPointSize(self._font_size)
        return font

    def _ensure_output_plain_mode(self):
        """译文框恢复为纯文本模式（禁用富文本），避免上一轮润色 HTML 影响后续翻译。"""
        self._output_text.setAcceptRichText(False)

    def _clear_polish_diff_snapshot(self):
        """清除润色差异缓存（新任务或替换译文内容时调用）。"""
        self._polish_diff_snapshot = None

    def _apply_polish_diff_html(self, original: str, polished: str):
        """用词/短语级比对结果渲染删除/新增高亮（颜色随当前主题语义色混合）。"""
        try:
            from ..utils.polish_diff import build_polish_diff_html
        except ImportError:
            from src.utils.polish_diff import build_polish_diff_html
        theme = get_theme(self._theme_style)
        bg_deleted, bg_added = polish_diff_highlight_colors(theme)
        fragment = build_polish_diff_html(
            original,
            polished,
            text_color=theme["text_primary"],
            font_family_css=self._FONT_FAMILY_CSS,
            font_size_px=self._font_size,
            bg_deleted=bg_deleted,
            bg_added=bg_added,
        )
        self._output_text.setAcceptRichText(True)
        self._output_text.setHtml(fragment)

    def _setup_window_properties(self):
        """设置窗口属性"""
        flags = (
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 窗口最小高度计算：
        # 默认模式：标题栏(28) + 控制栏(38) + 边距(52) + 原文框(120) + 分割条(6) + 译文框(180) = 424
        # 固定高度模式：标题栏(28) + 控制栏(38) + 边距(52) + 原文框(180) + 分割条(6) + 译文框(360) = 704
        if self._fixed_height_mode:
            self.setMinimumSize(450, 660)
            self.resize(500, 660)
        else:
            self.setMinimumSize(450, 450)
            self.resize(500, 450)

        # 开启鼠标追踪
        self.setMouseTracking(True)

        # 设置窗口图标（任务栏图标）
        self._set_window_icon()

        # 在 Windows 上启用任务栏最小化和 Win+方向键贴靠/最大化
        self._enable_windows_window_management()

    def _set_window_icon(self):
        """设置窗口图标（任务栏图标）"""
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _enable_windows_window_management(self):
        """在 Windows 上启用系统窗口管理快捷键和任务栏最小化。"""
        try:
            if not sys.platform.startswith("win"):
                return

            import ctypes
            # 获取窗口句柄
            hwnd = int(self.winId())

            # 获取当前窗口样式
            GWL_STYLE = -16
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)

            # WS_THICKFRAME/WS_MAXIMIZEBOX 让 Windows 识别该无边框窗口可贴靠/最大化，
            # 因而支持 Win+方向键等系统窗口管理快捷键。
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            new_style = style | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU

            # 设置新样式
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)

            # 通知 Windows 重新计算非客户区样式，否则快捷键/贴靠状态可能不立即生效。
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )
        except Exception:
            pass

    def _create_copy_icon(self, theme: dict) -> QIcon:
        """创建复制图标（两个重叠的空心文档）"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 图标颜色使用主题的 muted 文本颜色
        icon_color = QColor(theme.get('text_muted', '#888888'))
        pen = QPen(icon_color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        # 不填充，只绘制边框
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)

        # 绘制后面的文档（偏移位置，稍微小一点）
        painter.drawRoundedRect(6, 1, 10, 13, 2, 2)

        # 绘制前面的文档（主位置）
        painter.drawRoundedRect(2, 4, 10, 13, 2, 2)

        painter.end()

        return QIcon(pixmap)

    def _create_speak_icon(self, theme: dict) -> QIcon:
        """创建朗读图标（播放三角形）"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 图标颜色使用主题的 muted 文本颜色
        icon_color = QColor(theme.get('text_muted', '#888888'))

        # 绘制播放三角形
        painter.setBrush(icon_color)
        painter.setPen(Qt.PenStyle.NoPen)

        # 三角形的三个顶点
        triangle = [
            QPointF(5, 3),    # 左上
            QPointF(5, 15),   # 左下
            QPointF(15, 9),   # 右中
        ]
        painter.drawPolygon(*triangle)

        painter.end()

        return QIcon(pixmap)

    def _create_history_icon(self, theme: dict) -> QIcon:
        """创建历史记录图标（时钟）"""
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        icon_color = QColor(theme.get('text_muted', '#888888'))
        pen = QPen(icon_color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)

        # 表盘圆
        painter.drawEllipse(QPointF(9, 9), 6.5, 6.5)
        # 时针
        painter.drawLine(QPointF(9, 9), QPointF(9, 5))
        # 分针
        painter.drawLine(QPointF(9, 9), QPointF(12.5, 9))

        painter.end()

        return QIcon(pixmap)

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
        # 开启鼠标追踪
        self._content_frame.setMouseTracking(True)
        layout.addWidget(self._content_frame)

        # 添加阴影效果
        self._shadow_effect = QGraphicsDropShadowEffect()
        self._shadow_effect.setBlurRadius(15)
        self._shadow_effect.setColor(QColor(*theme['shadow_color']))
        self._shadow_effect.setOffset(0, 2)
        self._content_frame.setGraphicsEffect(self._shadow_effect)

        # 内容布局
        content_layout = QVBoxLayout(self._content_frame)
        content_layout.setContentsMargins(12, 8, 12, 22)
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
        # 开启鼠标追踪，让鼠标移动事件能传递到主窗口
        self._title_bar.setMouseTracking(True)

        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(8, 0, 8, 0)

        # 标题图标
        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            title_icon = QLabel()
            title_pixmap = QPixmap(str(icon_path))
            title_icon.setPixmap(title_pixmap.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            title_icon.setMouseTracking(True)
            title_layout.addWidget(title_icon)
            title_layout.addSpacing(4)

        # 标题文字
        self._title_label = QLabel("QTranslator")
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {theme['text_muted']};
                font-size: 12px;
            }}
        """)
        self._title_label.setMouseTracking(True)
        title_layout.addWidget(self._title_label)
        title_layout.addStretch()

        # 更新按钮（初始隐藏，检测到新版本时显示）
        self._update_btn = QPushButton("⬆️")
        self._update_btn.setObjectName("updateBtn")
        self._update_btn.setFixedSize(22, 22)
        self._update_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._update_btn.setToolTip("有新版本可用，点击更新")
        self._update_btn.setStyleSheet(f"""
            QPushButton#updateBtn {{
                background-color: transparent;
                border: none;
                border-radius: 11px;
                font-size: 12px;
                padding-bottom: 2px;
            }}
            QPushButton#updateBtn:hover {{
                background-color: {theme['button_hover']};
            }}
        """)
        self._update_btn.clicked.connect(self._on_update_clicked)
        self._update_btn.hide()  # 默认隐藏
        title_layout.addWidget(self._update_btn)

        # 帮助按钮
        self._help_btn = QPushButton("?")
        self._help_btn.setObjectName("helpBtn")
        self._help_btn.setFixedSize(22, 22)
        self._help_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._help_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._help_btn.setToolTip("帮助")
        self._help_btn.setStyleSheet(f"""
            QPushButton#helpBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#helpBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)
        self._help_btn.clicked.connect(self._on_help_clicked)
        title_layout.addWidget(self._help_btn)

        # 设置按钮
        self._settings_btn = QPushButton("⛭")
        self._settings_btn.setObjectName("settingsBtn")
        self._settings_btn.setFixedSize(22, 22)
        self._settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._settings_btn.setToolTip("设置")
        self._settings_btn.setStyleSheet(f"""
            QPushButton#settingsBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 12px;
            }}
            QPushButton#settingsBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)
        self._settings_btn.clicked.connect(self._on_settings_clicked)
        title_layout.addWidget(self._settings_btn)

        # 最小化按钮
        self._minimize_btn = QPushButton("─")
        self._minimize_btn.setObjectName("minimizeBtn")
        self._minimize_btn.setFixedSize(22, 22)
        self._minimize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._minimize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._minimize_btn.setStyleSheet(f"""
            QPushButton#minimizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
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
        self._maximize_btn.setFixedSize(22, 22)
        self._maximize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._maximize_btn.setStyleSheet(f"""
            QPushButton#maximizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 12px;
                font-weight: bold;
                padding-bottom: 2px;
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
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self._lang_combo.setMaxVisibleItems(5)  # 避免弹出视图滚动
        self._lang_combo.setStyleSheet(get_combobox_style(theme))
        # 预创建弹出视图，避免首次打开时懒加载导致的卡顿
        self._lang_combo.view()
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
        self._translate_btn.setFixedSize(55, 28)  # 统一宽度55px
        self._translate_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._translate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:focus {{
                border: 1px solid transparent;
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._translate_btn.pressed.connect(lambda: self._set_default_function('translate'))
        self._translate_btn.clicked.connect(lambda: self._run_function_button('translate'))
        control_layout.addWidget(self._translate_btn)

        # 润色按钮
        self._polishing_btn = QPushButton("润色")
        self._polishing_btn.setFixedSize(55, 28)  # 统一宽度55px
        self._polishing_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._polishing_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:focus {{
                border: 1px solid {theme['border_color']};
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._polishing_btn.pressed.connect(lambda: self._set_default_function('polishing'))
        self._polishing_btn.clicked.connect(lambda: self._run_function_button('polishing'))
        control_layout.addWidget(self._polishing_btn)

        # 总结按钮
        self._summarize_btn = QPushButton("总结")
        self._summarize_btn.setFixedSize(55, 28)  # 统一宽度55px
        self._summarize_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._summarize_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:focus {{
                border: 1px solid {theme['border_color']};
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)
        self._summarize_btn.pressed.connect(lambda: self._set_default_function('summarize'))
        self._summarize_btn.clicked.connect(lambda: self._run_function_button('summarize'))
        control_layout.addWidget(self._summarize_btn)

        content_layout.addWidget(self._control_bar)

        # 分割器（使用动画分隔器）
        self._splitter = AnimatedSplitter(Qt.Orientation.Vertical)
        # 设置分隔线主题颜色
        base_color = QColor(theme['splitter_color'])
        accent_color = QColor(theme['accent_color'])
        self._splitter.set_theme_colors(base_color, accent_color)
        self._splitter.setChildrenCollapsible(False)

        # 原文输入区域 - 纯文本显示
        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText("输入要翻译的文本...")
        # 固定高度模式下原文框高度为180px，否则为120px
        input_min_height = 180 if self._fixed_height_mode else 120
        self._input_text.setMinimumHeight(input_min_height)
        self._input_text.setFont(self._create_text_font())
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-family: {self._FONT_FAMILY_CSS};
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
        self._input_text.installEventFilter(self)  # 安装事件过滤器以处理回车键
        self._splitter.addWidget(self._input_text)

        # 翻译结果显示区域 - 包装在容器中以支持右下角悬浮按钮
        # 容器仅用于定位，不设置 border-radius 避免裁剪遮罩在子控件滚动时产生残影
        self._output_container = QWidget()
        self._output_container.setStyleSheet("QWidget { background-color: transparent; border: none; }")
        # 不使用布局，使用绝对定位放置文本框和悬浮按钮
        # 固定高度模式下译文框高度为360px，否则为180px
        output_min_height = 360 if self._fixed_height_mode else 180
        self._output_container.setMinimumHeight(output_min_height)

        # 翻译结果文本框
        self._output_text = QTextEdit()
        self._output_text.setParent(self._output_container)
        self._output_text.setReadOnly(True)
        self._output_text.setFont(self._create_text_font())
        self._output_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._output_text.setPlaceholderText("翻译结果...")
        self._output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-family: {self._FONT_FAMILY_CSS};
                font-size: {self._font_size}px;
            }}
            {get_scrollbar_style(theme)}
        """)
        self._output_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._output_text.customContextMenuRequested.connect(self._show_output_context_menu)
        self._output_text.setAcceptRichText(False)  # 禁用富文本
        self._output_text.installEventFilter(self)

        # 悬浮按钮容器（右下角）- 完全透明，无边框
        self._floating_buttons_frame = QFrame()
        self._floating_buttons_frame.setParent(self._output_container)
        self._floating_buttons_frame.setObjectName("floatingButtonsFrame")
        self._floating_buttons_frame.setStyleSheet(f"""
            QFrame#floatingButtonsFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """)
        self._floating_buttons_layout = QHBoxLayout(self._floating_buttons_frame)
        self._floating_buttons_layout.setContentsMargins(4, 2, 4, 2)
        self._floating_buttons_layout.setSpacing(2)

        # 朗读按钮（朗读译文）- 使用绘制的播放图标
        self._speak_output_btn = QPushButton()
        self._speak_output_btn.setObjectName("speakOutputBtn")
        self._speak_output_btn.setFixedSize(28, 28)
        self._speak_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._speak_output_btn.setToolTip("朗读译文")
        self._speak_output_btn.setIcon(self._create_speak_icon(theme))
        self._speak_output_btn.setStyleSheet(f"""
            QPushButton#speakOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#speakOutputBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#speakOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
        """)
        self._speak_output_btn.clicked.connect(self._speak_output)
        self._floating_buttons_layout.addWidget(self._speak_output_btn)

        # 复制按钮 - 使用绘制的复制图标
        self._copy_output_btn = QPushButton()
        self._copy_output_btn.setObjectName("copyOutputBtn")
        self._copy_output_btn.setFixedSize(28, 28)
        self._copy_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._copy_output_btn.setToolTip("复制译文")
        self._copy_output_btn.setIcon(self._create_copy_icon(theme))
        self._copy_output_btn.setStyleSheet(f"""
            QPushButton#copyOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#copyOutputBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#copyOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
        """)
        self._copy_output_btn.clicked.connect(self._copy_all_text)
        self._floating_buttons_layout.addWidget(self._copy_output_btn)

        # 历史记录按钮 - 使用绘制的时钟图标
        self._history_output_btn = QPushButton()
        self._history_output_btn.setObjectName("historyOutputBtn")
        self._history_output_btn.setFixedSize(28, 28)
        self._history_output_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._history_output_btn.setToolTip("翻译历史")
        self._history_output_btn.setIcon(self._create_history_icon(theme))
        self._history_output_btn.setStyleSheet(f"""
            QPushButton#historyOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#historyOutputBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#historyOutputBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
        """)
        self._history_output_btn.clicked.connect(self._on_history_clicked)
        self._floating_buttons_layout.addWidget(self._history_output_btn)

        # 固定悬浮按钮容器大小
        self._floating_buttons_frame.setFixedSize(100, 34)

        self._splitter.addWidget(self._output_container)

        # 设置分割器初始比例（固定高度模式：原文框180px，译文框360px；默认：原文框120px，译文框180px）
        if self._fixed_height_mode:
            self._splitter.setSizes([180, 360])
        else:
            self._splitter.setSizes([120, 180])
        content_layout.addWidget(self._splitter, 1)

        # 为输出容器安装事件过滤器，以便处理 resize 事件更新悬浮按钮位置
        self._output_container.installEventFilter(self)

        # 为标题栏安装事件过滤器，以便处理鼠标移动事件更新光标
        self._title_bar.installEventFilter(self)
        self._title_label.installEventFilter(self)
        self._content_frame.installEventFilter(self)

        # 底部版本标签（绝对定位在右下角边框区域）
        self._version_label = QLabel(f"Powered by {VERSION_AUTHOR} v{APP_VERSION} ")
        self._version_label.setParent(self._content_frame)
        self._version_label.setObjectName("versionLabel")
        self._version_label.setStyleSheet(f"""
            QLabel#versionLabel {{
                color: {theme['text_muted']};
                font-size: 10px;
                background: transparent;
            }}
        """)
        self._version_label.adjustSize()
        self._version_label.raise_()

        # 应用默认功能的选中状态
        self._apply_default_function_style()

    def _on_minimize(self):
        """最小化窗口"""
        self._is_minimized = True
        self.showMinimized()  # 使用系统最小化

    def _on_update_clicked(self):
        """点击更新按钮，打开 GitHub Releases 页面"""
        try:
            from ..utils.update_checker import get_update_url
        except ImportError:
            from src.utils.update_checker import get_update_url
        webbrowser.open(get_update_url())

    def _on_settings_clicked(self):
        """点击设置按钮，打开设置对话框"""
        self.settings_requested.emit()

    def _on_history_clicked(self):
        """点击历史按钮，打开翻译历史窗口"""
        try:
            from ..ui.history_window import get_history_window
        except ImportError:
            from src.ui.history_window import get_history_window
        history_window = get_history_window()
        history_window.show_window()

    def _on_help_clicked(self):
        """点击帮助按钮，打开帮助窗口"""
        try:
            from ..ui.help_window import get_help_window
        except ImportError:
            from src.ui.help_window import get_help_window
        help_window = get_help_window()
        help_window.show_window()

    def _check_for_update(self):
        """启动版本更新检查（在后台线程中执行）"""
        if self._update_check_worker and self._update_check_worker.isRunning():
            return

        self._update_check_worker = UpdateCheckWorker()
        self._update_check_worker.update_available.connect(self._on_update_available)
        self._update_check_worker.no_update.connect(self._on_no_update)
        self._update_check_worker.check_error.connect(self._on_update_check_error)
        self._update_check_worker.start()

        # 记录本次检查日期
        self._last_check_date = datetime.now().strftime("%Y-%m-%d")

    def _schedule_next_daily_check(self):
        """计算距离下一个中午12点的毫秒数，设置单次定时器"""
        now = datetime.now()
        # 目标：今天12:00，如果已过则明天12:00
        target = now.replace(hour=12, minute=0, second=0, microsecond=0)
        if now >= target:
            # 已过今天12点，目标改为明天12点
            from datetime import timedelta
            target += timedelta(days=1)
        delay_ms = int((target - now).total_seconds() * 1000)
        self._daily_check_timer.start(delay_ms)

    def _on_daily_check_timer(self):
        """每日定时器触发，执行更新检查并调度下一次"""
        today = datetime.now().strftime("%Y-%m-%d")
        # 今天还没检查过才检查
        if self._last_check_date != today:
            self._check_for_update()
        # 调度下一次（明天12点）
        self._schedule_next_daily_check()

    def _on_update_available(self, new_version: str):
        """检测到新版本可用"""
        self._update_available = True
        self._update_btn.show()
        self._update_btn.setToolTip(f"新版本 {new_version} 可用，点击更新")

    def _on_no_update(self):
        """无新版本"""
        self._update_available = False
        self._update_btn.hide()

    def _on_update_check_error(self):
        """更新检查失败"""
        pass  # 静默失败，不影响用户使用

    def is_minimized(self) -> bool:
        """检查窗口是否最小化"""
        return self._is_minimized or self.windowState() & Qt.WindowState.WindowMinimized

    def restore_from_minimized(self):
        """从最小化状态恢复"""
        self._is_minimized = False
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _update_always_on_top(self):
        """动态切换窗口置顶属性（运行时配置变更时调用）"""
        was_visible = self.isVisible()
        flags = (
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # setWindowFlags 会隐藏窗口，需要重新显示
        if was_visible:
            self.show()
            self.raise_()
            self.activateWindow()
        # 重新设置 Windows 窗口管理支持（setWindowFlags 会重置 Win32 样式）
        self._enable_windows_window_management()

    @property
    def is_foreground(self) -> bool:
        """使用 Win32 API 精确检测窗口是否为当前前台窗口"""
        try:
            import ctypes
            hwnd = int(self.winId())
            foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()
            return hwnd == foreground_hwnd
        except Exception:
            pass
        return self.isActiveWindow()

    def bring_to_front(self):
        """将窗口唤醒到最顶层（使用 Win32 API 确保可靠地获取前台焦点）"""
        if self.isMinimized():
            self.restore_from_minimized()
            return

        if not self.isVisible():
            self.show_window()
            return

        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32

            # 获取当前前台窗口的线程 ID
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_tid = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            # 获取当前线程 ID
            current_tid = ctypes.windll.kernel32.GetCurrentThreadId()

            # AttachThreadInput 技巧：将本线程的输入处理关联到前台窗口线程
            # 这样 SetForegroundWindow 才能可靠地将窗口置前
            attached = False
            if foreground_tid != current_tid:
                attached = user32.AttachThreadInput(current_tid, foreground_tid, True)

            if not self._always_on_top:
                # 非置顶模式：先 TOPMOST 再 NOTOPMOST，窗口拉到最前但不保持置顶
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_SHOWWINDOW = 0x0040
                swp_flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, swp_flags)   # HWND_TOPMOST
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, swp_flags)   # HWND_NOTOPMOST

            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)

            if attached:
                user32.AttachThreadInput(current_tid, foreground_tid, False)
        except Exception:
            pass

        self.raise_()
        self.activateWindow()

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
            # 获取窗口当前所在的屏幕（而不是主屏幕）
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.availableGeometry())
            self._is_maximized = True
            self._maximize_btn.setText("❐")

        # 窗口大小改变后，如果正在流式翻译中，停止自动高度增长并显示滚动条
        if self._is_streaming:
            self._on_user_resize_during_streaming()

        # 标记用户手动调整了窗口大小（用于记忆窗口大小功能）
        self._user_manually_resized = True

    def update_theme(self):
        """更新主题"""
        new_theme = get_config().get('theme.popup_style', 'dark')
        new_font_size = get_config().get('font.size', 14)
        new_fixed_height_mode = get_config().get('translator_window.fixed_height_mode', False)
        new_style_signature = self._get_style_signature()

        # 同步记忆窗口位置配置
        self._remember_window_position = get_config().get('translator_window.remember_window_position', False)
        if not self._remember_window_position:
            self._saved_window_pos = None
        
        # 同步记忆窗口大小配置
        self._remember_window_size = get_config().get('translator_window.remember_window_size', False)
        if not self._remember_window_size:
            self._saved_window_size = None
        else:
            # 如果启用了记忆窗口大小，尝试从配置加载
            saved_width = get_config().get('translator_window.last_window_width', None)
            saved_height = get_config().get('translator_window.last_window_height', None)
            if saved_width is not None and saved_height is not None:
                self._saved_window_size = QSize(saved_width, saved_height)

        # 同步始终置顶配置
        new_always_on_top = get_config().get('translator_window.always_on_top', False)
        if new_always_on_top != self._always_on_top:
            self._always_on_top = new_always_on_top
            self._update_always_on_top()

        # 检查是否需要更新固定高度模式
        if new_fixed_height_mode != self._fixed_height_mode:
            self._fixed_height_mode = new_fixed_height_mode
            # 如果启用了固定高度模式，禁用记忆窗口大小
            if self._fixed_height_mode:
                self._remember_window_size = False
                get_config().set('translator_window.remember_window_size', False)
                get_config().save()
            # 更新最小高度和分割器尺寸
            input_min_height = 180 if self._fixed_height_mode else 120
            output_min_height = 360 if self._fixed_height_mode else 180
            self._input_text.setMinimumHeight(input_min_height)
            self._output_container.setMinimumHeight(output_min_height)
            if self._fixed_height_mode:
                self._splitter.setSizes([180, 360])
                self.setMinimumSize(450, 660)
                self.resize(500, 660)
            else:
                self._splitter.setSizes([120, 180])
                self.setMinimumSize(450, 450)
                # 注意：不再在这里 resize，让 show_window 来处理大小

        self._theme_style = new_theme
        self._font_size = new_font_size
        if self._applied_style_signature != new_style_signature:
            self._apply_theme()
            self._applied_style_signature = new_style_signature

    def _get_style_signature(self):
        """获取影响翻译窗口样式的配置签名。"""
        config = get_config()
        return (
            config.get('theme.popup_style', 'dark'),
            config.get('theme.custom_accent', '#007AFF'),
            config.get('theme.custom_bg', '#2d2d2d'),
            config.get('font.size', 14),
        )

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

        # 更新更新按钮样式
        self._update_btn.setStyleSheet(f"""
            QPushButton#updateBtn {{
                background-color: transparent;
                border: none;
                border-radius: 11px;
                font-size: 12px;
                padding-bottom: 2px;
            }}
            QPushButton#updateBtn:hover {{
                background-color: {theme['button_hover']};
            }}
        """)

        # 更新帮助按钮样式
        self._help_btn.setStyleSheet(f"""
            QPushButton#helpBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#helpBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)

        # 更新设置按钮样式
        self._settings_btn.setStyleSheet(f"""
            QPushButton#settingsBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
                font-size: 12px;
            }}
            QPushButton#settingsBtn:hover {{
                background-color: {theme['button_hover']};
                color: {theme['text_primary']};
            }}
        """)

        # 更新最小化按钮样式
        self._minimize_btn.setStyleSheet(f"""
            QPushButton#minimizeBtn {{
                background-color: transparent;
                color: {theme['text_muted']};
                border: none;
                border-radius: 11px;
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
                border-radius: 11px;
                font-size: 12px;
                font-weight: bold;
                padding-bottom: 2px;
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
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:focus {{
                border: 1px solid transparent;
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新润色按钮
        self._polishing_btn.setStyleSheet(f"""
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
            QPushButton:focus {{
                border: 1px solid {theme['border_color']};
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新总结按钮
        self._summarize_btn.setStyleSheet(f"""
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
            QPushButton:focus {{
                border: 1px solid {theme['border_color']};
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """)

        # 更新分割器颜色（使用动画分隔器的颜色设置）
        base_color = QColor(theme['splitter_color'])
        accent_color = QColor(theme['accent_color'])
        self._splitter.set_theme_colors(base_color, accent_color)

        # 更新输入框
        self._input_text.setFont(self._create_text_font())
        self._input_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-family: {self._FONT_FAMILY_CSS};
                font-size: {self._font_size}px;
            }}
            QTextEdit:focus {{
                border-color: {theme['accent_color']};
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新输出框容器 - 仅定位用，不渲染
        self._output_container.setStyleSheet("QWidget { background-color: transparent; border: none; }")

        # 更新输出框
        self._output_text.setFont(self._create_text_font())
        self._output_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 8px;
                font-family: {self._FONT_FAMILY_CSS};
                font-size: {self._font_size}px;
            }}
            {get_scrollbar_style(theme)}
        """)

        # 更新悬浮按钮容器样式 - 完全透明，无边框
        self._floating_buttons_frame.setStyleSheet(f"""
            QFrame#floatingButtonsFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """)

        # 根据主题背景亮度设置悬停/点击效果
        if _luminance(theme['bg_color']) < 0.5:
            hover_bg = "rgba(255, 255, 255, 0.15)"
            pressed_bg = "rgba(255, 255, 255, 0.25)"
        else:
            hover_bg = "rgba(0, 0, 0, 0.1)"
            pressed_bg = "rgba(0, 0, 0, 0.2)"

        # 更新复制按钮样式和图标
        self._copy_output_btn.setIcon(self._create_copy_icon(theme))
        self._copy_output_btn.setStyleSheet(f"""
            QPushButton#copyOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#copyOutputBtn:hover {{
                background-color: {hover_bg};
            }}
            QPushButton#copyOutputBtn:pressed {{
                background-color: {pressed_bg};
            }}
        """)

        # 更新朗读按钮样式和图标
        self._speak_output_btn.setIcon(self._create_speak_icon(theme))
        self._speak_output_btn.setStyleSheet(f"""
            QPushButton#speakOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#speakOutputBtn:hover {{
                background-color: {hover_bg};
            }}
            QPushButton#speakOutputBtn:pressed {{
                background-color: {pressed_bg};
            }}
        """)

        # 更新历史按钮样式和图标
        self._history_output_btn.setIcon(self._create_history_icon(theme))
        self._history_output_btn.setStyleSheet(f"""
            QPushButton#historyOutputBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#historyOutputBtn:hover {{
                background-color: {hover_bg};
            }}
            QPushButton#historyOutputBtn:pressed {{
                background-color: {pressed_bg};
            }}
        """)

        # 更新底部版本标签样式
        self._version_label.setStyleSheet(f"""
            QLabel#versionLabel {{
                color: {theme['text_muted']};
                font-size: 10px;
                background: transparent;
            }}
        """)

        # 应用默认功能按钮样式（确保主题切换后样式保持不变）
        self._apply_default_function_style()

        # 当前若显示「润色差异」HTML，则用新主题色重建（高亮底色随语义色适配）
        if self._polish_diff_snapshot:
            o, pol = self._polish_diff_snapshot
            try:
                self._apply_polish_diff_html(o, pol)
            except Exception:
                pass

    def _copy_all_text(self):
        """复制译文（润色差异视图下仅复制最终润色文，不包含删除片段）"""
        clipboard = QApplication.clipboard()
        if self._polish_diff_snapshot:
            _, polished = self._polish_diff_snapshot
            if polished:
                clipboard.setText(polished)
            return
        translated_text = self._output_text.toPlainText()
        if translated_text:
            clipboard.setText(translated_text)

    def _copy_output_standard(self):
        """译文框右键「复制」：差异视图下复制全文润色稿，否则复制当前选区。"""
        if self._polish_diff_snapshot:
            _, polished = self._polish_diff_snapshot
            if polished:
                QApplication.clipboard().setText(polished)
            return
        self._output_text.copy()

    def _speak_output(self):
        """朗读译文"""
        if self._polish_diff_snapshot:
            _, text = self._polish_diff_snapshot
        else:
            text = self._output_text.toPlainText()
        if text:
            tts = get_tts()
            if tts.is_speaking():
                tts.stop()
            else:
                tts.speak(text)

    def _clear_all(self):
        """清空所有内容并取消正在进行的流式输出任务"""
        # 1. 如果当前有翻译/总结/润色任务正在执行，取消它
        if self._current_worker and self._current_worker.isRunning():
            # 调用取消机制，设置取消标志
            self._current_worker.cancel()
            # 等待线程结束（最多1秒），避免资源泄露
            self._current_worker.wait(1000)
            # 清理 worker 引用
            self._current_worker = None

        # 2. 重置流式输出状态变量
        self._is_streaming = False
        self._scrollbar_hidden = False
        self._user_resized_during_streaming = False
        if hasattr(self, '_streaming_text'):
            self._streaming_text = ""

        # 2.1 停止逐字输出定时器并清空缓冲区
        self._char_timer.stop()
        self._char_queue.clear()
        self._pending_finish_callback = None

        # 3. 恢复滚动条显示（如果之前被隐藏）
        self._show_output_scrollbar()

        # 4. 清空输入和输出文本框
        self._input_text.clear()
        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()

        # 5. 重置划词翻译相关状态
        self._auto_mode = False
        self._pending_original_text = ""

        # 6. 重新启用之前被禁用的操作按钮
        self._translate_btn.setEnabled(True)
        self._polishing_btn.setEnabled(True)
        self._summarize_btn.setEnabled(True)

        # 7. 停止分隔线动画（如果正在播放）
        self._splitter.stop_animation()

        # 8. 清理高度调整定时器（如果存在）
        if self._height_adjust_timer:
            self._height_adjust_timer.stop()
            self._height_adjust_timer = None

        # 9. 不重置窗口高度，保持当前窗口大小状态
        # 只恢复滚动条显示
        self._show_output_scrollbar()
        self._scrollbar_hidden = False

    def _disconnect_worker_signals(self):
        """断开当前工作线程的所有信号连接，防止残留信号污染新任务"""
        if not self._current_worker:
            return
        for signal_name in ['chunk_received', 'translation_finished', 'translation_error',
                            'polishing_finished', 'polishing_error',
                            'summarize_finished', 'summarize_error']:
            try:
                getattr(self._current_worker, signal_name).disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass

    def _start_translation(self):
        """开始翻译"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        # 取消之前的翻译
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
        # 断开旧 worker 信号，防止事件队列中的残留信号污染新任务
        self._disconnect_worker_signals()
        self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()
        self._streaming_text = ""

        # 初始化流式状态
        self._is_streaming = True
        self._last_adjusted_height = 0
        self._scrollbar_hidden = False  # 重置滚动条隐藏状态
        self._user_resized_during_streaming = False  # 重置用户手动调整标志
        self._char_queue.clear()  # 清空逐字输出缓冲区
        self._char_timer.stop()  # 停止逐字输出定时器
        self._pending_finish_callback = None  # 重置完成回调

        # 锁定原文框高度，防止流式输出期间 splitter 重新分配导致文字跳动
        self._lock_input_height()

        # 流式输出开始时隐藏滚动条（固定高度模式下不隐藏，保持滚动条显示）
        if not self._fixed_height_mode:
            self._hide_output_scrollbar()

        # 禁用按钮（按钮文字保持不变，通过禁用状态表示正在处理）
        self._translate_btn.setEnabled(False)
        self._polishing_btn.setEnabled(False)
        self._summarize_btn.setEnabled(False)

        # 启动分隔线动画（指示正在翻译）
        self._splitter.start_animation()

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
        """收到翻译片段 - 将字符加入逐字输出缓冲区"""
        try:
            # 忽略来自已取消/旧工作线程的残留信号
            if self.sender() is not self._current_worker:
                return

            if not hasattr(self, '_streaming_text'):
                self._streaming_text = ""
                self._is_streaming = True
                self._last_adjusted_height = 0

            # 将 chunk 中的每个字符加入缓冲区
            self._char_queue.extend(chunk)

            # 启动逐字输出定时器（如果尚未启动）
            if not self._char_timer.isActive():
                self._char_timer.start()
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _flush_char(self):
        """逐字输出定时器回调：每次从缓冲区取出一个字符插入文本框"""
        try:
            if not self._char_queue:
                # 缓冲区为空，停止定时器
                self._char_timer.stop()
                # 如果流式已结束且缓冲区清空，执行完成回调
                if hasattr(self, '_pending_finish_callback') and self._pending_finish_callback:
                    callback = self._pending_finish_callback
                    self._pending_finish_callback = None
                    callback()
                return

            # 每次输出 3 个字符，提高速度感（10ms * 3 = 每秒约300字）
            batch_size = 3
            chars_to_insert = []
            for _ in range(batch_size):
                if self._char_queue:
                    chars_to_insert.append(self._char_queue.pop(0))
                else:
                    break

            if not chars_to_insert:
                return

            chunk = ''.join(chars_to_insert)
            self._streaming_text += chunk

            # 在插入文本之前记录滚动位置
            scrollbar = self._output_text.verticalScrollBar()
            was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 10

            # 使用 QTextCursor 追加文本，避免频繁 setPlainText 导致滚动条闪烁
            cursor = self._output_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(chunk)

            # 滚动策略：
            # - 窗口自动增长期间（滚动条隐藏）：不改变滚动位置
            # - 窗口达到最大高度后（滚动条可见）：自动滚动到底部跟随新内容
            if not self._scrollbar_hidden and was_at_bottom:
                scrollbar.setValue(scrollbar.maximum())

            # 触发高度调整（延迟执行，避免频繁更新）- 固定高度模式下不调整
            if self._is_streaming and not self._fixed_height_mode:
                self._schedule_height_adjust()
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_translation_finished(self, result: str):
        """翻译完成 - 等待逐字缓冲区清空后再执行完成逻辑"""
        if self.sender() is not self._current_worker:
            return
        from PyQt6.QtCore import QTimer
        if self._char_queue:
            # 缓冲区还有字符，延迟执行完成逻辑
            self._pending_finish_callback = lambda: self._do_translation_finished(result)
        else:
            QTimer.singleShot(0, lambda: self._do_translation_finished(result))

    def _do_translation_finished(self, result: str):
        """实际执行翻译完成操作"""
        try:
            self._is_streaming = False
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)

            # 停止分隔线动画（翻译完成）
            self._splitter.stop_animation()

            # 最终高度调整（固定高度模式下不调整）
            if not self._fixed_height_mode:
                QTimer.singleShot(100, self._final_height_adjust)

            # 调试输出
            try:
                from src.utils.logger import log_debug
                log_debug(f"翻译完成，最终高度调整已调度")
            except:
                pass

            # 发出翻译完成信号（用于划词翻译模式）
            if self._auto_mode:
                original_text = self._pending_original_text or self._input_text.toPlainText()
                self.translation_completed.emit(original_text, result)

            self._current_worker = None

            # 保存翻译历史
            if result:
                try:
                    from src.utils.history import add_translation_history
                    target_lang = self._lang_combo.currentText()
                    if target_lang == "自动检测":
                        target_lang = "中文"  # 默认
                    add_translation_history(
                        self._input_text.toPlainText(),
                        result,
                        target_lang,
                        "selection" if self._auto_mode else "manual"
                    )
                except Exception:
                    pass

            # 重置自动翻译模式
            self._auto_mode = False
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_translation_error(self, error: str):
        """翻译错误"""
        if self.sender() is not self._current_worker:
            return
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_translation_error(error))

    def _do_translation_error(self, error: str):
        """实际执行翻译错误操作"""
        try:
            self._is_streaming = False
            self._scrollbar_hidden = False
            # 停止逐字输出并清空缓冲区
            self._char_timer.stop()
            self._char_queue.clear()
            self._pending_finish_callback = None
            # 恢复滚动条显示
            self._show_output_scrollbar()
            self._ensure_output_plain_mode()
            self._clear_polish_diff_snapshot()
            self._output_text.setPlainText(f"翻译失败: {error}")
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            # 停止分隔线动画（翻译失败）
            self._splitter.stop_animation()
            self._current_worker = None
            # 重置自动翻译模式
            self._auto_mode = False
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _start_polishing(self):
        """开始润色"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        self._polishing_diff_mode = get_config().get("polishing.show_diff", False)
        self._polishing_source_for_diff = text if self._polishing_diff_mode else ""

        # 取消之前的任务
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
        # 断开旧 worker 信号，防止事件队列中的残留信号污染新任务
        self._disconnect_worker_signals()
        self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()
        self._streaming_text = ""

        # 初始化流式状态
        self._is_streaming = True
        self._last_adjusted_height = 0
        self._scrollbar_hidden = False
        self._user_resized_during_streaming = False  # 重置用户手动调整标志
        self._char_queue.clear()  # 清空逐字输出缓冲区
        self._char_timer.stop()  # 停止逐字输出定时器
        self._pending_finish_callback = None  # 重置完成回调

        # 锁定原文框高度，防止流式输出期间 splitter 重新分配导致文字跳动
        self._lock_input_height()

        # 流式输出开始时隐藏滚动条（固定高度模式下不隐藏）
        if not self._fixed_height_mode:
            self._hide_output_scrollbar()

        # 禁用所有操作按钮（按钮文字保持不变，通过禁用状态表示正在处理）
        self._translate_btn.setEnabled(False)
        self._polishing_btn.setEnabled(False)
        self._summarize_btn.setEnabled(False)

        # 启动分隔线动画（指示正在润色）
        self._splitter.start_animation()

        # 启动润色线程
        self._current_worker = StreamingPolishingWorker(text)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.polishing_finished.connect(self._on_polishing_finished)
        self._current_worker.polishing_error.connect(self._on_polishing_error)
        self._current_worker.start()

    def _on_polishing_finished(self, result: str):
        """润色完成 - 等待逐字缓冲区清空后再执行完成逻辑"""
        if self.sender() is not self._current_worker:
            return
        from PyQt6.QtCore import QTimer
        if self._char_queue:
            self._pending_finish_callback = lambda: self._do_polishing_finished(result)
        else:
            QTimer.singleShot(0, lambda: self._do_polishing_finished(result))

    def _do_polishing_finished(self, result: str):
        """实际执行润色完成操作（在主线程中）"""
        try:
            self._is_streaming = False
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            # 停止分隔线动画（润色完成）
            self._splitter.stop_animation()
            self._current_worker = None

            if self._polishing_diff_mode:
                snap_o = self._polishing_source_for_diff
                try:
                    if result and result.strip():
                        self._apply_polish_diff_html(snap_o, result)
                        self._polish_diff_snapshot = (snap_o, result)
                    else:
                        self._clear_polish_diff_snapshot()
                except Exception:
                    self._clear_polish_diff_snapshot()
                    self._ensure_output_plain_mode()
                    if result:
                        self._output_text.setPlainText(result)
                finally:
                    self._polishing_diff_mode = False
                    self._polishing_source_for_diff = ""

            # 最终高度调整（固定高度模式下不调整）
            if not self._fixed_height_mode:
                QTimer.singleShot(100, self._final_height_adjust)

            # 保存润色历史
            if result:
                try:
                    from src.utils.history import add_translation_history
                    add_translation_history(
                        self._input_text.toPlainText(),
                        result,
                        "润色",
                        "polishing"
                    )
                except Exception:
                    pass
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_polishing_error(self, error: str):
        """润色错误"""
        if self.sender() is not self._current_worker:
            return
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_polishing_error(error))

    def _do_polishing_error(self, error: str):
        """实际执行润色错误操作（在主线程中）"""
        try:
            self._is_streaming = False
            self._scrollbar_hidden = False
            # 停止逐字输出并清空缓冲区
            self._char_timer.stop()
            self._char_queue.clear()
            self._pending_finish_callback = None
            # 恢复滚动条显示
            self._show_output_scrollbar()
            self._polishing_diff_mode = False
            self._polishing_source_for_diff = ""
            self._clear_polish_diff_snapshot()
            self._ensure_output_plain_mode()
            self._output_text.setPlainText(f"润色失败: {error}")
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            # 停止分隔线动画（润色失败）
            self._splitter.stop_animation()
            self._current_worker = None
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _start_summarize(self):
        """开始总结"""
        text = self._input_text.toPlainText().strip()
        if not text:
            return

        # 取消之前的任务
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
        # 断开旧 worker 信号，防止事件队列中的残留信号污染新任务
        self._disconnect_worker_signals()
        self._current_worker = None

        # 清空输出
        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()
        self._streaming_text = ""

        # 初始化流式状态
        self._is_streaming = True
        self._last_adjusted_height = 0
        self._scrollbar_hidden = False
        self._user_resized_during_streaming = False  # 重置用户手动调整标志
        self._char_queue.clear()  # 清空逐字输出缓冲区
        self._char_timer.stop()  # 停止逐字输出定时器
        self._pending_finish_callback = None  # 重置完成回调

        # 锁定原文框高度，防止流式输出期间 splitter 重新分配导致文字跳动
        self._lock_input_height()

        # 流式输出开始时隐藏滚动条（固定高度模式下不隐藏）
        if not self._fixed_height_mode:
            self._hide_output_scrollbar()

        # 禁用所有操作按钮（按钮文字保持不变，通过禁用状态表示正在处理）
        self._translate_btn.setEnabled(False)
        self._polishing_btn.setEnabled(False)
        self._summarize_btn.setEnabled(False)

        # 启动分隔线动画（指示正在总结）
        self._splitter.start_animation()

        # 获取目标语言（用于总结输出的语言）
        target_language = self._lang_combo.currentText()
        if target_language == "自动检测":
            target_language = "中文"

        # 启动总结线程
        self._current_worker = StreamingSummarizeWorker(text, target_language)
        self._current_worker.chunk_received.connect(self._on_chunk_received)
        self._current_worker.summarize_finished.connect(self._on_summarize_finished)
        self._current_worker.summarize_error.connect(self._on_summarize_error)
        self._current_worker.start()

    def _on_summarize_finished(self, result: str):
        """总结完成 - 等待逐字缓冲区清空后再执行完成逻辑"""
        if self.sender() is not self._current_worker:
            return
        from PyQt6.QtCore import QTimer
        if self._char_queue:
            self._pending_finish_callback = lambda: self._do_summarize_finished(result)
        else:
            QTimer.singleShot(0, lambda: self._do_summarize_finished(result))

    def _do_summarize_finished(self, result: str):
        """实际执行总结完成操作"""
        try:
            self._is_streaming = False
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            # 停止分隔线动画（总结完成）
            self._splitter.stop_animation()
            self._current_worker = None

            # 最终高度调整（固定高度模式下不调整）
            if not self._fixed_height_mode:
                QTimer.singleShot(100, self._final_height_adjust)

            # 保存总结历史
            if result:
                try:
                    from src.utils.history import add_translation_history
                    target_lang = self._lang_combo.currentText()
                    if target_lang == "自动检测":
                        target_lang = "中文"
                    add_translation_history(
                        self._input_text.toPlainText(),
                        result,
                        target_lang,
                        "summarize"
                    )
                except Exception:
                    pass
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _on_summarize_error(self, error: str):
        """总结错误"""
        if self.sender() is not self._current_worker:
            return
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_summarize_error(error))

    def _do_summarize_error(self, error: str):
        """实际执行总结错误操作"""
        try:
            self._is_streaming = False
            self._scrollbar_hidden = False
            # 停止逐字输出并清空缓冲区
            self._char_timer.stop()
            self._char_queue.clear()
            self._pending_finish_callback = None
            # 恢复滚动条显示
            self._show_output_scrollbar()
            self._ensure_output_plain_mode()
            self._clear_polish_diff_snapshot()
            self._output_text.setPlainText(f"总结失败: {error}")
            self._translate_btn.setEnabled(True)
            self._polishing_btn.setEnabled(True)
            self._summarize_btn.setEnabled(True)
            # 停止分隔线动画（总结失败）
            self._splitter.stop_animation()
            self._current_worker = None
        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

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
        copy_action.triggered.connect(self._copy_output_standard)

        copy_all_action = menu.addAction("复制全部译文")
        copy_all_action.triggered.connect(self._copy_all_text)

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

        # 计算按钮区域（按钮都在标题栏右侧）
        # 按钮大小 20x20
        button_width = 20
        # 基础四个按钮（设置、最小化、最大化、关闭），如果更新按钮可见则加一个
        button_count = 5 if self._update_available else 4
        total_buttons_width = button_width * button_count + 8  # 额外8px间距余量

        # 标题栏右边距
        right_margin = 8

        # 按钮区域的左边界
        window_width = self.width()
        buttons_left = window_width - right_margin - total_buttons_width

        # 检查鼠标是否在按钮区域内
        return pos.x() >= buttons_left

    def _get_resize_edge(self, pos: QPoint) -> Optional[str]:
        """判断鼠标位置对应的调整边缘（优化灵敏度）"""
        # 边缘检测区域 - 覆盖整个边框和边缘附近的区域
        edge_margin = 15  # 边缘检测宽度

        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()

        # 分别检测四个方向的边缘（不使用 elif，以支持组合）
        on_left = x <= edge_margin
        on_right = x >= w - edge_margin
        on_top = y <= edge_margin
        on_bottom = y >= h - edge_margin

        # 组合边缘检测结果
        edge = None

        if on_top and on_left:
            edge = 'top-left'
        elif on_top and on_right:
            edge = 'top-right'
        elif on_bottom and on_left:
            edge = 'bottom-left'
        elif on_bottom and on_right:
            edge = 'bottom-right'
        elif on_top:
            edge = 'top'
        elif on_bottom:
            edge = 'bottom'
        elif on_left:
            edge = 'left'
        elif on_right:
            edge = 'right'

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

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """鼠标双击事件 - 双击标题栏切换最大化状态"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            title_bar_height = 28

            # 检查是否在标题栏区域且不在按钮区域
            if pos.y() <= title_bar_height and not self._is_over_title_bar_buttons(pos):
                # 双击标题栏任意位置切换最大化
                self._on_maximize()
                return

        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()

            # 优先检测边缘调整区域（让调整大小优先于拖动）
            edge = self._get_resize_edge(pos)
            if edge:
                self._is_resizing = True
                self._resize_edge = edge
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
            else:
                # 不是边缘区域，检测标题栏拖动
                title_bar_height = 28
                if pos.y() <= title_bar_height and not self._is_over_title_bar_buttons(pos):
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
            # 1. 首先检查边框调整区域
            edge = self._get_resize_edge(pos)
            if edge:
                self._update_cursor_for_edge(edge)
            # 2. 其他区域显示默认箭头光标（标题栏不显示拖动光标）
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            was_resizing = self._is_resizing
            self._is_dragging = False
            self._drag_start_pos = None
            self._is_resizing = False
            self._resize_edge = None

            # 如果刚刚结束了窗口大小调整，且正在流式翻译中，
            # 停止自动高度增长并立即显示滚动条，让用户可以滚动查看内容
            if was_resizing and self._is_streaming:
                self._on_user_resize_during_streaming()

            # 标记用户手动调整了窗口大小（用于记忆窗口大小功能）
            if was_resizing:
                self._user_manually_resized = True

        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        # 鼠标离开窗口时恢复默认光标
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(event)

    def eventFilter(self, obj, event):
        """事件过滤器 - 处理子控件的鼠标事件和输入框的键盘事件"""
        # 译文框 Ctrl+C：润色差异视图下只复制最终润色稿（与复制按钮一致）
        if hasattr(self, "_output_text") and obj == self._output_text and event.type() == event.Type.KeyPress:
            if (
                event.key() == Qt.Key.Key_C
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and self._polish_diff_snapshot
            ):
                polished = self._polish_diff_snapshot[1]
                if polished:
                    QApplication.clipboard().setText(polished)
                    return True

        # 处理输出容器的 resize 事件（确保属性已存在）
        if hasattr(self, '_output_container') and obj == self._output_container and event.type() == event.Type.Resize:
            self._update_output_layout()
            return False  # 不拦截，让事件继续传播

        # 处理内容框架的 resize 事件（更新版本标签位置）
        if hasattr(self, '_version_label') and obj == self._content_frame and event.type() == event.Type.Resize:
            self._update_version_label_position()
            return False

        # 处理输入框的键盘事件
        if hasattr(self, '_input_text') and obj == self._input_text and event.type() == event.Type.KeyPress:
            key = event.key()
            # 处理回车键
            if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                # Shift+回车：换行（不拦截，让 QTextEdit 处理）
                if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                    return False  # 不拦截，让事件继续传播
                # 回车（无修饰）：触发默认功能
                if self._input_text.toPlainText().strip():
                    self._execute_default_function()
                    return True  # 拦截事件，阻止换行

        if event.type() == event.Type.MouseMove:
            # 获取鼠标在主窗口中的位置
            pos = self.mapFromGlobal(obj.mapToGlobal(event.position().toPoint()))

            # 更新光标样式
            edge = self._get_resize_edge(pos)
            if edge:
                self._update_cursor_for_edge(edge)
                obj.setCursor(QCursor(self._get_cursor_shape_for_edge(edge)))
            else:
                # 其他区域显示默认箭头光标（标题栏不显示拖动光标）
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                obj.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        elif event.type() == event.Type.Leave:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            obj.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        return super().eventFilter(obj, event)

    def _update_output_layout(self):
        """更新输出区域的布局（文本框和悬浮按钮位置）"""
        try:
            container_width = self._output_container.width()
            container_height = self._output_container.height()

            # 更新文本框大小（填充整个容器）
            self._output_text.setGeometry(0, 0, container_width, container_height)

            # 更新悬浮按钮位置（右下角，留出一定边距）
            button_width = self._floating_buttons_frame.width()
            button_height = self._floating_buttons_frame.height()
            margin = 6

            # 悬浮按钮位置：右下角，考虑边距
            button_x = container_width - button_width - margin
            button_y = container_height - button_height - margin

            self._floating_buttons_frame.move(button_x, button_y)

        except RuntimeError:
            # 窗口已被销毁，忽略
            pass

    def _update_version_label_position(self):
        """更新底部版本标签位置（右下角）"""
        try:
            frame_width = self._content_frame.width()
            frame_height = self._content_frame.height()
            label_width = self._version_label.width()
            label_height = self._version_label.height()
            # 定位在左下角，考虑左边距
            x = 18
            y = frame_height - label_height - 6
            self._version_label.move(x, y)
        except RuntimeError:
            pass

    def _set_default_function(self, function_name: str):
        """设置默认功能
        
        Args:
            function_name: 功能名称 ('translate', 'polishing', 'summarize')
        """
        # 保存设置到配置文件
        self._default_function = function_name
        get_config().set('translator_window.default_function', function_name)
        get_config().save()
        
        # 应用按钮样式
        self._apply_default_function_style()
        
        # 显示提示信息
        function_labels = {
            'translate': '翻译',
            'polishing': '润色',
            'summarize': '总结'
        }
        label = function_labels.get(function_name, '翻译')
        self._title_label.setText(f"QTranslator - 默认功能: {label}")
        
        # 2秒后恢复标题
        QTimer.singleShot(2000, lambda: self._title_label.setText("QTranslator"))

    def _run_function_button(self, function_name: str):
        """按钮左键点击：执行按钮本身功能（默认功能已在 pressed 阶段切换）。"""
        if function_name == 'translate':
            self._start_translation()
        elif function_name == 'polishing':
            self._start_polishing()
        elif function_name == 'summarize':
            self._start_summarize()

    def _apply_default_function_style(self):
        """应用默认功能按钮样式"""
        theme = get_theme(self._theme_style)
        
        # 选中的按钮样式（使用翻译按钮的颜色）
        selected_style = f"""
            QPushButton {{
                background-color: {theme['accent_color']};
                color: #ffffff;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['accent_hover']};
            }}
            QPushButton:focus {{
                border: 1px solid transparent;
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['accent_color']};
                color: #ffffff;
            }}
        """

        # 未选中的按钮样式
        normal_style = f"""
            QPushButton {{
                background-color: {theme['button_bg']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border_color']};
                border-radius: 4px;
                padding: 0 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {theme['button_hover']};
            }}
            QPushButton:focus {{
                border: 1px solid {theme['border_color']};
                outline: none;
            }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """
        
        # 根据默认功能应用样式
        if self._default_function == 'translate':
            self._translate_btn.setStyleSheet(selected_style)
            self._polishing_btn.setStyleSheet(normal_style)
            self._summarize_btn.setStyleSheet(normal_style)
        elif self._default_function == 'polishing':
            self._translate_btn.setStyleSheet(normal_style)
            self._polishing_btn.setStyleSheet(selected_style)
            self._summarize_btn.setStyleSheet(normal_style)
        elif self._default_function == 'summarize':
            self._translate_btn.setStyleSheet(normal_style)
            self._polishing_btn.setStyleSheet(normal_style)
            self._summarize_btn.setStyleSheet(selected_style)

    def _execute_default_function(self):
        """执行当前选中的默认功能"""
        if self._default_function == 'translate':
            self._start_translation()
        elif self._default_function == 'polishing':
            self._start_polishing()
        elif self._default_function == 'summarize':
            self._start_summarize()
        else:
            # 默认执行翻译
            self._start_translation()

    def _get_cursor_shape_for_edge(self, edge: Optional[str]) -> Qt.CursorShape:
        """根据边缘获取光标形状"""
        if edge == 'top-left' or edge == 'bottom-right':
            return Qt.CursorShape.SizeFDiagCursor
        elif edge == 'top-right' or edge == 'bottom-left':
            return Qt.CursorShape.SizeBDiagCursor
        elif edge == 'left' or edge == 'right':
            return Qt.CursorShape.SizeHorCursor
        elif edge == 'top' or edge == 'bottom':
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def changeEvent(self, event):
        """窗口状态变化事件"""
        if event.type() == event.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                # 窗口被最小化
                self._is_minimized = True
            elif self.windowState() & Qt.WindowState.WindowMaximized:
                # Win+上方向键等系统快捷键触发最大化
                self._is_minimized = False
                self._is_maximized = True
                self._maximize_btn.setText("❐")
            elif self._is_minimized and not (self.windowState() & Qt.WindowState.WindowMinimized):
                # 窗口从最小化恢复
                self._is_minimized = False
            elif self._is_maximized and self.windowState() == Qt.WindowState.WindowNoState:
                # Win+下方向键等系统快捷键恢复普通窗口
                self._is_maximized = False
                self._maximize_btn.setText("□")
        super().changeEvent(event)

    def closeEvent(self, event):
        """窗口关闭事件"""
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.cancel()
            self._current_worker.wait(1000)
            self._current_worker = None

        # 重置自动翻译模式
        self._auto_mode = False
        self._pending_original_text = ""

        event.ignore()
        self.hide()

    def show_window(self):
        """显示窗口"""
        # 如果窗口处于最小化状态，先恢复正常
        if self.isMinimized():
            self.showNormal()

        self._is_minimized = False

        # 重置流式翻译状态（与 show_at_mouse 中 _reset_window_height 保持一致）
        # 防止窗口隐藏前的翻译状态残留导致分割条异常
        self._is_streaming = False
        self._scrollbar_hidden = False
        self._user_resized_during_streaming = False
        self._last_adjusted_height = 0

        # 停止可能残留的定时器和动画
        if self._height_adjust_timer and self._height_adjust_timer.isActive():
            self._height_adjust_timer.stop()
        from PyQt6.QtCore import QPropertyAnimation
        if self._height_animation and self._height_animation.state() == QPropertyAnimation.State.Running:
            self._height_animation.stop()

        # 恢复滚动条显示（内部会解锁原文框高度并设置 stretch factor 为 (0,1)）
        self._show_output_scrollbar()

        self.update_theme()

        # 固定高度模式下，每次显示都重置到预设尺寸
        if self._fixed_height_mode:
            self.setMinimumSize(450, 660)
            self.resize(500, 660)
        # 记忆窗口大小模式下，应用上次保存的大小
        elif self._remember_window_size and self._saved_window_size is not None:
            self.setMinimumSize(450, 450)
            self.resize(self._saved_window_size)

        # 记忆窗口位置：优先使用保存的位置，否则居中显示
        if self._remember_window_position and self._saved_window_pos is not None:
            self.move(self._saved_window_pos)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geo = screen.availableGeometry()
                x = (screen_geo.width() - self.width()) // 2
                y = (screen_geo.height() - self.height()) // 2
                self.move(x, y)

        if not self.isVisible():
            self._input_text.setFocus()
            self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event):
        """键盘事件处理"""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return

        # 当焦点不在输入框时，回车键执行默认功能
        # 输入框的回车键由事件过滤器处理（回车=默认功能，Shift+回车=换行）
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if not self._input_text.hasFocus() and self._input_text.toPlainText().strip():
                self._execute_default_function()
                return

        super().keyPressEvent(event)

    # ==================== 划词翻译模式支持 ====================

    def _get_screen_bounds(self):
        """获取屏幕可用区域"""
        try:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableVirtualGeometry()
                return (geo.x(), geo.y(), geo.width(), geo.height())
        except Exception:
            pass
        return (0, 0, 1920, 1080)

    def _calculate_position(self, mouse_pos):
        """计算悬浮窗位置（考虑屏幕边界）

        窗口位置计算策略：
        1. 默认显示在鼠标右下方
        2. 如果右侧空间不足，显示在左侧
        3. 如果下方空间不足以放置当前窗口高度，显示在上方
        4. 确保窗口不会超出屏幕边界
        """
        x, y = mouse_pos
        # 使用鼠标位置所在的屏幕
        try:
            screen = QApplication.screenAt(QPoint(x, y))
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                screen_x, screen_y, screen_w, screen_h = geo.x(), geo.y(), geo.width(), geo.height()
            else:
                screen_x, screen_y, screen_w, screen_h = 0, 0, 1920, 1080
        except Exception:
            screen_x, screen_y, screen_w, screen_h = self._get_screen_bounds()

        win_w = self.width()
        win_h = self.height()

        new_x = x + 15
        new_y = y + 15

        # 检查水平方向：如果右侧空间不足，放到左边
        if new_x + win_w > screen_x + screen_w - 10:
            new_x = x - win_w - 15

        # 检查垂直方向：使用当前窗口高度判断
        # 计算底部剩余空间
        bottom_space = screen_y + screen_h - new_y - 10
        if bottom_space < win_h:
            # 底部空间不够，尝试放在鼠标上方
            potential_y = y - win_h - 15
            if potential_y >= screen_y + 10:
                new_y = potential_y
            else:
                # 上方也放不下，贴着屏幕底部
                new_y = screen_y + screen_h - win_h - 10

        # 确保不超出左边界
        if new_x < screen_x + 10:
            new_x = screen_x + 10

        # 确保不超出上边界
        if new_y < screen_y + 10:
            new_y = screen_y + 10

        return (new_x, new_y)

    def show_at_mouse(self, mouse_pos=None, text=None):
        """在鼠标位置显示窗口并自动翻译（划词翻译模式）

        Args:
            mouse_pos: 鼠标位置元组 (x, y)，如果为 None 则使用当前鼠标位置
            text: 要翻译的文本，如果为 None 则使用输入框中的文本
        """
        if mouse_pos is None:
            mouse_pos = (QCursor.pos().x(), QCursor.pos().y())

        # 每次显示时重新加载主题和字体配置
        self.update_theme()

        # 如果窗口处于最小化状态，先恢复正常状态
        if self.isMinimized():
            self.showNormal()
            self._is_maximized = False
            self._maximize_btn.setText("□")

        # 重置窗口大小和高度状态
        self._reset_window_height()

        # 清空输入输出框，避免显示上次文本
        self._input_text.clear()
        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()
        self._streaming_text = ""
        # 强制立即刷新，确保清除在 show() 之前生效
        self._input_text.repaint()
        self._output_text.repaint()

        # 计算并移动到鼠标位置
        x, y = self._calculate_position(mouse_pos)
        self.move(x, y)
        self._input_text.setFocus()
        self.show()
        self.raise_()
        self.activateWindow()

        # 如果提供了文本，自动填充并翻译
        if text:
            self.auto_translate(text)

    def auto_translate(self, text: str):
        """自动翻译选中的文本

        Args:
            text: 要翻译的文本
        """
        if not text or not text.strip():
            return

        # 保存原文
        self._pending_original_text = text.strip()
        self._auto_mode = True

        # 填充输入框
        self._input_text.setPlainText(self._pending_original_text)

        # 清空输出框
        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()
        self._streaming_text = ""
        self._start_translation()

    def show_loading(self, original_text: str = None):
        """显示加载状态

        Args:
            original_text: 原文内容，如果提供则显示在输入框中
        """
        if original_text:
            self._input_text.setPlainText(original_text)
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()
        self._output_text.setPlainText("正在翻译...")

    def show_streaming_start(self, original_text: str = None):
        """开始流式翻译显示

        Args:
            original_text: 原文内容，如果提供则显示在输入框中
        """
        self._streaming_text = ""
        self._is_streaming = True  # 设置流式状态
        self._last_adjusted_height = 0  # 重置高度记录
        self._scrollbar_hidden = False  # 重置滚动条隐藏状态
        self._user_resized_during_streaming = False  # 重置用户手动调整标志
        self._char_queue.clear()  # 清空逐字输出缓冲区
        self._char_timer.stop()  # 停止逐字输出定时器
        self._pending_finish_callback = None  # 重置完成回调

        # 锁定原文框高度，防止流式输出期间 splitter 重新分配导致文字跳动
        self._lock_input_height()

        if original_text:
            self._input_text.setPlainText(original_text)

        self._output_text.clear()
        self._ensure_output_plain_mode()
        self._clear_polish_diff_snapshot()

        # 流式输出开始时隐藏滚动条（固定高度模式下不隐藏）
        if not self._fixed_height_mode:
            self._hide_output_scrollbar()

        # 启用按钮
        self._translate_btn.setEnabled(True)
        self._polishing_btn.setEnabled(True)
        self._summarize_btn.setEnabled(True)

    def append_translation_text(self, chunk: str):
        """追加流式翻译文本（通过逐字缓冲区输出）

        Args:
            chunk: 翻译文本片段
        """
        if not hasattr(self, '_streaming_text'):
            self._streaming_text = ""

        # 将 chunk 中的每个字符加入缓冲区
        self._char_queue.extend(chunk)

        # 启动逐字输出定时器（如果尚未启动）
        if not self._char_timer.isActive():
            self._char_timer.start()

    def finish_streaming(self):
        """完成流式翻译 - 刷新缓冲区中剩余字符后执行完成操作"""
        # 如果缓冲区还有字符，加速排空
        if self._char_queue:
            # 立即排空所有剩余字符
            remaining = ''.join(self._char_queue)
            self._char_queue.clear()
            self._char_timer.stop()
            self._streaming_text += remaining

            cursor = self._output_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(remaining)

        self._is_streaming = False
        # 清理定时器
        if self._height_adjust_timer:
            self._height_adjust_timer.stop()
            self._height_adjust_timer = None
        # 滚动到顶部
        self._input_text.verticalScrollBar().setValue(0)
        self._output_text.verticalScrollBar().setValue(0)
        # 最终高度调整和屏幕边界检查（固定高度模式下不调整）
        if not self._fixed_height_mode:
            QTimer.singleShot(100, self._final_height_adjust)

    def _final_height_adjust(self):
        """流式翻译结束后的最终高度调整"""
        try:
            # 在解锁前保存当前原文框高度，防止 _show_output_scrollbar 改变
            # stretch factor 后 Qt 布局系统重新分配导致原文框收缩
            current_sizes = self._splitter.sizes()
            saved_input_height = current_sizes[0] if current_sizes else 120
            saved_input_height = max(saved_input_height, 120)

            # 恢复滚动条显示（流式输出结束后）
            # _show_output_scrollbar 内部会同步恢复分割条的拉伸因子并解锁原文框高度
            self._show_output_scrollbar()
            self._scrollbar_hidden = False

            # _show_output_scrollbar 将 stretch factor 从 (0,0) 改为 (0,1)
            # 并解锁了原文框高度约束，这可能导致 Qt 布局系统重新分配 splitter 空间，
            # 使原文框从比例分配的高度收缩到最小高度 120px。
            # 立即重新设置 splitter 尺寸，锁定原文框高度不变。
            splitter_h = self._splitter.height()
            if splitter_h > 0:
                handle_width = self._splitter.handleWidth()
                output_height = splitter_h - saved_input_height - handle_width
                output_height = max(0, output_height)
                self._splitter.setSizes([saved_input_height, output_height])

            # 如果用户在流式期间手动调整过窗口大小，不再自动调整高度
            # 避免翻译完成后窗口"跳动"
            if self._user_resized_during_streaming:
                return

            # 计算最终所需高度
            target_height = self._calculate_required_height()
            # 立即调整高度（不使用动画）
            self._smooth_adjust_height(target_height, immediate=True)
        except RuntimeError:
            pass
        except Exception:
            pass

    def _get_current_screen_bounds(self) -> tuple:
        """获取窗口当前所在屏幕的可用区域

        Returns:
            tuple: (screen_x, screen_y, screen_w, screen_h)
        """
        try:
            # 优先使用窗口当前所在的屏幕
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                screen = QApplication.screenAt(self.pos())
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                return (geo.x(), geo.y(), geo.width(), geo.height())
        except Exception:
            pass
        return self._get_screen_bounds()

    def _calculate_required_height(self) -> int:
        """计算显示当前内容所需的窗口高度

        保持用户手动调整的原文框高度，只根据译文内容动态调整窗口高度
        使用动态 overhead 计算，避免硬编码常量遗漏边框等像素。

        Returns:
            所需的窗口高度（像素）
        """
        try:
            # 使用当前窗口所在屏幕
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            # 最大允许高度（屏幕高度的70%）
            max_height = int(screen_h * 0.7)

            from PyQt6.QtGui import QFontMetrics, QTextDocument

            # 动态计算 splitter 以外的开销（标题栏、控制栏、边距、边框等）
            splitter_h = self._splitter.height()
            if splitter_h > 0 and self.height() > splitter_h:
                overhead = self.height() - splitter_h
            else:
                overhead = 98  # fallback

            # 优先使用 viewport 宽度（最准确，反映实际排版宽度）
            viewport_width = self._output_text.viewport().width()
            if viewport_width > 50:
                output_width = viewport_width
            else:
                output_width = self.width() - 2 - 24 - 2 - 16
                output_width = max(200, output_width)

            # 计算输出文本高度
            output_font = self._output_text.font()
            output_text = self._output_text.toPlainText()

            if output_text:
                doc = QTextDocument()
                doc.setDefaultFont(output_font)
                doc.setTextWidth(output_width)
                doc.setPlainText(output_text)
                text_content_height = int(doc.size().height())
            else:
                text_content_height = 0

            # output_container 需要的高度 = 文本高度 + padding(8*2) + border(1*2)
            output_container_height = text_content_height + 18

            # 获取当前分割器尺寸
            current_sizes = self._splitter.sizes()
            input_height = current_sizes[0] if current_sizes else 100
            input_height = max(60, input_height)
            current_output = current_sizes[1] if len(current_sizes) > 1 else 180

            # 用当前输出容器实际大小作为下限（不缩小），而非固定 180
            # 当前容器可能 < 180（如窗口较小时），但内容已能完全显示
            output_container_height = max(current_output, output_container_height)

            handle_width = self._splitter.handleWidth()
            total_height = overhead + input_height + handle_width + output_container_height

            min_window_height = 400
            total_height = max(min_window_height, min(total_height, max_height))

            return total_height

        except Exception:
            return 400

    def _ensure_within_screen(self):
        """确保窗口完全在屏幕范围内"""
        try:
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            x, y = self.x(), self.y()
            w, h = self.width(), self.height()

            # 检查右边界
            if x + w > screen_x + screen_w:
                x = screen_x + screen_w - w
            # 检查下边界
            if y + h > screen_y + screen_h:
                y = screen_y + screen_h - h
            # 检查左边界
            if x < screen_x:
                x = screen_x
            # 检查上边界
            if y < screen_y:
                y = screen_y

            # 如果位置需要调整，则移动窗口
            if x != self.x() or y != self.y():
                self.move(x, y)

        except RuntimeError:
            pass
        except Exception:
            pass

    def _calculate_max_height_for_position(self) -> int:
        """根据当前窗口位置计算最大允许高度

        确保窗口不会超出屏幕下边界

        Returns:
            最大允许高度（像素）
        """
        try:
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            current_y = self.y()

            # 计算从当前位置到底部屏幕边界的可用空间
            available_height = screen_y + screen_h - current_y

            # 但也不能超过屏幕高度的70%
            max_by_screen_percent = int(screen_h * 0.7)

            return min(available_height, max_by_screen_percent)

        except Exception:
            return int(QApplication.primaryScreen().availableGeometry().height() * 0.7)

    def _smooth_adjust_height(self, target_height: int, immediate: bool = False):
        """平滑调整窗口高度

        在调整窗口高度时保持原文框高度不变，只改变译文框高度。
        当底部触及屏幕边界但整体高度未达到屏幕70%时，向上扩展窗口。

        Args:
            target_height: 目标高度
            immediate: 是否立即调整（不使用动画）
        """
        try:
            # 固定高度模式下不调整窗口高度
            if self._fixed_height_mode:
                return

            # 获取屏幕信息
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            max_height_by_percent = int(screen_h * 0.7)  # 屏幕高度70%限制

            # 首先根据窗口位置计算最大允许高度（确保不超出屏幕下边界）
            max_height_for_position = self._calculate_max_height_for_position()

            current_height = self.height()
            current_y = self.y()

            # 保存原始目标高度（用于判断是否内容超出了窗口容量）
            original_target_height = target_height

            # 判断是否需要向上扩展
            # 条件：1. 目标高度超过位置限制（底部触及屏幕边界）
            #      2. 当前高度小于屏幕70%限制
            #      3. 窗口上方有足够空间
            need_expand_upward = False
            new_window_y = current_y
            actual_expand = 0  # 记录实际向上扩展的高度

            if target_height > max_height_for_position and current_height < max_height_by_percent:
                # 计算需要向上移动的距离
                needed_extra = target_height - max_height_for_position
                # 上方可用空间
                top_space = current_y - screen_y

                if top_space > 10:
                    # 可以向上扩展
                    # 计算实际可扩展的高度（考虑上方空间和70%限制）
                    max_expand_upward = min(top_space, max_height_by_percent - current_height)
                    actual_expand = min(needed_extra, max_expand_upward)

                    if actual_expand > 5:
                        need_expand_upward = True
                        new_window_y = current_y - actual_expand
                        # 向上扩展后，实际可达到的高度
                        target_height = min(target_height, current_height + actual_expand)

            # 如果不需要向上扩展，则限制目标高度不超过位置限制
            if not need_expand_upward:
                target_height = min(target_height, max_height_for_position)

            # 判断窗口是否无法继续增长（达到屏幕70%或空间耗尽）
            # 直接检查文本是否溢出 viewport，避免 clamped target 导致检测失效
            content_exceeds_window = self._output_text.verticalScrollBar().maximum() > 0
            window_at_max_limit = current_height >= max_height_by_percent - 20 or (
                not need_expand_upward and target_height >= max_height_for_position - 20
            )
            if content_exceeds_window and window_at_max_limit and self._scrollbar_hidden:
                self._show_output_scrollbar()
                self._scrollbar_hidden = False
                # 滚动条刚变为可见，滚到底部显示最新内容
                if self._is_streaming:
                    self._output_text.verticalScrollBar().setValue(
                        self._output_text.verticalScrollBar().maximum()
                    )

            # 如果高度差异太小，不调整
            if abs(target_height - current_height) < 5 and not need_expand_upward:
                return

            # 如果目标高度比当前高度小很多（超过20px），才缩小
            # 这样可以避免小幅度的抖动，但允许窗口增长
            if target_height < current_height - 20 and not need_expand_upward:
                return

            self._last_adjusted_height = target_height

            # 原文框默认高度（初始化时设置的值）
            DEFAULT_INPUT_HEIGHT = 120

            # 在流式输出过程中，使用固定的输入框高度（避免分割条跳动）
            if self._is_streaming and hasattr(self, '_streaming_input_height'):
                current_input_height = self._streaming_input_height
            else:
                # 非流式输出时，获取当前原文框高度（用户可能手动调整过）
                current_sizes = self._splitter.sizes()
                current_input_height = current_sizes[0] if current_sizes else DEFAULT_INPUT_HEIGHT

            # 确保原文框高度不低于默认高度，防止窗口调整时原文框被压缩
            current_input_height = max(current_input_height, DEFAULT_INPUT_HEIGHT)

            # 动态计算 splitter 以外的开销，与 _calculate_required_height 保持一致
            splitter_h = self._splitter.height()
            if splitter_h > 0 and self.height() > splitter_h:
                overhead = self.height() - splitter_h
            else:
                overhead = 98  # fallback

            handle_width = self._splitter.handleWidth()
            target_output_height = target_height - overhead - current_input_height - handle_width
            target_output_height = max(0, target_output_height)

            if immediate or not self.isVisible():
                # 先设置 splitter 尺寸，再 resize，避免 resize 时 Qt 按比例重新分配导致原文框缩小
                self._splitter.setSizes([current_input_height, target_output_height])
                self.resize(self.width(), target_height)
                # resize 后再次确保 splitter 尺寸正确（防止 Qt 自动调整）
                self._splitter.setSizes([current_input_height, target_output_height])
                # 如果需要向上扩展，移动窗口位置
                if need_expand_upward:
                    self.move(self.x(), new_window_y)
                # 确保窗口在屏幕范围内
                self._ensure_within_screen()
                return

            # 使用动画平滑调整
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QSize

            if self._height_animation is None:
                self._height_animation = QPropertyAnimation(self, b"size")
                self._height_animation.setDuration(150)
                self._height_animation.setEasingCurve(QEasingCurve.Type.OutQuad)

            # 检查动画是否正在运行
            animation_running = self._height_animation.state() == QPropertyAnimation.State.Running

            # 如果动画正在运行
            if animation_running:
                # 获取当前动画的目标高度
                current_anim_target = self._height_animation.endValue().height()
                height_diff = abs(target_height - current_anim_target)

                # 如果需要向上扩展，必须立即移动窗口位置，并更新动画目标
                if need_expand_upward:
                    self.move(self.x(), new_window_y)
                    # 更新动画目标值（从当前位置继续动画到新目标）
                    self._height_animation.setEndValue(QSize(self.width(), target_height))
                    return

                # 如果差异小于30px且不需要向上扩展，跳过本次调整，让动画继续
                if height_diff < 30:
                    return
                # 差异较大，停止动画重新开始
                self._height_animation.stop()

            current_size = self.size()
            target_size = QSize(self.width(), target_height)

            # 流式输出期间，两个面板都不拉伸，避免 QPropertyAnimation 逐帧 resize 时
            # Qt 按 stretch factor 重新分配 splitter 空间导致文字上下跳动
            self._splitter.setStretchFactor(0, 0)  # input 不拉伸
            self._splitter.setStretchFactor(1, 0)  # output 也不拉伸（流式期间）

            # 设置 splitter 尺寸
            self._splitter.setSizes([current_input_height, target_output_height])

            # 如果需要向上扩展，先移动窗口位置
            if need_expand_upward:
                self.move(self.x(), new_window_y)

            self._height_animation.setStartValue(current_size)
            self._height_animation.setEndValue(target_size)
            self._height_animation.start()

            # 动画完成后：恢复 stretch factor 并确保分割条正确
            def on_animation_done():
                try:
                    # 流式输出结束后，恢复译文框的拉伸因子，让后续 resize 时译文框可自适应
                    if not self._is_streaming:
                        self._splitter.setStretchFactor(1, 1)
                    self._splitter.setSizes([current_input_height, target_output_height])
                    self._ensure_within_screen()
                except:
                    pass
            QTimer.singleShot(200, on_animation_done)

        except RuntimeError:
            pass
        except Exception:
            try:
                self.resize(self.width(), target_height)
                self._ensure_within_screen()
            except:
                pass

    def _schedule_height_adjust(self):
        """调度高度调整（延迟执行，避免频繁更新）"""
        try:
            if self._height_adjust_timer is not None and self._height_adjust_timer.isActive():
                return

            from PyQt6.QtCore import QTimer
            if self._height_adjust_timer is None:
                self._height_adjust_timer = QTimer(self)
                self._height_adjust_timer.setSingleShot(True)
                self._height_adjust_timer.timeout.connect(self._do_height_adjust)

            self._height_adjust_timer.start(50)

        except RuntimeError:
            pass

    def _do_height_adjust(self):
        """执行高度调整"""
        try:
            if not self._is_streaming or not self.isVisible():
                return

            # 如果用户手动调整了窗口大小，不再自动增长高度
            # 新内容到达时保持当前窗口大小，用户通过滚动条查看
            if self._user_resized_during_streaming:
                return

            target_height = self._calculate_required_height()

            # 获取屏幕信息，用于判断是否达到70%限制
            screen_x, screen_y, screen_w, screen_h = self._get_current_screen_bounds()
            max_height_by_percent = int(screen_h * 0.7)

            current_height = self.height()

            # 判断窗口是否达到高度上限（屏幕70%限制或位置限制）
            # 窗口无法继续增长且内容溢出时，显示滚动条让用户滚动查看内容
            max_height_for_position = self._calculate_max_height_for_position()
            window_at_limit = (
                current_height >= max_height_by_percent - 10 or
                current_height >= max_height_for_position - 10
            )
            content_needs_more_space = self._output_text.verticalScrollBar().maximum() > 0

            if window_at_limit and content_needs_more_space and self._scrollbar_hidden:
                self._show_output_scrollbar()
                self._scrollbar_hidden = False
                # 滚动条刚变为可见（窗口无法继续增长），滚到底部显示最新内容
                self._output_text.verticalScrollBar().setValue(
                    self._output_text.verticalScrollBar().maximum()
                )

            # 流式期间使用立即 resize（不用动画），内容是增量到达的，
            # 每次增长几像素，本身就足够平滑，动画反而会导致 splitter 跳动
            self._smooth_adjust_height(target_height, immediate=True)

            # 确保窗口在屏幕范围内
            self._ensure_within_screen()

        except RuntimeError:
            pass

    def _reset_window_height(self):
        """重置窗口高度到默认值（固定高度模式下不调整尺寸）"""
        try:
            self._last_adjusted_height = 0
            self._is_streaming = False
            self._scrollbar_hidden = False
            self._user_resized_during_streaming = False
            self._user_manually_resized = False  # 重置手动调整标志

            if self._height_adjust_timer:
                self._height_adjust_timer.stop()
                self._height_adjust_timer = None

            from PyQt6.QtCore import QPropertyAnimation
            if self._height_animation and self._height_animation.state() == QPropertyAnimation.State.Running:
                self._height_animation.stop()

            # 恢复滚动条显示
            self._show_output_scrollbar()

            # 根据模式重置窗口尺寸
            if self._fixed_height_mode:
                self.setMinimumSize(450, 660)
                self.resize(500, 660)
            elif self._remember_window_size and self._saved_window_size is not None:
                # 记忆窗口大小模式下，应用保存的大小
                self.setMinimumSize(450, 450)
                self.resize(self._saved_window_size)
            else:
                self.resize(500, 400)

            # 确保窗口在屏幕范围内
            self._ensure_within_screen()

        except RuntimeError:
            pass

    def show_result(self, result):
        """显示翻译结果（非流式）

        Args:
            result: TranslationResult 对象
        """
        if result.error:
            self._ensure_output_plain_mode()
            self._clear_polish_diff_snapshot()
            self._output_text.setPlainText(f"翻译失败: {result.error}")
        else:
            self._input_text.setPlainText(result.original_text)
            self._ensure_output_plain_mode()
            self._clear_polish_diff_snapshot()
            self._output_text.setPlainText(result.translated_text)

    def _window_overlaps_any_screen(self) -> bool:
        """当前窗口几何是否与任意一块屏幕有交集（用于过滤离屏预渲染等无效坐标）。"""
        try:
            g = self.frameGeometry()
            # 取中心与四角任一点命中屏幕即可（覆盖跨屏与普通窗口）
            candidates = (
                QPoint(g.center().x(), g.center().y()),
                QPoint(g.left(), g.top()),
                QPoint(g.right(), g.top()),
                QPoint(g.left(), g.bottom()),
                QPoint(g.right(), g.bottom()),
            )
            for p in candidates:
                if QApplication.screenAt(p) is not None:
                    return True
            return False
        except Exception:
            return True

    def hide(self):
        """隐藏窗口"""
        # 记忆窗口位置：在隐藏前保存当前位置（跳过完全离屏的假位置，例如启动时离屏预渲染）
        if self._remember_window_position and self._window_overlaps_any_screen():
            self._saved_window_pos = self.pos()
        
        # 记忆窗口大小：只在用户手动调整过窗口大小时才保存
        # 流式输出自动变大的高度不计入保存
        if self._remember_window_size and self._user_manually_resized:
            current_size = self.size()
            self._saved_window_size = current_size
            # 保存到配置文件
            try:
                get_config().set('translator_window.last_window_width', current_size.width())
                get_config().set('translator_window.last_window_height', current_size.height())
                get_config().save()
            except Exception:
                pass  # 静默失败，不影响功能
        
        # 重置手动调整标志
        self._user_manually_resized = False

        # 重置自动翻译模式状态
        self._auto_mode = False
        self._pending_original_text = ""

        super().hide()
        self.closed.emit()

    def is_auto_mode(self) -> bool:
        """检查是否处于自动翻译模式"""
        return self._auto_mode

    def get_pending_text(self) -> str:
        """获取待翻译的原文"""
        return self._pending_original_text

    def _hide_output_scrollbar(self):
        """隐藏译文框滚动条（流式输出开始时）"""
        try:
            theme = get_theme(self._theme_style)
            # 使用隐藏滚动条的样式
            self._output_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {theme['bg_secondary']};
                    color: {theme['text_primary']};
                    border: 1px solid {theme['border_color']};
                    border-radius: 4px;
                    padding: 8px;
                    font-family: {self._FONT_FAMILY_CSS};
                    font-size: {self._font_size}px;
                }}
                {get_hidden_scrollbar_style(theme)}
            """)
            self._scrollbar_hidden = True
        except RuntimeError:
            pass
        except Exception:
            pass

    def _show_output_scrollbar(self):
        """显示译文框滚动条（流式输出结束后）"""
        try:
            theme = get_theme(self._theme_style)
            # 恢复正常的滚动条样式
            self._output_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {theme['bg_secondary']};
                    color: {theme['text_primary']};
                    border: 1px solid {theme['border_color']};
                    border-radius: 4px;
                    padding: 8px;
                    font-family: {self._FONT_FAMILY_CSS};
                    font-size: {self._font_size}px;
                }}
                {get_scrollbar_style(theme)}
            """)
            self._scrollbar_hidden = False

            # 流式输出结束后，恢复原文框高度约束和分割条拉伸因子
            if not self._is_streaming:
                self._unlock_input_height()
                self._splitter.setStretchFactor(0, 0)  # 原文框不拉伸
                self._splitter.setStretchFactor(1, 1)  # 译文框拉伸
        except RuntimeError:
            pass
        except Exception:
            pass

    def _lock_input_height(self):
        """锁定原文框高度（流式输出开始时）

        通过 setFixedHeight 让 QSplitter 无法改变原文框的高度，
        从而避免窗口 resize 时 splitter 重新分配空间导致文字跳动。
        使用 splitter 当前分配的实际高度，不强制最小值，
        避免与窗口尺寸约束冲突导致不必要的窗口增长。
        """
        try:
            current_sizes = self._splitter.sizes()
            input_height = current_sizes[0] if current_sizes else 120
            self._streaming_input_height = input_height

            # setFixedHeight 同时设置 min 和 max，splitter 物理上无法改变它
            self._input_text.setFixedHeight(input_height)

            # 同时设置 stretch factor，双重保护
            self._splitter.setStretchFactor(0, 0)
            self._splitter.setStretchFactor(1, 0)
        except RuntimeError:
            pass

    def _unlock_input_height(self):
        """解除原文框高度锁定（流式输出结束后）

        恢复原文框的 min/max 高度约束，让用户可以手动拖动分割条。
        恢复约束后再设置 splitter 尺寸，避免 setFixedHeight 把最小高度卡在
        流式开始时的高度，导致后续分割线无法向上拖动。
        """
        try:
            input_min_height = 180 if self._fixed_height_mode else 120
            current_sizes = self._splitter.sizes()
            current_height = current_sizes[0] if current_sizes else self._input_text.height()
            output_height = current_sizes[1] if len(current_sizes) > 1 else self._output_container.height()

            # setFixedHeight 同时设置 min/max。解锁时必须显式恢复 max 和 min，
            # 不能再次调用 setFixedHeight，否则 min 会被固定到 current_height。
            self._input_text.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            self._input_text.setMinimumHeight(input_min_height)

            # 保持当前视觉高度不跳变，同时让用户之后可以继续拖动分割线。
            self._splitter.setSizes([current_height, output_height])
        except RuntimeError:
            pass

    def _on_user_resize_during_streaming(self):
        """用户在流式翻译期间手动调整了窗口大小

        当用户手动调整窗口大小（拖动边缘或最大化/还原）时：
        1. 标记用户已手动调整，停止自动高度增长
        2. 立即显示滚动条，让用户可以滚动查看溢出的内容
        3. 保持流式翻译继续运行，新内容到达时不再调整窗口高度
        4. 翻译完成时也不再调整窗口高度，避免"跳动"
        """
        try:
            # 标记用户手动调整了窗口大小
            self._user_resized_during_streaming = True

            # 停止正在进行的高度调整动画
            from PyQt6.QtCore import QPropertyAnimation
            if self._height_animation and self._height_animation.state() == QPropertyAnimation.State.Running:
                self._height_animation.stop()

            # 停止高度调整定时器
            if self._height_adjust_timer:
                self._height_adjust_timer.stop()
                self._height_adjust_timer = None

            # 立即显示滚动条
            if self._scrollbar_hidden:
                self._show_output_scrollbar()
                self._scrollbar_hidden = False
        except RuntimeError:
            pass
        except Exception:
            pass


# 全局翻译窗口实例
_translator_window_instance: Optional[TranslatorWindow] = None


def get_translator_window() -> TranslatorWindow:
    """获取全局翻译窗口实例"""
    global _translator_window_instance
    if _translator_window_instance is None:
        _translator_window_instance = TranslatorWindow()
    return _translator_window_instance
