"""一步构建 Windows 安装包。

流程：
1. 准备 Windows 可嵌入 Python（python-3.11.9-embed-amd64.zip）
2. 用 pip 的 --platform 能力把 Windows wheel 直接铺进 site-packages（可在 Linux/Windows 上构建）
3. 拷贝程序、字体、示例方案、文档、维护工具与 ViGEmBus 驱动安装包
4. 调用 makensis 生成安装程序

用法::

    python build/build_installer.py                # 全量构建
    python build/build_installer.py --skip-deps    # 复用已有 payload，只重打安装包
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CACHE = BUILD / "cache"
PAYLOAD = BUILD / "payload"
DIST = ROOT / "dist"

PYTHON_VERSION = "3.11.9"
PYTHON_ZIP = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"

VIGEM_ZIP = "ViGEmBus_1.22.0_x64_x86_arm64.exe"
VIGEM_URL = f"https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/{VIGEM_ZIP}"

WHEELS = ("pygame", "hidapi", "inputs")
VERSION = "1.3.0"


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def download(url: str, target: Path) -> Path:
    if target.exists() and target.stat().st_size > 0:
        log(f"缓存命中 {target.name}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"下载 {url}")
    with urllib.request.urlopen(url, timeout=120) as response, open(target, "wb") as handle:
        shutil.copyfileobj(response, handle)
    return target


def prepare_python_runtime() -> None:
    runtime = PAYLOAD / "runtime"
    if runtime.exists() and (runtime / "python311.dll").exists():
        log("runtime 已存在，跳过解包")
        return
    archive = download(PYTHON_URL, CACHE / PYTHON_ZIP)
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(runtime)
    # 让 embeddable 解释器能找到 site-packages
    (runtime / "python311._pth").write_text(
        "python311.zip\r\n.\r\nLib\\site-packages\r\nimport site\r\n", encoding="utf-8"
    )
    log("已解包 Windows 运行时")


def install_wheels() -> None:
    site_packages = PAYLOAD / "runtime" / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    if (site_packages / "pygame").is_dir():
        log("site-packages 已就绪，跳过 pip")
        return
    command = [
        sys.executable, "-m", "pip", "install", "--quiet",
        "--target", str(site_packages),
        "--platform", "win_amd64",
        "--python-version", "311",
        "--implementation", "cp",
        "--abi", "cp311",
        "--only-binary=:all:",
        *WHEELS,
    ]
    log("安装 Windows wheel：" + ", ".join(WHEELS))
    subprocess.run(command, check=True)


def install_vgamepad() -> None:
    target = PAYLOAD / "runtime" / "Lib" / "site-packages" / "vgamepad"
    if target.is_dir():
        return
    archive = CACHE / "vgamepad.tar.gz"
    if not archive.exists():
        import json
        with urllib.request.urlopen("https://pypi.org/pypi/vgamepad/json", timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        url = data["urls"][0]["url"]
        download(url, archive)
    with tarfile.open(archive) as tar:
        member_root = tar.getnames()[0].split("/")[0]
        for member in tar.getmembers():
            if "/vgamepad/" in member.name.replace(member_root, "", 1) or member.name.endswith("/vgamepad"):
                relative = member.name.split("vgamepad/", 1)[-1]
                if not relative:
                    continue
                destination = target / relative
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as source, open(destination, "wb") as handle:
                        shutil.copyfileobj(source, handle)
    log("已解包 vgamepad（纯 Python + ViGEmClient.dll）")


def copy_tree(source: Path, destination: Path, ignore_pycache: bool = True) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            if ignore_pycache and item.name == "__pycache__":
                continue
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(item, target, ignore_pycache)
        else:
            shutil.copy2(item, target)


def copy_application() -> None:
    app_dir = PAYLOAD / "app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    copy_tree(ROOT / "src" / "gamepadstudio", app_dir / "gamepadstudio")
    copy_tree(ROOT / "assets", app_dir / "assets")
    copy_tree(ROOT / "profiles", app_dir / "profiles")
    shutil.copy2(ROOT / "src" / "run_gamepad.py", app_dir / "run_gamepad.py")

    # 文档：先渲染 HTML，再整体拷进 app/docs（开始菜单快捷方式指向它）
    subprocess.run([sys.executable, str(ROOT / "docs" / "build_docs.py")], check=False)
    copy_tree(ROOT / "docs", app_dir / "docs")
    (app_dir / "docs" / "build_docs.py").unlink(missing_ok=True)
    shutil.copy2(ROOT / "LICENSE", app_dir / "docs" / "LICENSE.txt")

    tools_dir = PAYLOAD / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tools" / "bootstrap.py", tools_dir / "bootstrap.py")
    shutil.copy2(ROOT / "tools" / "check_env.bat", tools_dir / "check_env.bat")
    driver = download(VIGEM_URL, CACHE / VIGEM_ZIP)
    shutil.copy2(driver, tools_dir / "ViGEmBus_Setup.exe")
    log("已拷贝程序、文档与工具")


def build_installer() -> Path:
    makensis = shutil.which("makensis")
    if makensis is None:
        candidate = Path(r"C:\Program Files (x86)\NSIS\makensis.exe")
        makensis = str(candidate) if candidate.exists() else None
    if makensis is None:
        raise SystemExit("未找到 makensis：请先安装 NSIS 3.x（Windows: https://nsis.sourceforge.io/）")

    DIST.mkdir(parents=True, exist_ok=True)
    output = DIST / f"GamepadStudio-Setup-{VERSION}.exe"
    command = [
        makensis,
        "-V2",
        f"-DOUTFILE={output}",
        f"-DPAYLOAD={PAYLOAD}",
        str(ROOT / "installer" / "GamepadStudio.nsi"),
    ]
    log("调用 NSIS 编译安装程序…")
    started = time.time()
    subprocess.run(command, check=True, cwd=str(ROOT / "installer"))
    log(f"完成，用时 {time.time() - started:.1f}s")
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 Gamepad Studio 安装包")
    parser.add_argument("--skip-deps", action="store_true", help="复用 build/payload 中的运行时")
    args = parser.parse_args(argv)

    PAYLOAD.mkdir(parents=True, exist_ok=True)
    if not args.skip_deps:
        prepare_python_runtime()
        install_wheels()
        install_vgamepad()
        copy_application()
    else:
        copy_application()

    output = build_installer()
    size_mb = output.stat().st_size / 1024 / 1024
    log(f"安装包：{output} （{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
