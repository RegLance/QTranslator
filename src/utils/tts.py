"""文本转语音（TTS）模块：系统语音（SAPI/pyttsx3）与 Microsoft Edge 在线 TTS（edge-tts）。"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from enum import Enum
from typing import Optional, Callable, Dict

LANG_HINT_TO_VOICE: Dict[str, str] = {
    "中文": "zh-CN-XiaoxiaoNeural",
    "英文": "en-US-JennyNeural",
    "日文": "ja-JP-NanamiNeural",
    "韩文": "ko-KR-SunHiNeural",
}

# langdetect 常见结果 -> Edge Neural 音色
DETECT_CODE_TO_VOICE: Dict[str, str] = {
    "zh-cn": "zh-CN-XiaoxiaoNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "zh-tw": "zh-TW-HsiaoChenNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-JennyNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-AlvaroNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "vi": "vi-VN-HoaiMyNeural",
}

_DEFAULT_EDGE_VOICE = "en-US-JennyNeural"

# 设置界面预置 Edge 音色：(显示名, 语音 ID)；ID 为空表示按语言自动
EDGE_TTS_VOICE_PRESETS: tuple[tuple[str, str], ...] = (
    ("自动（按语言）", ""),
    ("中文 · 晓晓（女）", "zh-CN-XiaoxiaoNeural"),
    ("中文 · 云希（男）", "zh-CN-YunxiNeural"),
    ("中文 · 云扬（男·新闻风格）", "zh-CN-YunyangNeural"),
    ("中文 · 晓伊（女）", "zh-CN-XiaoyiNeural"),
    ("中文 · 晓涵（女）", "zh-CN-XiaohanNeural"),
    ("中文 · 晓墨（女）", "zh-CN-XiaomoNeural"),
    ("台湾中文 · 晓臻（女）", "zh-TW-HsiaoChenNeural"),
    ("台湾中文 · 云哲（男）", "zh-TW-YunJheNeural"),
    ("英文 · Jenny（女）", "en-US-JennyNeural"),
    ("英文 · Guy（男）", "en-US-GuyNeural"),
    ("日文 · Nanami（女）", "ja-JP-NanamiNeural"),
    ("日文 · Keita（男）", "ja-JP-KeitaNeural"),
    ("韩文 · SunHi（女）", "ko-KR-SunHiNeural"),
    ("韩文 · InJoon（男）", "ko-KR-InJoonNeural"),
)

EDGE_TTS_RATE_SLIDER_MIN = -50
EDGE_TTS_RATE_SLIDER_MAX = 100
EDGE_TTS_VOLUME_SLIDER_MIN = -50
EDGE_TTS_VOLUME_SLIDER_MAX = 50


def parse_edge_percent_for_slider(raw: Optional[str], default: int, min_v: int, max_v: int) -> int:
    """将配置中的 '+12%' / '-10%' 解析为整数，并限制在滑块范围内。"""
    if raw is None or not str(raw).strip():
        return default
    s = str(raw).strip().rstrip("%").strip()
    try:
        v = int(round(float(s)))
    except ValueError:
        return default
    return max(min_v, min(max_v, v))


def edge_percent_from_slider(value: int) -> str:
    """滑块整数转为 edge-tts 所需的带符号百分比字符串。"""
    return f"{int(value):+d}%"


def _log_tts(msg: str, level: str = "info") -> None:
    """朗读诊断日志默认关闭，避免刷屏。"""
    return


def _edge_dependency_status() -> tuple[bool, str]:
    """(Edge 链路是否就绪, 说明或失败原因)。"""
    parts: list[str] = []

    try:
        import edge_tts  # noqa: F401
        parts.append("edge_tts: ok")
    except Exception as e:
        parts.append(f"edge_tts: FAIL ({type(e).__name__}: {e})")

    try:
        from PyQt6.QtMultimedia import QMediaPlayer  # noqa: F401

        parts.append("QtMultimedia: ok")
    except Exception as e:
        parts.append(f"QtMultimedia: FAIL ({type(e).__name__}: {e})")

    ok = parts[0].endswith(": ok") and parts[1].endswith(": ok") if len(parts) >= 2 else False
    return ok, " | ".join(parts)


def _edge_imports_ok() -> bool:
    ok, _ = _edge_dependency_status()
    return ok


def _edge_save_audio_to_file(communicate: object, path: str) -> None:
    """将 Edge 合成音频写入 path。兼容无 save_sync 的 edge-tts（如部分旧版/裁剪打包）。"""
    save_sync = getattr(communicate, "save_sync", None)
    if callable(save_sync):
        save_sync(path)
        return

    stream_sync = getattr(communicate, "stream_sync", None)
    if callable(stream_sync):
        with open(path, "wb") as f:
            for chunk in stream_sync():
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("type") == "audio" and chunk.get("data"):
                    f.write(chunk["data"])
        return

    import asyncio

    save = getattr(communicate, "save", None)
    if callable(save):
        asyncio.run(save(path))
        return

    stream = getattr(communicate, "stream", None)
    if callable(stream):

        async def _drain() -> None:
            with open(path, "wb") as f:
                async for message in stream():
                    if (
                        isinstance(message, dict)
                        and message.get("type") == "audio"
                        and message.get("data")
                    ):
                        f.write(message["data"])

        asyncio.run(_drain())
        return

    raise RuntimeError("edge_tts.Communicate 无 save_sync / stream_sync / save / stream 可用")


# 长文本拆成两段：前段较短以更快开始出声，后段在前段播放时于后台线程内合成并入队。
_EDGE_SPLIT_MIN_CHARS = 160
_EDGE_HEAD_MAX_CHARS = 220
_EDGE_TAIL_MIN_CHARS = 48
_EDGE_HEAD_PREF_MIN_CHARS = 32


def _edge_hard_split(s: str) -> Optional[tuple[str, str]]:
    """前段过短时，在合适区间按空白/顿号或固定位置硬切，保证两段都有足够长度。"""
    n = len(s)
    hi = n - _EDGE_TAIL_MIN_CHARS
    lo = _EDGE_HEAD_PREF_MIN_CHARS
    if hi <= lo:
        return None
    window = s[lo:hi]
    for sep in (" ", "\n", "\u3001", "\uff0c", ",", "，"):
        j = window.rfind(sep)
        if j >= 0:
            cut = lo + j + len(sep)
            h, t = s[:cut].strip(), s[cut:].strip()
            if len(h) >= 8 and len(t) >= _EDGE_TAIL_MIN_CHARS:
                return h, t
    cut = min(hi, max(lo, _EDGE_HEAD_MAX_CHARS))
    h, t = s[:cut].strip(), s[cut:].strip()
    if len(t) >= _EDGE_TAIL_MIN_CHARS:
        return h, t
    return None


def _edge_speak_segments(text: str) -> list[str]:
    """返回 1～2 段待合成文本。"""
    s = (text or "").strip()
    if len(s) < _EDGE_SPLIT_MIN_CHARS:
        return [s]
    cap = min(_EDGE_HEAD_MAX_CHARS, len(s))
    pref = s[:cap]
    delim_re = r"[。.．！？]|…|[.!?](?=\s|$)"
    matches = list(re.finditer(delim_re, pref))
    cut: Optional[int] = None
    for m in reversed(matches):
        if m.end() >= _EDGE_HEAD_PREF_MIN_CHARS:
            cut = m.end()
            break
    if cut is None and matches:
        cut = matches[-1].end()
    if cut is None:
        nl = pref.rfind("\n")
        if nl >= _EDGE_HEAD_PREF_MIN_CHARS:
            cut = nl + 1
        else:
            sp = pref.rfind(" ")
            if sp >= _EDGE_HEAD_PREF_MIN_CHARS:
                cut = sp + 1
            else:
                cut = cap
    head = s[:cut].strip()
    tail = s[cut:].strip()
    if len(head) < _EDGE_HEAD_PREF_MIN_CHARS and len(tail) >= _EDGE_TAIL_MIN_CHARS:
        pair = _edge_hard_split(s)
        if pair:
            head, tail = pair
    if not tail or len(tail) < _EDGE_TAIL_MIN_CHARS:
        return [s]
    return [head, tail]


def _config_edge_voice() -> str:
    try:
        from ..config import get_config
        v = (get_config().get("tts.edge_voice") or "").strip()
        return v
    except Exception:
        return ""


def _config_edge_rate_volume() -> tuple[str, str]:
    try:
        from ..config import get_config
        cfg = get_config()
        rate = (cfg.get("tts.edge_rate") or "+0%").strip() or "+0%"
        vol = (cfg.get("tts.edge_volume") or "+0%").strip() or "+0%"
        return rate, vol
    except Exception:
        return "+0%", "+0%"


def _pick_edge_voice(lang_hint: Optional[str], text: str) -> str:
    forced = _config_edge_voice()
    if forced:
        return forced
    if lang_hint and lang_hint in LANG_HINT_TO_VOICE:
        return LANG_HINT_TO_VOICE[lang_hint]
    sample = (text or "")[:400]
    if re.search(r"[\u3040-\u30ff]", sample):
        return LANG_HINT_TO_VOICE["日文"]
    if re.search(r"[\uac00-\ud7af]", sample):
        return LANG_HINT_TO_VOICE["韩文"]
    if re.search(r"[\u4e00-\u9fff]", sample):
        return LANG_HINT_TO_VOICE["中文"]
    try:
        from langdetect import detect
        code = detect(sample) if sample else "en"
        code = (code or "en").lower()
        return DETECT_CODE_TO_VOICE.get(code, _DEFAULT_EDGE_VOICE)
    except Exception:
        return _DEFAULT_EDGE_VOICE


def _tts_provider() -> str:
    try:
        from ..config import get_config
        p = (get_config().get("tts.provider") or "system").strip().lower()
        return p if p in ("system", "edge") else "system"
    except Exception:
        return "system"


class TTSState(Enum):
    IDLE = "idle"
    SPEAKING = "speaking"


class TTSEngine:
    """文本转语音引擎：系统 SAPI / pyttsx3，或 Edge 在线 TTS。"""

    _instance: Optional["TTSEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._state = TTSState.IDLE
        self._lock = threading.Lock()
        self._current_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._thread_engine = None

        self._on_start_callback: Optional[Callable] = None
        self._on_finish_callback: Optional[Callable] = None
        self._on_stop_callback: Optional[Callable] = None

        # Edge 朗读失败时回退系统 TTS：保留本次待读内容与语言提示
        self._edge_fallback_text: Optional[str] = None
        self._edge_fallback_lang_hint: Optional[str] = None
        # Edge 多段合成与 abort/stop 竞态：每次 speak/stop 递增，仅当前代号的入队有效
        self._edge_enqueue_generation: int = 0

        self._system_backend = None
        try:
            import win32com.client  # noqa: F401
            self._system_backend = "sapi"
        except ImportError:
            pass
        if self._system_backend is None:
            try:
                import pyttsx3  # noqa: F401
                self._system_backend = "pyttsx3"
            except ImportError:
                pass

    def is_available(self) -> bool:
        """Edge 模式下若 Edge 不可用但系统 TTS 可用，仍返回 True（失败时自动回退）。"""
        if _tts_provider() == "edge":
            return bool(_edge_imports_ok() or self._system_backend is not None)
        return self._system_backend is not None

    def _clear_edge_fallback(self) -> None:
        self._edge_fallback_text = None
        self._edge_fallback_lang_hint = None

    def set_callbacks(self, on_start: Callable = None, on_finish: Callable = None, on_stop: Callable = None):
        self._on_start_callback = on_start
        self._on_finish_callback = on_finish
        self._on_stop_callback = on_stop

    def speak(self, text: str, lang_hint: Optional[str] = None, _force_system: bool = False) -> bool:
        """朗读文本。

        Args:
            text: 正文
            lang_hint: 翻译窗口目标语「中文/英文/日文/韩文」；None 或「自动检测」时按文本推测 Edge 音色。
            _force_system: 内部使用——强制走系统 TTS（Edge 失败回退）。
        """
        stripped = (text or "").strip()
        if not stripped:
            return False

        if _force_system:
            if not self._system_backend:
                return False
        else:
            if not self.is_available():
                return False

        with self._lock:
            if self._state == TTSState.SPEAKING:
                return False
            self._stop_requested = False
            self._state = TTSState.SPEAKING
            provider = "system" if _force_system else _tts_provider()
            edge_job_id = 0
            if provider == "edge":
                self._edge_enqueue_generation += 1
                edge_job_id = self._edge_enqueue_generation

        try:
            from ..config import get_config
            raw_prov = repr(get_config().get("tts.provider"))
        except Exception:
            raw_prov = "(unread)"
        dep_ok, dep_msg = _edge_dependency_status()
        _log_tts(
            f"speak: config.tts.provider={raw_prov} resolved={provider} "
            f"force_system={_force_system} edge_deps_ok={dep_ok} [{dep_msg}] "
            f"system_backend={self._system_backend!r} text_len={len(stripped)} edge_job={edge_job_id}"
        )

        if provider == "edge":
            self._edge_fallback_text = stripped
            self._edge_fallback_lang_hint = lang_hint
            self._run_edge_speak(stripped, lang_hint, edge_job_id)
            return True

        self._clear_edge_fallback()
        _log_tts(f"run_system_speak: backend={self._system_backend!r}")
        self._run_system_speak(stripped)
        return True

    def _run_edge_speak(self, text: str, lang_hint: Optional[str], edge_job_id: int):
        def _edge_job_alive() -> bool:
            with self._lock:
                return self._edge_enqueue_generation == edge_job_id

        enqueued_playback = [False]
        aborted_before_enqueue = [False]

        def _thread():
            tmp_path: Optional[str] = None

            def cleanup_mp3():
                nonlocal tmp_path
                if tmp_path and os.path.isfile(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                tmp_path = None

            try:
                if not _edge_imports_ok():
                    raise RuntimeError("edge_tts 或 PyQt6.QtMultimedia 不可用")
                import edge_tts
                from .tts_media import ensure_tts_media_bridge

                _edge_ver = getattr(edge_tts, "__version__", "?")
                try:
                    from edge_tts.constants import SEC_MS_GEC_VERSION as _edge_gec_ver
                except Exception:
                    _edge_gec_ver = "?"
                _log_tts(
                    f"Edge thread: edge-tts={_edge_ver} SEC_MS_GEC_VERSION={_edge_gec_ver}"
                )

                bridge = ensure_tts_media_bridge()
                ops = bool(bridge and bridge.is_operational())
                _log_tts(
                    f"Edge thread: bridge={bridge is not None} operational={ops} lang_hint={lang_hint!r}"
                )
                if not bridge or not ops:
                    raise RuntimeError("TTS 媒体播放未初始化")

                voice = _pick_edge_voice(lang_hint, text)
                rate, volume = _config_edge_rate_volume()
                _log_tts(f"Edge thread: voice={voice} rate={rate} volume={volume}")
                segments = _edge_speak_segments(text)
                if len(segments) > 1:
                    _log_tts(
                        f"Edge thread: 分段加快首包 total_len={len(text)} "
                        f"seg1_len={len(segments[0])} seg2_len={len(segments[1])}"
                    )

                start_cb_fired = False
                for seg_idx, seg_text in enumerate(segments):
                    if self._stop_requested or not _edge_job_alive():
                        if not _edge_job_alive():
                            aborted_before_enqueue[0] = True
                        break
                    fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="qtr_tts_")
                    os.close(fd)
                    try:
                        communicate = edge_tts.Communicate(
                            seg_text, voice, rate=rate, volume=volume
                        )
                        _edge_save_audio_to_file(communicate, tmp_path)
                    except Exception as seg_exc:
                        if seg_idx == 0:
                            raise
                        _log_tts(
                            f"Edge 后段合成失败（前段已入队）: "
                            f"{type(seg_exc).__name__}: {seg_exc}",
                            "warning",
                        )
                        try:
                            if tmp_path and os.path.isfile(tmp_path):
                                os.unlink(tmp_path)
                        except OSError:
                            pass
                        tmp_path = None
                        break

                    mp3_sz = (
                        os.path.getsize(tmp_path)
                        if tmp_path and os.path.isfile(tmp_path)
                        else -1
                    )
                    _log_tts(
                        f"Edge thread: seg{seg_idx + 1} mp3 size={mp3_sz} path={tmp_path!r}"
                    )

                    if self._stop_requested or not _edge_job_alive():
                        aborted_before_enqueue[0] = True
                        cleanup_mp3()
                        break

                    if not start_cb_fired:
                        if self._on_start_callback:
                            try:
                                self._on_start_callback()
                            except Exception:
                                pass
                        start_cb_fired = True

                    if self._stop_requested or not _edge_job_alive():
                        aborted_before_enqueue[0] = True
                        cleanup_mp3()
                        break

                    enqueued_playback[0] = True
                    _log_tts(
                        f"Edge thread: enqueue seg{seg_idx + 1}/{len(segments)} -> main"
                    )
                    bridge.enqueue_play(tmp_path)
                    tmp_path = None

            except Exception as e:
                _log_tts(f"Edge 朗读失败: {type(e).__name__}: {e}", "error")
                err_s = str(e).lower()
                if (
                    "403" in str(e)
                    or "invalid response status" in err_s
                    or type(e).__name__ == "WSServerHandshakeError"
                ):
                    _log_tts(
                        "Edge 403/握手失败：多为 edge-tts 过旧（日志里 SEC_MS_GEC_VERSION "
                        "若明显低于当前 Edge 浏览器大版本，请 pip install -U \"edge-tts>=7.2.8\"；"
                        "打包程序需用新依赖重新构建。亦可能是网络/地区限制，将回退系统朗读。",
                        "warning",
                    )
                with self._lock:
                    fb_text = self._edge_fallback_text
                    fb_hint = self._edge_fallback_lang_hint
                    self._clear_edge_fallback()
                    user_aborted = self._stop_requested
                    self._state = TTSState.IDLE
                    self._stop_requested = False

                if not user_aborted and fb_text and self._system_backend:
                    _log_tts("Edge 合成/入队失败，回退系统 TTS", "warning")
                    if self.speak(fb_text, lang_hint=fb_hint, _force_system=True):
                        enqueued_playback[0] = True
                        return

                if not user_aborted:
                    try:
                        if self._on_finish_callback:
                            self._on_finish_callback()
                    except Exception:
                        pass

            finally:
                cleanup_mp3()
                if enqueued_playback[0]:
                    return

                # 用户在合成完成前取消，且未进入 except
                if aborted_before_enqueue[0]:
                    with self._lock:
                        self._clear_edge_fallback()
                        if self._state == TTSState.SPEAKING:
                            self._state = TTSState.IDLE
                            self._stop_requested = False
                    return

        self._current_thread = threading.Thread(target=_thread, daemon=True)
        self._current_thread.start()

    def _run_system_speak(self, text: str):
        def _speak_thread():
            thread_was_stopped = False
            try:
                if self._system_backend == "sapi":
                    try:
                        import pythoncom
                        pythoncom.CoInitialize()
                    except Exception:
                        pass

                    try:
                        import win32com.client
                        engine = win32com.client.Dispatch("SAPI.SpVoice")

                        if self._on_start_callback:
                            try:
                                self._on_start_callback()
                            except Exception:
                                pass

                        engine.Speak(text, 1)

                        while True:
                            if self._stop_requested:
                                try:
                                    engine.Speak("", 3)
                                except Exception:
                                    pass
                                thread_was_stopped = True
                                break

                            try:
                                if engine.WaitUntilDone(0):
                                    break
                            except Exception:
                                break

                            time.sleep(0.05)
                    finally:
                        try:
                            import pythoncom
                            pythoncom.CoUninitialize()
                        except Exception:
                            pass

                elif self._system_backend == "pyttsx3":
                    import pyttsx3
                    engine = pyttsx3.init()

                    with self._lock:
                        self._thread_engine = engine

                    if self._on_start_callback:
                        try:
                            self._on_start_callback()
                        except Exception:
                            pass

                    engine.say(text)
                    engine.runAndWait()

                    thread_was_stopped = self._stop_requested

            except Exception:
                pass
            finally:
                with self._lock:
                    self._state = TTSState.IDLE
                    self._stop_requested = False
                    self._thread_engine = None

                try:
                    if thread_was_stopped and self._on_stop_callback:
                        self._on_stop_callback()
                    elif not thread_was_stopped and self._on_finish_callback:
                        self._on_finish_callback()
                except Exception:
                    pass

        self._current_thread = threading.Thread(target=_speak_thread, daemon=True)
        self._current_thread.start()

    def _edge_playback_finished(self, error: bool):
        """由 TTSEdgePlayback 在主线程调用（播放自然结束或媒体错误）。"""
        fb_text = None
        fb_hint = None
        with self._lock:
            if self._state != TTSState.SPEAKING:
                return
            self._state = TTSState.IDLE
            self._stop_requested = False
            if error:
                fb_text = self._edge_fallback_text
                fb_hint = self._edge_fallback_lang_hint
            self._clear_edge_fallback()

        _log_tts(f"Edge playback_finished: error={error} fallback_text={bool(fb_text)}")
        if error and fb_text and self._system_backend:
            _log_tts("Edge 播放失败（InvalidMedia 等），回退系统 TTS", "warning")
            if self.speak(fb_text, lang_hint=fb_hint, _force_system=True):
                return

        try:
            if error:
                if self._on_stop_callback:
                    self._on_stop_callback()
            elif self._on_finish_callback:
                self._on_finish_callback()
        except Exception:
            pass

    def _edge_user_aborted_playback(self):
        """中断 Edge 音频回放时复位状态（不调用 on_stop，由 stop() 统一触发）。"""
        with self._lock:
            if self._state != TTSState.SPEAKING:
                return
            self._clear_edge_fallback()
            self._state = TTSState.IDLE
            # 保留 _stop_requested，供 Edge 合成线程在入队前检测到并退出；
            # 下一次 speak() 会将其清 False。

    def stop(self) -> None:
        """停止朗读（Edge / 系统语音 / 二者切换中的任意阶段）。"""
        should_notify_stop = False
        py_eng = None
        with self._lock:
            self._edge_enqueue_generation += 1
            if self._state == TTSState.SPEAKING:
                self._stop_requested = True
                should_notify_stop = True
            if self._system_backend == "pyttsx3":
                py_eng = self._thread_engine

        media_stopped = False
        try:
            from .tts_media import get_tts_media_bridge

            b = get_tts_media_bridge()
            if b:
                media_stopped = bool(b.abort_playback())
        except Exception:
            pass

        if py_eng:
            try:
                py_eng.stop()
            except Exception:
                pass

        if (
            should_notify_stop or media_stopped
        ) and self._on_stop_callback:
            try:
                self._on_stop_callback()
            except Exception:
                pass

    def is_speaking(self) -> bool:
        with self._lock:
            return self._state == TTSState.SPEAKING

    def get_state(self) -> TTSState:
        with self._lock:
            return self._state


def get_tts() -> TTSEngine:
    return TTSEngine()
