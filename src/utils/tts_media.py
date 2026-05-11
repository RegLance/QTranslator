"""Edge TTS 等在线朗读的音频播放桥接（必须在 Qt 主线程使用 QMediaPlayer）。"""
import os
from collections import deque
from typing import Deque, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QUrl

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
except ImportError:  # 极端环境无 QtMultimedia
    QMediaPlayer = None  # type: ignore
    QAudioOutput = None  # type: ignore


def _media_diag(msg: str, level: str = "info") -> None:
    try:
        from .tts import _log_tts

        _log_tts(f"TTSMedia: {msg}", level)
    except Exception:
        pass


class TTSEdgePlayback(QObject):
    """在主线程播放临时 MP3，并在结束时通知 TTSEngine 复位状态。"""

    playRequested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._player: Optional[QMediaPlayer] = None
        self._audio: Optional[QAudioOutput] = None
        self._current_path: Optional[str] = None
        self._pending_paths: Deque[str] = deque()
        self._aborting = False

        if QMediaPlayer is not None and QAudioOutput is not None:
            self._player = QMediaPlayer()
            self._audio = QAudioOutput()
            self._player.setAudioOutput(self._audio)
            self._player.mediaStatusChanged.connect(self._on_media_status)

        self.playRequested.connect(self._on_play_requested)

    def is_operational(self) -> bool:
        return self._player is not None

    def abort_playback(self) -> bool:
        """停止队列与解码。返回是否真的在播放或有排队音频（便于 UI 兜底收到 on_stop）。"""
        playing = False
        if self._player:
            try:
                playing = (
                    self._player.playbackState()
                    == QMediaPlayer.PlaybackState.PlayingState
                )
            except Exception:
                playing = False

        had_queue_before = bool(self._current_path) or bool(self._pending_paths)
        had_media = had_queue_before or playing

        self._aborting = True
        self._pending_paths.clear()
        try:
            if self._player:
                self._player.stop()
        finally:
            self._unlink_current()
            self._aborting = False
            if had_media:
                try:
                    from .tts import get_tts
                    get_tts()._edge_user_aborted_playback()
                except Exception:
                    pass

        return had_media

    def enqueue_play(self, path: str):
        """从任意线程调用：将播放请求投递到主线程。"""
        p = os.path.normpath(path)
        _media_diag(f"enqueue_play emit path={p!r} exists={os.path.isfile(p)}")
        self.playRequested.emit(p)

    def _on_play_requested(self, path: str):
        if not self._player:
            self._pending_paths.clear()
            _media_diag("playRequested: no QMediaPlayer -> error end", "error")
            self._notify_engine_end(error=True)
            return
        self._pending_paths.append(path)
        _media_diag(f"playRequested: queued len={len(self._pending_paths)}")
        self._pump_queue()

    def _pump_queue(self) -> None:
        if not self._player or self._current_path is not None:
            return
        if not self._pending_paths:
            return
        path = self._pending_paths.popleft()
        self._current_path = path
        url = QUrl.fromLocalFile(path)
        _media_diag(f"pump: setSource url={url.toString()!r}")
        self._player.setSource(url)
        self._player.play()
        _media_diag("pump: play() called")

    def _on_media_status(self, status):
        if not self._player:
            return
        if self._aborting:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            _media_diag("mediaStatus EndOfMedia -> success")
            self._unlink_current()
            self._pump_queue()
            if self._current_path is None and not self._pending_paths:
                self._notify_engine_end(error=False)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            _media_diag("mediaStatus InvalidMedia -> error", "error")
            self._pending_paths.clear()
            self._unlink_current()
            self._notify_engine_end(error=True)

    def _unlink_current(self):
        path = self._current_path
        self._current_path = None
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _notify_engine_end(self, error: bool):
        try:
            from .tts import get_tts
            get_tts()._edge_playback_finished(error=error)
        except Exception:
            pass


_bridge: Optional[TTSEdgePlayback] = None


def ensure_tts_media_bridge() -> Optional[TTSEdgePlayback]:
    """在主线程创建单例桥接（应用启动后调用一次）。"""
    global _bridge
    if _bridge is None and QMediaPlayer is not None:
        _bridge = TTSEdgePlayback()
    return _bridge


def get_tts_media_bridge() -> Optional[TTSEdgePlayback]:
    return _bridge
