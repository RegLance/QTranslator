"""
准备嵌入式 Node.js 运行时脚本

功能：
- 从 Node.js 官方下载 Windows x64 二进制文件
- 提取 node.exe 到 native/node/win-x64/node.exe
- 支持指定版本，默认 v20.12.0
- 记录版本信息到 native/node/version.txt

使用方法：
    python scripts/prepare_node_runtime.py
    python scripts/prepare_node_runtime.py --version v18.19.0
"""
import os
import sys
import zipfile
import hashlib
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
NATIVE_DIR = PROJECT_ROOT / "native"
NODE_DIR = NATIVE_DIR / "node" / "win-x64"

# 默认 Node.js 版本
DEFAULT_VERSION = "v20.12.0"

# Node.js 下载 URL 模板
NODE_DOWNLOAD_URL = "https://nodejs.org/dist/{version}/node-{version}-win-x64.zip"


def calculate_sha256(file_path: Path) -> str:
    """计算文件的 SHA256 哈希值"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def download_node_js(version: str, download_dir: Path) -> Path:
    """下载 Node.js Windows 二进制文件"""
    url = NODE_DOWNLOAD_URL.format(version=version)
    zip_path = download_dir / f"node-{version}-win-x64.zip"

    print(f"下载 URL: {url}")
    print(f"保存路径: {zip_path}")

    # 如果已存在，询问是否重新下载
    if zip_path.exists():
        print(f"文件已存在: {zip_path}")
        print("跳过下载（如需重新下载，请删除该文件）")
        return zip_path

    try:
        print("开始下载...")
        # 创建下载目录
        download_dir.mkdir(parents=True, exist_ok=True)

        # 下载文件
        urllib.request.urlretrieve(url, zip_path)
        print(f"下载完成: {zip_path}")
        print(f"文件大小: {zip_path.stat().st_size / 1024 / 1024:.2f} MB")

        return zip_path

    except urllib.error.URLError as e:
        print(f"下载失败: {e}")
        raise
    except Exception as e:
        print(f"下载出错: {e}")
        raise


def extract_node_exe(zip_path: Path, output_dir: Path) -> Path:
    """从 ZIP 文件中提取 node.exe"""
    output_dir.mkdir(parents=True, exist_ok=True)
    node_exe_path = output_dir / "node.exe"

    print(f"解压 ZIP 文件: {zip_path}")
    print(f"输出目录: {output_dir}")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # ZIP 内 node.exe 的路径: node-v20.12.0-win-x64/node.exe
            zip_internal_path = None
            for name in zip_ref.namelist():
                if name.endswith('node.exe') and 'node.exe' in name.split('/')[-1]:
                    zip_internal_path = name
                    break

            if not zip_internal_path:
                raise FileNotFoundError("ZIP 文件中未找到 node.exe")

            print(f"ZIP 内路径: {zip_internal_path}")

            # 提取 node.exe
            with zip_ref.open(zip_internal_path) as source:
                with open(node_exe_path, 'wb') as target:
                    target.write(source.read())

        print(f"提取完成: {node_exe_path}")
        print(f"node.exe 大小: {node_exe_path.stat().st_size / 1024 / 1024:.2f} MB")

        return node_exe_path

    except zipfile.BadZipFile as e:
        print(f"ZIP 文件损坏: {e}")
        raise
    except Exception as e:
        print(f"解压出错: {e}")
        raise


def write_version_info(version: str, node_dir: Path):
    """写入版本信息文件"""
    version_file = node_dir.parent / "version.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)

    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(f"{version}\n")
        f.write(f"下载时间: {os.popen('date /t & time /t').read().strip()}\n")

    print(f"版本信息已写入: {version_file}")


def verify_node_exe(node_exe_path: Path) -> bool:
    """验证 node.exe 是否可执行"""
    if not node_exe_path.exists():
        print(f"node.exe 不存在: {node_exe_path}")
        return False

    try:
        import subprocess
        result = subprocess.run(
            [str(node_exe_path), '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"node.exe 版本: {result.stdout.strip()}")
            return True
        else:
            print(f"node.exe 执行失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"验证出错: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='准备嵌入式 Node.js 运行时')
    parser.add_argument('--version', default=DEFAULT_VERSION,
                        help=f'Node.js 版本 (默认: {DEFAULT_VERSION})')
    parser.add_argument('--keep-zip', action='store_true',
                        help='保留下载的 ZIP 文件')
    args = parser.parse_args()

    version = args.version
    print(f"Node.js 版本: {version}")
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"输出目录: {NODE_DIR}")
    print()

    # 检查是否已存在
    node_exe = NODE_DIR / "node.exe"
    if node_exe.exists():
        print(f"node.exe 已存在: {node_exe}")
        if verify_node_exe(node_exe):
            print("验证成功，无需重新下载")
            return 0
        else:
            print("验证失败，将重新下载")

    # 下载目录
    download_dir = PROJECT_ROOT / "downloads"

    try:
        # 下载 Node.js
        zip_path = download_node_js(version, download_dir)

        # 提取 node.exe
        extract_node_exe(zip_path, NODE_DIR)

        # 写入版本信息
        write_version_info(version, NODE_DIR)

        # 验证
        node_exe = NODE_DIR / "node.exe"
        if verify_node_exe(node_exe):
            print()
            print("=" * 50)
            print("准备完成!")
            print(f"node.exe 位置: {node_exe}")
            print("=" * 50)
        else:
            print("验证失败!")
            return 1

        # 清理 ZIP 文件（除非指定保留）
        if not args.keep_zip:
            print(f"清理 ZIP 文件: {zip_path}")
            zip_path.unlink()
            # 如果下载目录为空，删除它
            try:
                download_dir.rmdir()
            except OSError:
                pass

        return 0

    except Exception as e:
        print(f"准备失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())