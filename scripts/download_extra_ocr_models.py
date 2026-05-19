"""
下载韩文 PP-OCRv3 识别 ONNX 及对应字符字典（rapidocr-onnxruntime 需要 dict 解码 CTC）。

运行（在 QTranslator 根目录）:
  python scripts/download_extra_ocr_models.py

ONNX 下载顺序：ModelScope → Hugging Face → hf-mirror。
字典仅从 ModelScope 拉取（与 ONNX 同仓库，体积小）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "assets" / "rapidocr" / "models"
DICT_DIR = ROOT / "assets" / "rapidocr" / "dicts"

# (保存文件名, ModelScope 模型 ID, Hugging Face 下载地址)
SOURCES: list[tuple[str, str, str]] = [
    (
        "korean_PP-OCRv3_rec_infer.onnx",
        "cycloneboy/korean_PP-OCRv3_rec_infer",
        "https://huggingface.co/breezedeus/cnocr-ppocr-korean_PP-OCRv3/resolve/main/korean_PP-OCRv3_rec_infer.onnx",
    ),
]

# (字典文件名, ModelScope 模型 ID) — 须与 rapidocr_engine._DICT_BY_LANG 一致
DICT_SOURCES: list[tuple[str, str]] = [
    ("korean_dict.txt", "cycloneboy/korean_PP-OCRv3_rec_infer"),
]


def _modelscope_url(model_id: str, file_path: str) -> str:
    fp = quote(file_path, safe="")
    return (
        f"https://www.modelscope.cn/api/v1/models/{model_id}/repo"
        f"?Revision=master&FilePath={fp}"
    )


def _mirror_hf(url: str) -> str:
    if "huggingface.co/" in url:
        return url.replace("https://huggingface.co/", "https://hf-mirror.com/", 1)
    return url


def download_file(
    url: str,
    dest: Path,
    timeout: int = 300,
    min_size: int = 10240,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "QTranslator-ocr-downloader/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < min_size:
        raise ValueError(f"响应过小 ({len(data)} B)，可能为错误页")
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.write_bytes(data)
    tmp.replace(dest)


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    DICT_DIR.mkdir(parents=True, exist_ok=True)

    for name, ms_id, hf_primary in SOURCES:
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size > 10240:
            print(f"已存在，跳过: {dest.name}")
            continue
        last_err: Exception | None = None
        for url in (
            _modelscope_url(ms_id, "model.onnx"),
            hf_primary,
            _mirror_hf(hf_primary),
        ):
            try:
                print(f"下载: {dest.name}\n  源: {url[:100]}...")
                download_file(url, dest)
                print(f"  完成 ({dest.stat().st_size // 1024} KB)")
                break
            except Exception as e:
                last_err = e
                print(f"  失败: {e}")
                dest.with_suffix(dest.suffix + ".partial").unlink(missing_ok=True)
        else:
            print(f"失败 {name}: {last_err}", file=sys.stderr)
            return 1

    for dict_name, ms_id in DICT_SOURCES:
        dest = DICT_DIR / dict_name
        if dest.exists() and dest.stat().st_size > 200:
            print(f"已存在，跳过字典: {dest.name}")
            continue
        url = _modelscope_url(ms_id, dict_name)
        try:
            print(f"下载字典: {dict_name}\n  源: {url[:100]}...")
            download_file(url, dest, min_size=200)
            print(f"  完成 ({dest.stat().st_size // 1024} KB)")
        except Exception as e:
            print(f"失败 字典 {dict_name}: {e}", file=sys.stderr)
            return 1

    print("全部就绪。在设置 → 截图识字 中选择「韩文」即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
