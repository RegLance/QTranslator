"""RapidOCR：项目内 assets 模型，支持多语种识别（切换 rec 模型）。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

try:
    from ..utils.logger import log_debug, log_info
except ImportError:
    from src.utils.logger import log_debug, log_info

# 配置键 ocr.language 取值
OCR_LANGUAGE_CH_EN = "ch_en"
OCR_LANGUAGE_JAPANESE = "japanese"
OCR_LANGUAGE_KOREAN = "korean"
OCR_LANGUAGE_CYRILLIC = "cyrillic"

# 设置下拉顺序：(key, 显示名)
OCR_LANGUAGE_OPTIONS: List[Tuple[str, str]] = [
    (OCR_LANGUAGE_CH_EN, "中文 / English（默认）"),
    (OCR_LANGUAGE_JAPANESE, "日文"),
    (OCR_LANGUAGE_KOREAN, "韩文"),
    (OCR_LANGUAGE_CYRILLIC, "俄文（西里尔字母）"),
]

_DET_FILENAME = "ch_PP-OCRv3_det_infer.onnx"
_CLS_FILENAME = "ch_ppocr_mobile_v2.0_cls_infer.onnx"
_REC_BY_LANG = {
    OCR_LANGUAGE_CH_EN: "ch_PP-OCRv3_rec_infer.onnx",
    OCR_LANGUAGE_JAPANESE: "japan_PP-OCRv3_rec_infer.onnx",
    OCR_LANGUAGE_KOREAN: "korean_PP-OCRv3_rec_infer.onnx",
    OCR_LANGUAGE_CYRILLIC: "cyrillic_PP-OCRv3_rec_infer.onnx",
}

# 日文/韩文/俄文 rec 模型 ONNX 内无 character 元数据，须配套 Paddle 字典（每行一字）
_DICT_BY_LANG = {
    OCR_LANGUAGE_JAPANESE: "japan_dict.txt",
    OCR_LANGUAGE_KOREAN: "korean_dict.txt",
    OCR_LANGUAGE_CYRILLIC: "cyrillic_dict.txt",
}

_ocr_engine: Optional[Any] = None
_ocr_engine_lang: Optional[str] = None
_ocr_lock = threading.Lock()
_rapidocr_update_parameters_patched = False


def _apply_rapidocr_rec_keys_patch() -> None:
    """把 RapidOCR 识别配置里的 rec_keys_path 转为 Rec.keys_path。

    rapidocr_onnxruntime 1.2.x 在 ``UpdateParameters.update_rec_params`` 里处理参数；
    1.3+ 改为通用的 ``update_params``，不再有 ``update_rec_params``，
    在另一台电脑安装较新版本时会触发 ``has no attribute update_rec_params``。

    此处统一 monkey-patch ``UpdateParameters.__call__``，对返回的 config['Rec'] 做一次归一化，
    同时兼容 1.2 与 1.3+。
    """
    global _rapidocr_update_parameters_patched
    if _rapidocr_update_parameters_patched:
        return
    from rapidocr_onnxruntime.utils import UpdateParameters

    if not callable(getattr(UpdateParameters, "__call__", None)):
        log_debug("[OCR] UpdateParameters 无可包装 __call__，跳过 rec_keys_path 补丁")
        _rapidocr_update_parameters_patched = True
        return

    _orig_call = UpdateParameters.__call__

    def _call_wrapped(self, config, **kwargs):
        new_cfg = _orig_call(self, config, **kwargs)
        rec = new_cfg.get("Rec")
        if isinstance(rec, dict) and "rec_keys_path" in rec:
            rk = rec.pop("rec_keys_path")
            rec.setdefault("keys_path", rk)
        return new_cfg

    UpdateParameters.__call__ = _call_wrapped  # type: ignore[method-assign]
    _rapidocr_update_parameters_patched = True


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def models_dir() -> Path:
    return _bundle_root() / "assets" / "rapidocr" / "models"


def dicts_dir() -> Path:
    return _bundle_root() / "assets" / "rapidocr" / "dicts"


def resolve_ocr_language(config_value: Optional[str]) -> str:
    v = (config_value or OCR_LANGUAGE_CH_EN).strip().lower()
    if v in _REC_BY_LANG:
        return v
    return OCR_LANGUAGE_CH_EN


def expected_rec_filename(language_key: str) -> str:
    return _REC_BY_LANG.get(language_key, _REC_BY_LANG[OCR_LANGUAGE_CH_EN])


def invalidate_ocr_engine() -> None:
    """配置变更后丢弃缓存的引擎实例。"""
    global _ocr_engine, _ocr_engine_lang
    with _ocr_lock:
        _ocr_engine = None
        _ocr_engine_lang = None


def warmup_ocr_engine() -> None:
    """在主线程预加载 ONNX 引擎，避免 Windows 上在 QThread 内首次加载导致原生崩溃。"""
    try:
        get_ocr_engine()
    except Exception as e:
        log_debug(f"[OCR] 主线程预加载引擎失败（首次识别时会重试）: {e}")


def get_ocr_engine():
    """按当前配置语种懒加载 RapidOCR（检测/角度分类共用中文模型，仅替换识别模型）。"""
    global _ocr_engine, _ocr_engine_lang
    try:
        from ..config import get_config
    except ImportError:
        from src.config import get_config

    lang = resolve_ocr_language(get_config().get("ocr.language"))

    with _ocr_lock:
        if _ocr_engine is not None and _ocr_engine_lang == lang:
            return _ocr_engine

        md = models_dir()
        det = md / _DET_FILENAME
        cls_p = md / _CLS_FILENAME
        rec = md / _REC_BY_LANG[lang]
        for p in (det, cls_p, rec):
            if not p.is_file():
                raise FileNotFoundError(
                    f"缺少 OCR 模型文件: {p.name}（当前语种 {lang}）。"
                    f"若使用日文/韩文/俄文，请运行项目内 scripts/download_extra_ocr_models.py 下载对应 onnx 与字典。"
                )

        from rapidocr_onnxruntime import RapidOCR

        _apply_rapidocr_rec_keys_patch()

        kw: dict = {
            "det_model_path": str(det.resolve()),
            "rec_model_path": str(rec.resolve()),
            "cls_model_path": str(cls_p.resolve()),
            "print_verbose": False,
        }
        dict_name = _DICT_BY_LANG.get(lang)
        if dict_name:
            dpath = dicts_dir() / dict_name
            if not dpath.is_file():
                raise FileNotFoundError(
                    f"缺少 OCR 字典文件: {dict_name}（语种 {lang}）。"
                    f"请运行 scripts/download_extra_ocr_models.py 下载。"
                )
            # 由 _apply_rapidocr_rec_keys_patch 转为 Rec.keys_path
            kw["rec_keys_path"] = str(dpath.resolve())

        _ocr_engine = RapidOCR(**kw)
        _ocr_engine_lang = lang
        log_info(f"[OCR] RapidOCR 引擎实例已创建/缓存, language={lang}")
        return _ocr_engine


def qpixmap_to_rgb_numpy(pixmap) -> "object":
    """QPixmap -> RGB ndarray（必须在 Qt 主线程调用；结果可安全交给工作线程）。"""
    import cv2
    import numpy as np
    from PyQt6.QtCore import QBuffer, QIODevice

    img = pixmap.toImage()
    if img.isNull():
        raise ValueError("无效的图片")
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        raise ValueError("无效的图片尺寸")
    # 经 PNG 缓冲转码，避免 constBits().setsize() 越界导致堆损坏（Windows 0xC0000409）
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "PNG"):
        raise ValueError("QImage 编码失败")
    bgr = cv2.imdecode(np.frombuffer(bytes(buf.data()), np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("cv2 解码截图失败")
    return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _clamp_ocr_rgb(arr: "object") -> "object":
    """过大图在 ONNX 里易导致内存/原生异常，缩小后再识别。"""
    import cv2
    import numpy as np

    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    max_side = 4096
    max_pixels = 12_000_000
    if h * w <= max_pixels and max(h, w) <= max_side:
        return arr
    scale = min(max_side / max(h, w), (max_pixels / float(h * w)) ** 0.5, 1.0)
    nh = max(1, int(h * scale))
    nw = max(1, int(w * scale))
    return cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_AREA)


def _upscale_tiny_ocr_rgb(arr: "object") -> Tuple["object", float]:
    """过小截图检测模型往往 0 框，适当放大后再送 det/rec。

    Returns:
        (ndarray, scale_factor)  scale_factor > 1 表示已放大
    """
    import cv2
    import numpy as np

    arr = np.ascontiguousarray(arr)
    if arr.size == 0:
        return arr, 1.0
    h, w = int(arr.shape[0]), int(arr.shape[1])
    longest = max(h, w)
    shortest = min(h, w)
    # 经验值：长边远低于此的整行小字/小区域，det 常无输出（与用户 102×38 日志一致）
    target_long = 256
    target_short = 56
    scale = 1.0
    if longest > 0 and longest < target_long:
        scale = max(scale, min(target_long / float(longest), 6.0))
    if shortest > 0 and shortest < target_short:
        scale = max(scale, min(target_short / float(shortest), 6.0))
    if scale <= 1.001:
        return arr, 1.0
    nh = max(1, int(round(h * scale)))
    nw = max(1, int(round(w * scale)))
    up = cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_CUBIC)
    return up, scale


def run_ocr_on_rgb_numpy(arr: "object") -> str:
    """仅使用 numpy RGB 图像，可在后台线程调用（勿传 QPixmap）。"""
    orig_shape = getattr(arr, "shape", None)
    arr = _clamp_ocr_rgb(arr)
    clamped_shape = getattr(arr, "shape", None)
    if orig_shape != clamped_shape:
        log_info(f"[OCR] 大图已缩放: shape {orig_shape} -> {clamped_shape}")
    else:
        log_debug(f"[OCR] 识别输入 ndarray shape={clamped_shape}, dtype={getattr(arr, 'dtype', '?')}")
    arr, up_scale = _upscale_tiny_ocr_rgb(arr)
    if up_scale > 1.001:
        log_info(
            f"[OCR] 小图已放大: shape {clamped_shape} -> {getattr(arr, 'shape', None)}, "
            f"scale≈{up_scale:.2f}"
        )
    import numpy as np

    if not isinstance(arr, np.ndarray) or arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"OCR 输入须为 H×W×3 ndarray，当前 shape={getattr(arr, 'shape', None)}")
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8, copy=False)
    arr = np.ascontiguousarray(arr)

    log_info("[OCR] get_ocr_engine() …")
    engine = get_ocr_engine()
    log_info(f"[OCR] 开始推理 shape={arr.shape} …")
    result, _ = engine(arr)
    if not result:
        log_info("[OCR] 引擎返回空结果（未检测到文本行）")
        return ""
    text = "\n".join(item[1] for item in result)
    log_info(f"[OCR] 引擎返回 {len(result)} 行, 拼接文本长度 {len(text)}")
    return text


def run_ocr_on_qpixmap(pixmap) -> str:
    """主线程便捷封装（须在主线程调用）。"""
    return run_ocr_on_rgb_numpy(qpixmap_to_rgb_numpy(pixmap))
