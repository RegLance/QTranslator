"""单词查询浮动弹窗模块 — 选中英文单词时显示发音、释义与收藏入口。"""
from __future__ import annotations

import re
import sys
import time as _time
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QApplication,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QObject, QPointF, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QBrush, QPixmap, QPolygonF, QIcon
import math

try:
    from ..core.phonetic import lookup_dual_ipa
    from ..core.translator import get_translator
    from ..utils.vocabulary import get_vocabulary
    from ..utils.theme import get_theme
    from ..utils.tts import get_tts
    from ..utils.tts_speak_indicator import TtsSpeakPrepareIndicator
    from ..config import get_config
except ImportError:
    from src.core.phonetic import lookup_dual_ipa
    from src.core.translator import get_translator
    from src.utils.vocabulary import get_vocabulary
    from src.utils.theme import get_theme
    from src.utils.tts import get_tts
    from src.utils.tts_speak_indicator import TtsSpeakPrepareIndicator
    from src.config import get_config

# 英文单词判定正则
_WORD_RE = re.compile(r"^[a-zA-Z]+(?:[''][a-zA-Z]+)?$")


def is_english_word(text: str) -> bool:
    """检查文本是否是一个英文单词（不含空格、纯字母，允许缩写如 don't）。"""
    return bool(_WORD_RE.match(text.strip()))


class _DictLookupWorker(QThread):
    """后台词典查询线程（使用翻译 API 以词典模式查询）。"""

    result_ready = pyqtSignal(str, int)  # 释义文本, 代数
    lookup_error = pyqtSignal(str, int)  # 错误信息, 代数

    def __init__(self, word: str, generation: int):
        super().__init__()
        self._word = word
        self._generation = generation
        self._cancelled = False

    def cancel(self):
        """标记为已取消（不强行 terminate，让线程自己结束）。"""
        self._cancelled = True

    def run(self):
        try:
            translator = get_translator()
            if self._cancelled:
                return
            result = translator.translate_sync(
                self._word, target_language="中文", auto_detect=True
            )
            if self._cancelled:
                return

            if result and result.translated_text:
                text = result.translated_text.strip()
                if text and text != self._word:
                    lines = [l.strip() for l in text.split('\n') if l.strip()]

                    # 按段落解析：释义 / 形态变化 / 速记
                    definition_lines = []
                    forms_line = ""
                    mnemonic_lines = []
                    section = "def"  # def / forms / mnemonic

                    for line in lines:
                        if line.startswith('例句') or line.startswith('词源'):
                            continue
                        if line.startswith('形态变化'):
                            section = "forms"
                            forms_line = line[len('形态变化'):].strip().lstrip('：:').strip()
                            continue
                        if line.startswith('速记'):
                            section = "mnemonic"
                            mnemonic_line = line[len('速记'):].strip().lstrip('：:').strip()
                            if mnemonic_line:
                                mnemonic_lines.append(mnemonic_line)
                            continue

                        if section == "def":
                            if line.startswith('[') or any(
                                line.startswith(f'{pos}.') or line.startswith(f'{pos} ')
                                for pos in ['n', 'v', 'adj', 'adv', 'prep', 'conj', 'pron',
                                            'int', 'interj', 'det', 'art', 'num', 'aux']
                            ):
                                definition_lines.append(line)
                        elif section == "forms":
                            if line.strip() and ':' in line:
                                forms_line = line.strip()
                        elif section == "mnemonic":
                            mnemonic_lines.append(line)

                    if self._cancelled:
                        return

                    definition = '\n'.join(definition_lines) if definition_lines else ""
                    if not definition:
                        short = '\n'.join(lines[:4]) if len(lines) > 4 else '\n'.join(lines)
                        definition = short

                    # 用 ||| 分隔三个部分传给 UI
                    parts = [definition, forms_line, '\n'.join(mnemonic_lines).strip()]
                    self.result_ready.emit('|||'.join(parts), self._generation)
                else:
                    self.lookup_error.emit("未查到释义", self._generation)
            else:
                self.lookup_error.emit("未查到释义", self._generation)
        except Exception as e:
            if not self._cancelled:
                self.lookup_error.emit(str(e), self._generation)


