"""单词收藏窗口：列表 + 详情（浏览、删除、导出）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent, QObject, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QMouseEvent,
    QCloseEvent,
    QTextCursor,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QHideEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

# (id, 界面标签, 英文 articlePrompt 喂给模型)
BIG_BANG_ARTICLE_OPTIONS: Tuple[Tuple[str, str, str], ...] = (
    ("story", "有趣的小故事", "an insteresting story"),
    ("newsletter", "政治简报", "a political newsletter"),
    ("sports", "体育简报", "a sports bulletin"),
    ("lyric", "一段歌词", "a catchy lyric"),
    ("poem", "一首诗", "a smooth poem"),
)

try:
    from ..config import APP_NAME
    from ..utils.theme import get_scrollbar_style, get_splitter_style, get_theme, get_combobox_style
    from ..utils.tts import get_tts
    from ..utils.tts_speak_indicator import TtsSpeakPrepareIndicator
    from ..utils.vocabulary import VocabularyItem, get_vocabulary
except ImportError:
    from src.config import APP_NAME
    from src.utils.theme import get_scrollbar_style, get_splitter_style, get_theme, get_combobox_style
    from src.utils.tts import get_tts
    from src.utils.tts_speak_indicator import TtsSpeakPrepareIndicator
    from src.utils.vocabulary import VocabularyItem, get_vocabulary


class BigBangWorker(QThread):
    """后台流式调用翻译 API（词汇短文生成）。"""

    chunk_received = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, article_prompt: str, words_csv: str, parent=None):
        super().__init__(parent)
        self._article_prompt = article_prompt
        self._words_csv = words_csv
        self._cancel = False

    def run(self) -> None:
        try:
            try:
                from ..core.translator import get_translator
            except ImportError:
                from src.core.translator import get_translator

            translator = get_translator()
            full = ""
            for chunk in translator.big_bang_stream(self._article_prompt, self._words_csv):
                if self._cancel:
                    return
                if chunk:
                    full += chunk
                    self.chunk_received.emit(chunk)
            if not self._cancel:
                self.finished_ok.emit(full)
        except Exception as e:
            if not self._cancel:
                self.failed.emit(str(e))

    def cancel(self) -> None:
        self._cancel = True


class VocabularyWindow(QWidget):
    """单词收藏窗口"""

    # 双击条目标在翻译窗口打开
    open_in_translator = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("VocabularyWindow")
        try:
            from ..config import get_config
        except ImportError:
            from src.config import get_config

        self._theme_style = get_config().get("theme.popup_style", "dark")

        self._is_dragging = False
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_window_start_pos: Optional[QPoint] = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(560, 520)
        self.resize(720, 640)

        self._vocabulary = get_vocabulary()
        self._big_bang_worker: Optional[BigBangWorker] = None
        self._current_item: Optional[VocabularyItem] = None
        self._setup_ui()

        try:
            from ..utils.theme import get_theme_manager
        except ImportError:
            from src.utils.theme import get_theme_manager

        get_theme_manager().theme_changed.connect(self.update_theme)

    @staticmethod
    def _create_speak_icon(theme: dict) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        icon_color = QColor(theme.get("text_muted", "#888888"))
        painter.setBrush(icon_color)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        triangle = [QPointF(5, 3), QPointF(5, 15), QPointF(15, 9)]
        painter.drawPolygon(*triangle)
        painter.end()
        return QIcon(pixmap)

    def _setup_ui(self) -> None:
        theme = get_theme(self._theme_style)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._content_frame = QFrame()
        self._content_frame.setObjectName("vocContentFrame")
        self._content_frame.setStyleSheet(
            f"""
            QFrame#vocContentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 10px;
                border: 1px solid {theme['border_color']};
            }}
        """
        )
        main_layout.addWidget(self._content_frame)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(*theme["shadow_color"]))
        shadow.setOffset(0, 3)
        self._content_frame.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self._content_frame)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(8)

        title_bar = QHBoxLayout()
        self._title_label = QLabel("单词收藏")
        self._title_label.setStyleSheet(
            f"color: {theme['text_primary']}; font-size: 15px; font-weight: bold;"
        )
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent; color: {theme['text_muted']};
                border: none; border-radius: 11px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['close_hover']}; color: #fff; }}
        """
        )
        self._close_btn.clicked.connect(self.close)
        title_bar.addWidget(self._title_label)
        title_bar.addStretch()
        title_bar.addWidget(self._close_btn)
        outer.addLayout(title_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        self._splitter.setStyleSheet(get_splitter_style(theme))
        self._list = QListWidget()
        self._list.setMinimumWidth(160)
        self._list.setStyleSheet(
            f"""
            QListWidget {{ background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px; }}
            {get_scrollbar_style(theme)}
        """
        )
        self._list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)

        detail = QFrame()
        detail.setMinimumWidth(240)
        detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(0)

        self._trans_output_container = QWidget()
        self._trans_output_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._trans_output_container.setStyleSheet(
            "QWidget { background-color: transparent; border: none; }"
        )

        self._trans_plain = QPlainTextEdit(self._trans_output_container)
        self._trans_plain.setReadOnly(True)
        self._trans_plain.setPlaceholderText("译文")
        self._trans_plain.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px;
            }}
            {get_scrollbar_style(theme)}
        """
        )

        self._trans_floating_frame = QFrame(self._trans_output_container)
        self._trans_floating_frame.setObjectName("vocTransFloatingFrame")
        self._trans_floating_frame.setStyleSheet(
            f"""
            QFrame#vocTransFloatingFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """
        )
        trans_float_layout = QHBoxLayout(self._trans_floating_frame)
        trans_float_layout.setContentsMargins(4, 2, 4, 2)
        trans_float_layout.setSpacing(2)

        self._speak_word_btn = QPushButton()
        self._speak_word_btn.setObjectName("vocSpeakWordBtn")
        self._speak_word_btn.setFixedSize(28, 28)
        self._speak_word_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._speak_word_btn.setToolTip("朗读单词")
        self._speak_word_btn.setIcon(self._create_speak_icon(theme))
        self._speak_word_btn.setEnabled(False)
        self._speak_word_btn.setStyleSheet(
            f"""
            QPushButton#vocSpeakWordBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#vocSpeakWordBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#vocSpeakWordBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
            QPushButton#vocSpeakWordBtn:disabled {{
                opacity: 0.35;
            }}
        """
        )
        self._speak_word_btn.clicked.connect(self._speak_word)
        trans_float_layout.addWidget(self._speak_word_btn)
        self._trans_floating_frame.setFixedSize(36, 34)
        self._trans_floating_frame.raise_()

        self._trans_output_container.installEventFilter(self)

        self._tts_speak_word_prep = TtsSpeakPrepareIndicator(
            self,
            self._speak_word_btn,
            lambda: get_theme(self._theme_style),
            self._create_speak_icon,
        )

        dv.addWidget(self._trans_output_container, 1)

        self._splitter.addWidget(self._list)
        self._splitter.addWidget(detail)
        self._splitter.setSizes([220, 380])
        outer.addWidget(self._splitter, 1)

        row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索原文或译文…")
        self._search_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px;
                padding: 6px 10px;
            }}
        """
        )
        self._search_edit.textChanged.connect(self._reload_list)
        self._del_btn = QPushButton("删除选中")
        self._export_btn = QPushButton("导出 JSON")
        self._clear_btn = QPushButton("清空")
        for b in (self._del_btn, self._export_btn, self._clear_btn):
            b.setStyleSheet(
                f"""
                QPushButton {{
                    background: {theme['button_bg']}; color: {theme['text_primary']};
                    border: none; border-radius: 6px; padding: 6px 12px;
                }}
                QPushButton:hover {{ background: {theme['button_hover']}; }}
            """
            )
        self._del_btn.clicked.connect(self._delete_selected)
        self._export_btn.clicked.connect(self._export_json)
        self._clear_btn.clicked.connect(self._clear_all)
        row.addWidget(self._search_edit, 1)
        row.addWidget(self._del_btn)
        row.addWidget(self._export_btn)
        row.addWidget(self._clear_btn)
        outer.addLayout(row)

        self._bb_title = QLabel("📝 词汇短文")
        self._bb_title.setStyleSheet(
            f"color: {theme['text_primary']}; font-size: 13px; font-weight: bold; margin-top: 4px;"
        )
        self._bb_hint = QLabel(
            "按「复习次数」从高到低取原文，最多 50 条；若总数不足 50，则用当前已有的全部条目。"
            "将这些词用逗号连接后交给当前翻译 API，"
            "生成不超过约 160 词的短文。"
        )
        self._bb_hint.setWordWrap(True)
        self._bb_hint.setStyleSheet(f"color: {theme['text_muted']}; font-size: 11px;")

        bb_row = QHBoxLayout()
        self._bb_genre_label = QLabel("体裁:")
        self._bb_genre_label.setStyleSheet(
            f"color: {theme['text_secondary']}; font-size: 12px; background: transparent;"
        )
        self._bb_article_combo = QComboBox()
        for _id, label, prompt in BIG_BANG_ARTICLE_OPTIONS:
            self._bb_article_combo.addItem(label, prompt)
        self._bb_article_combo.setStyleSheet(get_combobox_style(theme))
        self._bb_go_btn = QPushButton("生成短文")
        self._bb_stop_btn = QPushButton("停止")
        self._bb_stop_btn.setEnabled(False)
        self._bb_go_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {theme['button_bg']}; color: {theme['text_primary']};
                border: none; border-radius: 6px; padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {theme['button_hover']}; }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """
        )
        self._bb_stop_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {theme['button_bg']}; color: {theme['text_primary']};
                border: none; border-radius: 6px; padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {theme['button_hover']}; }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """
        )
        self._bb_go_btn.clicked.connect(self._on_big_bang_clicked)
        self._bb_stop_btn.clicked.connect(self._on_big_bang_stop)
        bb_row.addWidget(self._bb_genre_label)
        bb_row.addWidget(self._bb_article_combo, 1)
        bb_row.addWidget(self._bb_go_btn)
        bb_row.addWidget(self._bb_stop_btn)

        self._bb_output_container = QWidget()
        self._bb_output_container.setMinimumHeight(120)
        self._bb_output_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self._bb_output_container.setStyleSheet(
            "QWidget { background-color: transparent; border: none; }"
        )
        self._bb_output = QPlainTextEdit(self._bb_output_container)
        self._bb_output.setReadOnly(True)
        self._bb_output.setPlaceholderText("生成的短文将显示在这里…")
        self._bb_output.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px;
            }}
            {get_scrollbar_style(theme)}
        """
        )

        self._bb_floating_frame = QFrame(self._bb_output_container)
        self._bb_floating_frame.setObjectName("vocBbFloatingFrame")
        self._bb_floating_frame.setStyleSheet(
            f"""
            QFrame#vocBbFloatingFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """
        )
        bb_float_layout = QHBoxLayout(self._bb_floating_frame)
        bb_float_layout.setContentsMargins(4, 2, 4, 2)
        bb_float_layout.setSpacing(2)
        self._bb_speak_btn = QPushButton()
        self._bb_speak_btn.setObjectName("vocBbSpeakBtn")
        self._bb_speak_btn.setFixedSize(28, 28)
        self._bb_speak_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._bb_speak_btn.setToolTip("朗读短文")
        self._bb_speak_btn.setIcon(self._create_speak_icon(theme))
        self._bb_speak_btn.setEnabled(False)
        self._bb_speak_btn.setStyleSheet(
            f"""
            QPushButton#vocBbSpeakBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#vocBbSpeakBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#vocBbSpeakBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
            QPushButton#vocBbSpeakBtn:disabled {{
                opacity: 0.35;
            }}
        """
        )
        self._bb_speak_btn.clicked.connect(self._speak_bb_output)
        bb_float_layout.addWidget(self._bb_speak_btn)
        self._bb_floating_frame.setFixedSize(36, 34)
        self._bb_floating_frame.raise_()
        self._bb_output_container.installEventFilter(self)

        self._tts_speak_bb_prep = TtsSpeakPrepareIndicator(
            self,
            self._bb_speak_btn,
            lambda: get_theme(self._theme_style),
            self._create_speak_icon,
        )

        outer.addWidget(self._bb_title)
        outer.addWidget(self._bb_hint)
        outer.addLayout(bb_row)
        outer.addWidget(self._bb_output_container)

    def eventFilter(self, watched: Optional[QObject], event: Optional[QEvent]) -> bool:
        if event is not None and event.type() == QEvent.Type.Resize:
            if watched is self._trans_output_container:
                self._update_trans_output_layout()
                return False
            if watched is self._bb_output_container:
                self._update_bb_output_layout()
                return False
        return super().eventFilter(watched, event)

    def _update_trans_output_layout(self) -> None:
        try:
            c = self._trans_output_container
            w, h = c.width(), c.height()
            if w <= 0 or h <= 0:
                return
            self._trans_plain.setGeometry(0, 0, w, h)
            fw = self._trans_floating_frame.width()
            fh = self._trans_floating_frame.height()
            m = 6
            self._trans_floating_frame.move(w - fw - m, h - fh - m)
        except RuntimeError:
            pass

    def _update_bb_output_layout(self) -> None:
        try:
            c = self._bb_output_container
            w, h = c.width(), c.height()
            if w <= 0 or h <= 0:
                return
            self._bb_output.setGeometry(0, 0, w, h)
            fw = self._bb_floating_frame.width()
            fh = self._bb_floating_frame.height()
            m = 6
            self._bb_floating_frame.move(w - fw - m, h - fh - m)
        except RuntimeError:
            pass

    def _refresh_overlay_layouts(self) -> None:
        self._update_trans_output_layout()
        self._update_bb_output_layout()

    def _sync_bb_speak_btn_enabled(self) -> None:
        try:
            self._bb_speak_btn.setEnabled(bool((self._bb_output.toPlainText() or "").strip()))
        except RuntimeError:
            pass

    def _set_big_bang_busy(self, busy: bool) -> None:
        self._bb_go_btn.setEnabled(not busy)
        self._bb_stop_btn.setEnabled(busy)
        self._bb_article_combo.setEnabled(not busy)

    def _on_big_bang_clicked(self) -> None:
        if self._big_bang_worker is not None and self._big_bang_worker.isRunning():
            return
        items = self._vocabulary.list_frequency_items(50)
        if not items:
            QMessageBox.information(
                self, APP_NAME, "请先收藏一些单词后再使用「词汇短文」。"
            )
            return
        words_csv = ",".join(it.word for it in items)
        prompt = self._bb_article_combo.currentData()
        if not prompt:
            prompt = BIG_BANG_ARTICLE_OPTIONS[0][2]
        self._bb_output.clear()
        self._sync_bb_speak_btn_enabled()
        self._set_big_bang_busy(True)
        self._big_bang_worker = BigBangWorker(str(prompt), words_csv, self)
        self._big_bang_worker.chunk_received.connect(self._on_big_bang_chunk)
        self._big_bang_worker.finished_ok.connect(self._on_big_bang_finished)
        self._big_bang_worker.failed.connect(self._on_big_bang_failed)
        self._big_bang_worker.start()

    def _on_big_bang_chunk(self, chunk: str) -> None:
        cur = self._bb_output.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(chunk)
        self._bb_output.setTextCursor(cur)
        self._sync_bb_speak_btn_enabled()

    def _on_big_bang_finished(self, _full: str) -> None:
        self._set_big_bang_busy(False)
        self._big_bang_worker = None
        self._sync_bb_speak_btn_enabled()

    def _on_big_bang_failed(self, message: str) -> None:
        self._set_big_bang_busy(False)
        self._big_bang_worker = None
        self._sync_bb_speak_btn_enabled()
        QMessageBox.warning(self, APP_NAME, f"词汇短文生成失败：{message}")

    def _on_big_bang_stop(self) -> None:
        if self._big_bang_worker is not None and self._big_bang_worker.isRunning():
            self._big_bang_worker.cancel()
            self._big_bang_worker.wait(3000)
        self._set_big_bang_busy(False)
        self._big_bang_worker = None
        self._sync_bb_speak_btn_enabled()

    def _stop_tts_playback(self) -> None:
        try:
            get_tts().stop()
            self._tts_speak_word_prep.end_prepare()
            self._tts_speak_bb_prep.end_prepare()
        except Exception:
            pass

    def _speak_bb_output(self) -> None:
        text = (self._bb_output.toPlainText() or "").strip()
        if not text:
            return
        tts = get_tts()
        if (
            tts.is_speaking()
            or self._tts_speak_word_prep.is_preparing()
            or self._tts_speak_bb_prep.is_preparing()
        ):
            self._stop_tts_playback()
            return
        self._tts_speak_bb_prep.attach_to_tts_engine(tts)
        ok = tts.speak(text, lang_hint=None)
        if ok:
            self._tts_speak_bb_prep.start_prepare()
        else:
            self._tts_speak_bb_prep.end_prepare()

    def _speak_word(self) -> None:
        if not self._current_item or not (self._current_item.word or "").strip():
            return
        tts = get_tts()
        if (
            tts.is_speaking()
            or self._tts_speak_word_prep.is_preparing()
            or self._tts_speak_bb_prep.is_preparing()
        ):
            self._stop_tts_playback()
            return
        self._tts_speak_word_prep.attach_to_tts_engine(tts)
        ok = tts.speak(self._current_item.word.strip(), lang_hint=None)
        if ok:
            self._tts_speak_word_prep.start_prepare()
        else:
            self._tts_speak_word_prep.end_prepare()

    def _item_word(self, item: Optional[QListWidgetItem]) -> Optional[str]:
        if item is None:
            return None
        w = item.data(Qt.ItemDataRole.UserRole)
        return str(w) if w else None

    def _reload_list(self) -> None:
        kw = self._search_edit.text().strip()
        items: List[VocabularyItem] = self._vocabulary.search(kw)
        self._list.blockSignals(True)
        self._list.clear()
        for it in items:
            li = QListWidgetItem(it.word[:80] + ("…" if len(it.word) > 80 else ""))
            li.setData(Qt.ItemDataRole.UserRole, it.word)
            self._list.addItem(li)
        self._list.blockSignals(False)
        self._current_item = None
        self._speak_word_btn.setEnabled(False)
        self._trans_plain.clear()
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_selection_changed(
        self, cur: Optional[QListWidgetItem], _prev: Optional[QListWidgetItem]
    ) -> None:
        wkey = self._item_word(cur)
        if not wkey:
            self._current_item = None
            self._speak_word_btn.setEnabled(False)
            self._trans_plain.clear()
            return
        it = self._vocabulary.get_item(wkey)
        if not it:
            self._current_item = None
            self._speak_word_btn.setEnabled(False)
            return
        self._current_item = it
        self._speak_word_btn.setEnabled(bool((it.word or "").strip()))
        self._trans_plain.setPlainText(it.translation)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        wkey = self._item_word(item)
        if not wkey:
            return
        it = self._vocabulary.get_item(wkey)
        if it:
            self.open_in_translator.emit(it.word, it.translation)

    def _delete_selected(self) -> None:
        item = self._list.currentItem()
        wkey = self._item_word(item)
        if not wkey:
            return
        self._vocabulary.remove_item(wkey)
        self._reload_list()

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出单词收藏", str(Path.home() / "qtranslator_vocabulary.json"), "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = [it.to_dict() for it in self._vocabulary.list_items()]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"导出失败: {e}")

    def _clear_all(self) -> None:
        if self._list.count() == 0:
            return
        r = QMessageBox.question(
            self,
            APP_NAME,
            "确定清空全部单词收藏？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        self._vocabulary.clear_all()
        self._reload_list()

    def show_window(self) -> None:
        self.update_theme()
        self._reload_list()
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.move(
                g.x() + (g.width() - self.width()) // 2,
                g.y() + (g.height() - self.height()) // 2,
            )
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._refresh_overlay_layouts)

    def update_theme(self) -> None:
        try:
            from ..config import get_config
        except ImportError:
            from src.config import get_config

        self._theme_style = get_config().get("theme.popup_style", "dark")
        theme = get_theme(self._theme_style)
        self._content_frame.setStyleSheet(
            f"""
            QFrame#vocContentFrame {{
                background-color: {theme['bg_color']};
                border-radius: 10px;
                border: 1px solid {theme['border_color']};
            }}
        """
        )
        eff = self._content_frame.graphicsEffect()
        if isinstance(eff, QGraphicsDropShadowEffect):
            eff.setColor(QColor(*theme["shadow_color"]))
        self._title_label.setStyleSheet(
            f"color: {theme['text_primary']}; font-size: 15px; font-weight: bold;"
        )
        self._list.setStyleSheet(
            f"""
            QListWidget {{ background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px; }}
            {get_scrollbar_style(theme)}
        """
        )
        self._splitter.setStyleSheet(get_splitter_style(theme))
        self._tts_speak_word_prep.sync_theme_icons()
        self._speak_word_btn.setStyleSheet(
            f"""
            QPushButton#vocSpeakWordBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#vocSpeakWordBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#vocSpeakWordBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
            QPushButton#vocSpeakWordBtn:disabled {{
                opacity: 0.35;
            }}
        """
        )
        self._trans_floating_frame.setStyleSheet(
            f"""
            QFrame#vocTransFloatingFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """
        )
        self._trans_plain.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px;
            }}
            {get_scrollbar_style(theme)}
        """
        )
        self._search_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px;
                padding: 6px 10px;
            }}
        """
        )
        for b in (self._del_btn, self._export_btn, self._clear_btn):
            b.setStyleSheet(
                f"""
                QPushButton {{
                    background: {theme['button_bg']}; color: {theme['text_primary']};
                    border: none; border-radius: 6px; padding: 6px 12px;
                }}
                QPushButton:hover {{ background: {theme['button_hover']}; }}
            """
            )
        self._bb_title.setStyleSheet(
            f"color: {theme['text_primary']}; font-size: 13px; font-weight: bold; margin-top: 4px;"
        )
        self._bb_hint.setStyleSheet(f"color: {theme['text_muted']}; font-size: 11px;")
        self._bb_genre_label.setStyleSheet(
            f"color: {theme['text_secondary']}; font-size: 12px; background: transparent;"
        )
        self._bb_article_combo.setStyleSheet(get_combobox_style(theme))
        self._bb_floating_frame.setStyleSheet(
            f"""
            QFrame#vocBbFloatingFrame {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
        """
        )
        self._tts_speak_bb_prep.sync_theme_icons()
        self._bb_speak_btn.setStyleSheet(
            f"""
            QPushButton#vocBbSpeakBtn {{
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton#vocBbSpeakBtn:hover {{
                background-color: rgba(0, 0, 0, 0.1);
            }}
            QPushButton#vocBbSpeakBtn:pressed {{
                background-color: rgba(0, 0, 0, 0.2);
            }}
            QPushButton#vocBbSpeakBtn:disabled {{
                opacity: 0.35;
            }}
        """
        )
        self._bb_output.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {theme['input_bg']}; color: {theme['text_primary']};
                border: 1px solid {theme['border_color']}; border-radius: 6px;
            }}
            {get_scrollbar_style(theme)}
        """
        )
        self._bb_go_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {theme['button_bg']}; color: {theme['text_primary']};
                border: none; border-radius: 6px; padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {theme['button_hover']}; }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """
        )
        self._bb_stop_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {theme['button_bg']}; color: {theme['text_primary']};
                border: none; border-radius: 6px; padding: 6px 14px;
            }}
            QPushButton:hover {{ background: {theme['button_hover']}; }}
            QPushButton:disabled {{
                background-color: {theme['scrollbar_handle']};
                color: {theme['text_muted']};
            }}
        """
        )
        self._close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent; color: {theme['text_muted']};
                border: none; border-radius: 11px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme['close_hover']}; color: #fff; }}
        """
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if pos.y() <= 36:
                self._is_dragging = True
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_window_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging and self._drag_start_pos and self._drag_window_start_pos:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            self.move(self._drag_window_start_pos + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._stop_tts_playback()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_tts_playback()
        self._on_big_bang_stop()
        super().closeEvent(event)


_voc_window: Optional[VocabularyWindow] = None


def get_vocabulary_window() -> VocabularyWindow:
    global _voc_window
    if _voc_window is None:
        _voc_window = VocabularyWindow()
    return _voc_window
