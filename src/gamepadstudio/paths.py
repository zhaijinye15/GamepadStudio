"""运行期路径与用户数据目录.

安装版目录结构（NSIS 生成的布局）::

    Gamepad Studio/
        runtime/          内嵌 Python 3.11 (pythonw.exe)
        app/gamepadstudio/ 源码包
        app/assets/        字体与图标
        app/profiles/      示例映射方案
        tools/            ViGEmBus 安装包等
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "GamepadStudio"


def app_root() -> Path:
    """可执行文件所在目录（frozen 时为 exe 目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def asset_path(*parts: str) -> Path:
    """定位随程序分发的静态资源（字体、图标、示例配置）。"""
    root = app_root()
    candidates = [root / "assets", root.parent / "assets", root / "app" / "assets"]
    for base in candidates:
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    # 返回首选路径，交由调用方降级处理
    return candidates[0].joinpath(*parts)


def bundled_profiles_dir() -> Path:
    root = app_root()
    for base in (root / "profiles", root.parent / "profiles", root / "app" / "profiles"):
        if base.is_dir():
            return base
    return root / "profiles"


def user_data_dir() -> Path:
    """用户数据目录：%APPDATA%\\GamepadStudio（便携模式下用程序目录 data/）。"""
    override = os.environ.get("GAMEPADSTUDIO_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_DIR_NAME
    else:
        base = Path.home() / ".config" / APP_DIR_NAME
    for sub in ("profiles", "logs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def profiles_dir() -> Path:
    return user_data_dir() / "profiles"


def logs_dir() -> Path:
    return user_data_dir() / "logs"


def settings_file() -> Path:
    return user_data_dir() / "settings.json"