class WordPopup(QFrame):
    """单词查询浮动弹窗 — 无边框、圆角、带阴影，点外部自动消失。

    使用方式：
        popup = WordPopup(parent_window)
        popup.show_at(word, global_pos, text_edit_widget)
    """

    _MIN_WIDTH = 220
    _MAX_WIDTH = 360

    # 跨线程安全关闭信号（供 Windows 钩子回调使用）
    _request_close = pyqtSignal()

    # 收藏状态变更信号（供外部窗口同步按钮状态）
    collection_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("WordPopup")

        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._theme = get_theme(self._theme_style)

        self._word: str = ""
        self._definition: str = ""
        self._phonetic: str = ""
        self._is_collected: bool = False

        # 用于点击外部检测
        self._text_edit_widget: Optional[QWidget] = None

        # 词典查询工作线程
        self._lookup_worker: Optional[_DictLookupWorker] = None

        # 查询代数：每次发起新查询时递增，回调用它忽略过期结果
        self._lookup_generation: int = 0

        # show_at 后的宽限期（秒级时间戳）：宽限期内不响应外部点击关闭
        # 防止用户划词选中新单词时的点击操作误关弹窗
        self._grace_until: float = 0.0

        # 跨线程关闭信号 → 主线程安全执行 hide_popup
        self._request_close.connect(self.hide_popup)

        self._setup_ui()
        self._apply_theme()

        # 朗读准备指示器（延迟初始化，因为 _speak_btn 在 _setup_ui 中创建）
        self._tts_speak_prep = TtsSpeakPrepareIndicator(
            self,
            self._speak_btn,
            lambda: get_theme(get_config().get('theme.popup_style', 'dark')),
            self._create_speak_icon,
        )

        # 跟随全局主题变更
        try:
            from ..utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self.update_theme)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self):
        """构建弹窗 UI 结构。"""
        # 关键：不使用 WA_ShowWithoutActivating，让窗口可以接收焦点。
        # 这样当用户点击弹窗外部时，系统会发送 ActivationChange 事件，
        # 弹窗在 changeEvent 中检测到失活后自动关闭。
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MouseTracking)
        # 允许接收焦点（确保 ActivationChange 能正常触发）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        # ---- 外框 ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._content = QFrame()
        self._content.setObjectName("wordPopupContent")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(14, 12, 14, 10)
        content_layout.setSpacing(6)

        # === 第一行：单词 + 收藏星标 ===
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self._word_label = QLabel()
        self._word_label.setObjectName("wordLabel")
        self._word_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._word_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        font = QFont()
        font.setFamilies(["Microsoft YaHei", "Segoe UI", "sans-serif"])
        font.setPointSize(16)
        font.setBold(True)
        self._word_label.setFont(font)
        header_row.addWidget(self._word_label, 1)

        self._collect_btn = QPushButton()
        self._collect_btn.setObjectName("popupCollectBtn")
        self._collect_btn.setFixedSize(30, 30)
        self._collect_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._collect_btn.setToolTip("收藏到单词本")
        self._collect_btn.clicked.connect(self._on_collect)
        header_row.addWidget(self._collect_btn)

        # 朗读按钮
        self._speak_btn = QPushButton()
        self._speak_btn.setObjectName("popupSpeakBtn")
        self._speak_btn.setFixedSize(30, 30)
        self._speak_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._speak_btn.setToolTip("朗读发音")
        self._speak_btn.setIcon(self._create_speak_icon())
        self._speak_btn.clicked.connect(self._on_speak)
        header_row.addWidget(self._speak_btn)

        content_layout.addLayout(header_row)

        # === 发音行 ===
        self._phonetic_label = QLabel()
        self._phonetic_label.setObjectName("phoneticLabel")
        phon_font = QFont()
        phon_font.setFamilies(["Microsoft YaHei", "Segoe UI", "sans-serif"])
        phon_font.setPointSize(12)
        self._phonetic_label.setFont(phon_font)
        self._phonetic_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._phonetic_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        content_layout.addWidget(self._phonetic_label)

        # === 分割线 ===
        self._separator = QFrame()
        self._separator.setObjectName("popupSeparator")
        self._separator.setFixedHeight(1)
        self._separator.setFrameShape(QFrame.Shape.HLine)
        content_layout.addWidget(self._separator)

        # === 释义区域 ===
        self._definition_label = QLabel()
        self._definition_label.setObjectName("definitionLabel")
        self._definition_label.setWordWrap(True)
        self._definition_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._definition_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._definition_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        def_font = QFont()
        def_font.setFamilies(["Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"])
        def_font.setPointSize(12)
        self._definition_label.setFont(def_font)
        content_layout.addWidget(self._definition_label)

        # === 形态变化 ===
        self._forms_label = QLabel()
        self._forms_label.setObjectName("formsLabel")
        self._forms_label.setWordWrap(True)
        self._forms_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._forms_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        forms_font = QFont()
        forms_font.setFamilies(["Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"])
        forms_font.setPointSize(11)
        self._forms_label.setFont(forms_font)
        content_layout.addWidget(self._forms_label)
        self._forms_label.hide()

        # === 速记法则 ===
        self._mnemonic_label = QLabel()
        self._mnemonic_label.setObjectName("mnemonicLabel")
        self._mnemonic_label.setWordWrap(True)
        self._mnemonic_label.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        self._mnemonic_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        mnem_font = QFont()
        mnem_font.setFamilies(["Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"])
        mnem_font.setPointSize(11)
        self._mnemonic_label.setFont(mnem_font)
        content_layout.addWidget(self._mnemonic_label)
        self._mnemonic_label.hide()

        # === 加载提示（查询中显示） ===
        self._loading_label = QLabel("查询中…")
        self._loading_label.setObjectName("loadingLabel")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_font = QFont()
        load_font.setFamilies(["Microsoft YaHei", "sans-serif"])
        load_font.setPointSize(11)
        self._loading_label.setFont(load_font)
        content_layout.addWidget(self._loading_label)
        self._loading_label.hide()

        layout.addWidget(self._content)

    def _create_star_icon(self, filled: bool) -> QIcon:
        """绘制收藏星标图标。"""
        sz = 24
        pixmap = QPixmap(sz, sz)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        accent = QColor(self._theme.get("accent_color", "#4a9eff"))
        muted = QColor(self._theme.get("text_muted", "#888888"))

        cx, cy = sz / 2.0, sz / 2.0
        r = 7.0
        points = []
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.42
            points.append(QPointF(cx + rr * math.cos(ang), cy - rr * math.sin(ang)))
        poly = QPolygonF(points)

        pen_join = Qt.PenJoinStyle.RoundJoin
        if filled:
            painter.setBrush(accent)
            painter.setPen(QPen(accent, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, pen_join))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(muted, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, pen_join))

        painter.drawPolygon(poly)
        painter.end()

        icon = QIcon(pixmap)
        for mode in (QIcon.Mode.Disabled, QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(pixmap, mode, QIcon.State.Off)
        return icon

    def _create_speak_icon(self, theme: Optional[dict] = None) -> QIcon:
        """创建朗读图标（播放三角形）。

        Args:
            theme: 主题字典，为 None 时使用当前弹窗主题。
        """
        t = theme if theme is not None else self._theme
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        icon_color = QColor(t.get('text_muted', '#888888'))
        painter.setBrush(icon_color)
        painter.setPen(Qt.PenStyle.NoPen)
        triangle = [
            QPointF(6, 4),
            QPointF(6, 16),
            QPointF(17, 10),
        ]
        painter.drawPolygon(*triangle)
        painter.end()
        icon = QIcon(pixmap)
        for mode in (QIcon.Mode.Disabled, QIcon.Mode.Active, QIcon.Mode.Selected):
            icon.addPixmap(pixmap, mode, QIcon.State.Off)
        return icon

    def _on_speak(self):
        """朗读当前单词。"""
        if not self._word:
            return
        tts = get_tts()
        if tts.is_speaking() or self._tts_speak_prep.is_preparing():
            tts.stop()
            self._tts_speak_prep.end_prepare()
            return
        self._tts_speak_prep.attach_to_tts_engine(tts)
        ok = tts.speak(self._word, lang_hint="英文")
        if ok:
            self._tts_speak_prep.start_prepare()
        else:
            self._tts_speak_prep.end_prepare()

    def update_theme(self):
        """响应全局主题变更。"""
        self._theme_style = get_config().get('theme.popup_style', 'dark')
        self._theme = get_theme(self._theme_style)
        self._apply_theme()
        self._tts_speak_prep.sync_theme_icons()

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------

    def _apply_theme(self):
        """应用主题样式。"""
        t = self._theme

        self._content.setStyleSheet(f"""
            QFrame#wordPopupContent {{
                background-color: {t['bg_color']};
                border-radius: 10px;
                border: 1px solid {t['border_color']};
            }}

            QLabel#wordLabel {{
                color: {t['text_primary']};
                background: transparent;
            }}

            QLabel#phoneticLabel {{
                color: {t.get('accent_color', '#4a9eff')};
                background: transparent;
            }}

            QFrame#popupSeparator {{
                background-color: {t['border_color']};
                border: none;
            }}

            QLabel#definitionLabel {{
                color: {t['text_secondary']};
                background: transparent;
            }}

            QLabel#formsLabel {{
                color: {t['text_secondary']};
                background: transparent;
            }}

            QLabel#mnemonicLabel {{
                color: {t.get('success_color', '#4caf50')};
                background: transparent;
            }}

            QLabel#loadingLabel {{
                color: {t['text_muted']};
                background: transparent;
            }}

            QPushButton#popupCollectBtn {{
                background-color: transparent;
                border: none;
                border-radius: 15px;
            }}
            QPushButton#popupCollectBtn:hover {{
                background-color: {t['button_hover']};
            }}

            QPushButton#popupSpeakBtn {{
                background-color: transparent;
                border: none;
                border-radius: 15px;
            }}
            QPushButton#popupSpeakBtn:hover {{
                background-color: {t['button_hover']};
            }}
        """)

        self._collect_btn.setIcon(self._create_star_icon(self._is_collected))
        self._speak_btn.setIcon(self._create_speak_icon())

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def show_at(self, word: str, global_pos: QPoint, text_edit: QWidget):
        """在指定位置显示单词弹窗。每次调用立即刷新为最新单词。"""

        new_word = word.strip()
        if new_word == self._word and self.isVisible():
            return

        # === 第 1 步：立即停止旧的一切 ===
        self._cancel_lookup()

        # === 第 2 步：原子更新全部 UI 状态 ===
        self._word = new_word
        self._text_edit_widget = text_edit
        self._word_label.setText(self._word)

        phonetic = lookup_dual_ipa(self._word)
        self._phonetic = phonetic or ""
        if self._phonetic:
            self._phonetic_label.setText(self._phonetic)
            self._phonetic_label.show()
        else:
            self._phonetic_label.hide()

        voc = get_vocabulary()
        self._is_collected = voc.is_collected(self._word)
        self._collect_btn.setIcon(self._create_star_icon(self._is_collected))

        self._definition_label.setText("")
        self._forms_label.hide()
        self._mnemonic_label.hide()
        self._loading_label.show()

        # === 第 3 步：主题 & 尺寸 & 定位 ===
        self._apply_theme()
        self.adjustSize()
        w = max(self._MIN_WIDTH, min(self.sizeHint().width(), self._MAX_WIDTH))
        self.setFixedWidth(w)
        self.adjustSize()
        self._position_popup(global_pos)

        # === 第 4 步：显示并立即绘制 ===
        self.setWindowOpacity(0.95)
        if not self.isVisible():
            self.show()
        else:
            self.repaint()  # 已可见时强制重绘，确保新单词立即可见
        self.raise_()

        # 开启 500ms 宽限期：其间不响应外部点击关闭
        # 防止用户划词选中新单词时，第一步（点击文本框）误关弹窗
        self._grace_until = _time.time() + 0.5

        # === 第 5 步：后台查询释义（UI 已显示新单词和「查询中…」） ===
        self._start_lookup()

    def _cancel_lookup(self):
        """取消进行中的词典查询（世代递增，旧回调自动丢弃）。"""
        if self._lookup_worker is not None:
            old = self._lookup_worker
            self._lookup_worker = None
            try:
                old.result_ready.disconnect()
                old.lookup_error.disconnect()
            except (TypeError, RuntimeError):
                pass
            old.cancel()
        self._lookup_generation += 1  # 所有旧信号携带的代数都不再匹配

    def _position_popup(self, anchor_pos: QPoint):
        """根据锚点位置计算弹窗显示位置，确保不超出屏幕边界。"""
        screen = QApplication.screenAt(anchor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            self.move(anchor_pos)
            return

        screen_geo = screen.availableGeometry()
        popup_w = self.width()
        popup_h = self.height()

        # 默认放在锚点下方偏左
        x = anchor_pos.x()
        y = anchor_pos.y() + 8  # 下方 8px 间距

        # 水平边界检查
        if x + popup_w > screen_geo.right():
            x = screen_geo.right() - popup_w - 4
        if x < screen_geo.left():
            x = screen_geo.left() + 4

        # 垂直边界检查：如果下方放不下，放到上方
        if y + popup_h > screen_geo.bottom():
            y = anchor_pos.y() - popup_h - 8
        if y < screen_geo.top():
            y = screen_geo.top() + 4

        self.move(x, y)

    # ------------------------------------------------------------------
    # 词典查询
    # ------------------------------------------------------------------

    def _start_lookup(self):
        """启动后台词典查询（新 worker 携带当前代数）。"""
        gen = self._lookup_generation
        self._lookup_worker = _DictLookupWorker(self._word, gen)
        self._lookup_worker.result_ready.connect(self._on_definition_ready)
        self._lookup_worker.lookup_error.connect(self._on_lookup_error)
        self._lookup_worker.start()

    def _on_definition_ready(self, text: str, generation: int):
        """词典查询成功（generation 由 worker 信号携带，用于忽略过期结果）。"""
        if generation != self._lookup_generation:
            return

        # 解析三部分：释义 ||| 形态变化 ||| 速记
        parts = text.split('|||')
        definition = parts[0].strip() if len(parts) > 0 else ""
        forms = parts[1].strip() if len(parts) > 1 else ""
        mnemonic = parts[2].strip() if len(parts) > 2 else ""

        self._definition = definition
        self._loading_label.hide()
        self._definition_label.setText(self._definition)

        if forms:
            self._forms_label.setText(f"📝 {forms}")
            self._forms_label.show()
        else:
            self._forms_label.hide()

        if mnemonic:
            self._mnemonic_label.setText(f"💡 {mnemonic}")
            self._mnemonic_label.show()
        else:
            self._mnemonic_label.hide()

        self.adjustSize()
        w = max(self._MIN_WIDTH, min(self.sizeHint().width(), self._MAX_WIDTH))
        self.setFixedWidth(w)
        self.adjustSize()
        if self.isVisible():
            self._position_popup(self.pos() + QPoint(0, 0))

    def _on_lookup_error(self, error_msg: str, generation: int):
        """词典查询失败（generation 由 worker 信号携带，用于忽略过期结果）。"""
        if generation != self._lookup_generation:
            return
        self._loading_label.hide()
        self._definition_label.setText(f"(查询失败: {error_msg})")
        self.adjustSize()
        w = max(self._MIN_WIDTH, min(self.sizeHint().width(), self._MAX_WIDTH))
        self.setFixedWidth(w)

    # ------------------------------------------------------------------
    # 收藏操作
    # ------------------------------------------------------------------

    def _on_collect(self):
        """收藏 / 取消收藏当前单词。"""
        if not self._word:
            return
        voc = get_vocabulary()
        try:
            if voc.is_collected(self._word):
                voc.remove_item(self._word)
                self._is_collected = False
            else:
                voc.put_item(self._word, self._definition)
                self._is_collected = True
            self._collect_btn.setIcon(self._create_star_icon(self._is_collected))
            self.collection_changed.emit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 点击外部自动关闭（多层兜底策略）
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        """弹窗内部点击不关闭。"""
        super().mousePressEvent(event)

    def changeEvent(self, event):
        """窗口失活（焦点转移到其他窗口）→ 关闭弹窗。"""
        if event.type() == event.Type.ActivationChange:
            if not self.isActiveWindow():
                # 延迟一小段时间，让弹窗内按钮的 click 信号先触发
                QTimer.singleShot(100, self._check_and_hide)
        super().changeEvent(event)

    def _check_and_hide(self):
        """确认窗口仍不活跃则关闭。"""
        if self.isVisible() and not self.isActiveWindow():
            self.hide_popup()

    @staticmethod
    def install_global_click_filter(popup_ref: list):
        """安装多层「点击外部关闭」监听。

        层级说明：
        1. QApplication 事件过滤器 — 捕获 Qt 内部的鼠标点击
        2. Windows 原生消息钩子 — 捕获 Qt 感知不到的点击（标题栏、桌面等）
        """
        # ---- Layer 1: Qt 应用级事件过滤器 ----
        class _PopupClickFilter(QObject):
            def eventFilter(self, obj, event):
                popup = popup_ref[0] if popup_ref else None
                if popup is None or not popup.isVisible():
                    return False

                if event.type() in (event.Type.MouseButtonPress, event.Type.MouseButtonRelease):
                    # 宽限期内不响应外部点击（show_at 刚更新过弹窗）
                    if _time.time() < popup._grace_until:
                        return False

                    try:
                        click_pos = event.globalPosition().toPoint()
                    except AttributeError:
                        click_pos = event.globalPos()

                    # 弹窗内部 → 不关闭（允许点击收藏按钮等）
                    if popup.geometry().contains(click_pos):
                        return False

                    # 弹窗外部任意位置 → 关闭
                    popup.hide_popup()
                    return False

                return False

        app = QApplication.instance()
        if app is None:
            return

        if hasattr(app, '_word_popup_filter'):
            app.removeEventFilter(app._word_popup_filter)
        f = _PopupClickFilter()
        app.installEventFilter(f)
        app._word_popup_filter = f

        # ---- Layer 2: Windows 原生消息钩子 ----
        try:
            import sys
            if not sys.platform.startswith('win'):
                return
            import ctypes
            from ctypes import wintypes

            # 防止重复安装
            if hasattr(app, '_word_popup_win_hook_id'):
                ctypes.windll.user32.UnhookWindowsHookEx(app._word_popup_win_hook_id)

            # 使用 Windows 原生 CBT 钩子监控窗口激活变化
            # 这样即使点击桌面或其他非 Qt 应用也能感知
            WH_MOUSE_LL = 14  # 低级鼠标钩子

            # 存储钩子回调引用防止被 GC
            _MouseProc = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
            )

            def _mouse_hook_callback(nCode, wParam, lParam):
                """低级鼠标钩子回调 — 在任何鼠标点击时检查弹窗。"""
                if wParam == 0x0201:  # WM_LBUTTONDOWN
                    popup = popup_ref[0] if popup_ref else None
                    if popup is None or not popup.isVisible():
                        return ctypes.windll.user32.CallNextHookEx(
                            app._word_popup_win_hook_id, nCode, wParam, lParam
                        )
                    # 宽限期内不响应外部点击
                    if _time.time() < popup._grace_until:
                        return ctypes.windll.user32.CallNextHookEx(
                            app._word_popup_win_hook_id, nCode, wParam, lParam
                        )
                    # 从 lParam 提取鼠标坐标（MSLLHOOKSTRUCT）
                    x = ctypes.c_long.from_address(lParam).value
                    y = ctypes.c_long.from_address(lParam + 4).value
                    click_pos = QPoint(x, y)

                    # 弹窗外部任意位置 → 跨线程安全关闭
                    if not popup.geometry().contains(click_pos):
                        popup._request_close.emit()

                return ctypes.windll.user32.CallNextHookEx(
                    app._word_popup_win_hook_id, nCode, wParam, lParam
                )

            # 保存回调引用防止被 GC 回收导致崩溃
            app._word_popup_mouse_proc = _MouseProc(_mouse_hook_callback)

            # 安装全局低级鼠标钩子（WH_MOUSE_LL 要求 hMod=NULL）
            hook_id = ctypes.windll.user32.SetWindowsHookExW(
                WH_MOUSE_LL,
                app._word_popup_mouse_proc,
                0,  # 低级钩子不需要模块句柄
                0,
            )
            if hook_id:
                app._word_popup_win_hook_id = hook_id
            else:
                print("[WordPopup] 无法安装 Windows 鼠标钩子，回退到 Qt 事件过滤", file=sys.stderr)
        except Exception as e:
            print(f"[WordPopup] Windows 原生钩子安装失败: {e}", file=sys.stderr)

    def hide_popup(self):
        """隐藏弹窗并清理资源。"""
        try:
            if hasattr(self, '_tts_speak_prep') and self._tts_speak_prep:
                self._tts_speak_prep.end_prepare()
            tts = get_tts()
            if tts.is_speaking():
                tts.stop()
        except Exception:
            pass
        self._cancel_lookup()
        self.hide()

    @staticmethod
    def uninstall_global_hooks():
        """卸载全局钩子（应用退出时调用）。"""
        app = QApplication.instance()
        if app is None:
            return
        if hasattr(app, '_word_popup_win_hook_id'):
            try:
                import ctypes
                ctypes.windll.user32.UnhookWindowsHookEx(app._word_popup_win_hook_id)
                del app._word_popup_win_hook_id
            except Exception:
                pass
        if hasattr(app, '_word_popup_mouse_proc'):
            try:
                del app._word_popup_mouse_proc
            except Exception:
                pass


# 全局弹窗实例引用
_word_popup_instance: Optional[WordPopup] = None
_popup_ref: list = [None]  # 用于全局事件过滤器的可变引用


def get_word_popup() -> WordPopup:
    """获取全局 WordPopup 单例。"""
    global _word_popup_instance, _popup_ref
    if _word_popup_instance is None:
        _word_popup_instance = WordPopup()
        _popup_ref[0] = _word_popup_instance
        WordPopup.install_global_click_filter(_popup_ref)
        # 应用退出时卸载 Windows 钩子
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(lambda: WordPopup.uninstall_global_hooks())
    return _word_popup_instance


def show_word_popup(word: str, global_pos: QPoint, text_edit: QWidget):
    """便捷函数：显示单词弹窗。"""
    popup = get_word_popup()
    popup.show_at(word, global_pos, text_edit)
