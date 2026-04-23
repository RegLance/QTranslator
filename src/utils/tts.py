"""文本转语音（TTS）模块 - 使用 Windows SAPI 或 pyttsx3"""
import threading
import time
from typing import Optional, Callable
from enum import Enum


class TTSState(Enum):
    """TTS 状态枚举"""
    IDLE = "idle"          # 空闲状态
    SPEAKING = "speaking"  # 正在朗读


class TTSEngine:
    """文本转语音引擎

    支持 Windows SAPI 和 pyttsx3 两种后端
    """

    _instance: Optional['TTSEngine'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._engine = None
        self._state = TTSState.IDLE
        self._lock = threading.Lock()
        self._current_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._thread_engine = None  # 子线程中的引擎引用

        # 回调函数
        self._on_start_callback: Optional[Callable] = None
        self._on_finish_callback: Optional[Callable] = None
        self._on_stop_callback: Optional[Callable] = None

        # 不在主线程初始化引擎：COM 对象不能跨线程使用，
        # 主线程创建的引擎在 speak 子线程中无法使用，
        # 子线程会自行初始化需要的引擎。这里只检测可用性。
        self._backend = None
        try:
            import win32com.client
            self._backend = 'sapi'
        except ImportError:
            pass
        if self._backend is None:
            try:
                import pyttsx3
                self._backend = 'pyttsx3'
            except ImportError:
                pass

    def is_available(self) -> bool:
        """检查 TTS 是否可用"""
        return self._backend is not None

    def set_callbacks(self, on_start: Callable = None, on_finish: Callable = None, on_stop: Callable = None):
        """设置回调函数"""
        self._on_start_callback = on_start
        self._on_finish_callback = on_finish
        self._on_stop_callback = on_stop

    def speak(self, text: str) -> bool:
        """朗读文本

        如果正在朗读，此方法会返回 False。
        调用者需要先调用 stop() 停止当前朗读。

        Args:
            text: 要朗读的文本

        Returns:
            是否成功开始朗读
        """
        if not self.is_available() or not text:
            return False

        with self._lock:
            # 如果正在朗读，返回 False
            if self._state == TTSState.SPEAKING:
                return False

            self._stop_requested = False
            self._state = TTSState.SPEAKING

        def _speak_thread():
            thread_was_stopped = False
            try:
                # 优先使用 SAPI 后端（与 _init_engine 优先级一致）
                if self._backend == 'sapi':
                    # 初始化 COM
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

                        # 异步朗读 (SVSFlagsAsync = 1)
                        engine.Speak(text, 1)

                        # 等待完成或停止
                        while True:
                            if self._stop_requested:
                                try:
                                    engine.Speak("", 3)  # Purge all speech
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

                elif self._backend == 'pyttsx3':
                    # pyttsx3 在子线程中需要重新初始化
                    import pyttsx3
                    engine = pyttsx3.init()

                    # 保存引用以便 stop() 可以调用
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
        return True

    def stop(self):
        """停止朗读"""
        with self._lock:
            if self._state != TTSState.SPEAKING:
                return
            
            self._stop_requested = True
            
            # 对于 pyttsx3，直接调用引擎的 stop 方法
            if self._backend == 'pyttsx3' and hasattr(self, '_thread_engine') and self._thread_engine:
                try:
                    self._thread_engine.stop()
                except Exception:
                    pass

        # 调用停止回调
        if self._on_stop_callback:
            try:
                self._on_stop_callback()
            except Exception:
                pass

    def is_speaking(self) -> bool:
        """检查是否正在朗读"""
        with self._lock:
            return self._state == TTSState.SPEAKING

    def get_state(self) -> TTSState:
        """获取当前状态"""
        with self._lock:
            return self._state


def get_tts() -> TTSEngine:
    """获取全局 TTS 引擎实例"""
    return TTSEngine()