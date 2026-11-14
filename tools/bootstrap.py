"""运行时依赖自检与自动部署（安装程序与"修复"菜单都会调用）.

设计原则
--------
* 安装包里已经预置了全部依赖（离线可装）；
* 本脚本在安装结束时做一次导入自检，把结果写入 runtime/bootstrap.log；
* 如果发现某个包缺失（例如安装包被裁剪、用户误删），自动从 PyPI 下载对应的
  Windows wheel 并解包到 site-packages —— 不依赖 pip，因为 wheel 本身就是 zip。

用法::

    python tools/bootstrap.py            # 自检 + 缺失时自动补装
    python tools/bootstrap.py --check    # 只自检，返回码 0/1
    python tools/bootstrap.py --quiet    # 少输出
"""
from __future__ import annotations

import argparse
import io
import os
import platform
import sys
import zipfile
from typing import Dict, List, Tuple
from urllib.request import urlopen

#: 需要校验的包 -> PyPI 项目名
PACKAGES: Dict[str, str] = {
    "pygame": "pygame",
    "hid": "hidapi",
    "inputs": "inputs",
    "vgamepad": "vgamepad",
}

PYPI_JSON = "https://pypi.org/pypi/{name}/json"


def running_in_install_layout() -> Tuple[str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    install_root = os.path.dirname(here)
    site_packages = os.path.join(install_root, "runtime", "Lib", "site-packages")
    return install_root, site_packages


def check_import(name: str) -> Tuple[bool, str]:
    try:
        __import__(name)
        return True, "OK"
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        # vgamepad 在未安装 ViGEmBus 驱动时导入会抛 VIGEM_ERROR_BUS_NOT_FOUND：
        # 库本身是完整的，只是驱动缺失，这里不算依赖缺失。
        if "VIGEM_ERROR_BUS_NOT_FOUND" in message:
            return True, "库已安装（ViGEmBus 驱动未安装）"
        return False, message


def pick_wheel(package: str) -> str:
    """从 PyPI 选出适配当前解释器 / 平台的最高版本 wheel."""
    import json

    with urlopen(PYPI_JSON.format(name=package), timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    tags = wheel_tags()
    candidates = []
    for version, files in data.get("releases", {}).items():
        for file in files:
            filename = file.get("filename", "")
            if not filename.endswith(".whl") or file.get("yanked"):
                continue
            if any(part in filename for part in tags):
                candidates.append((file.get("upload_time", ""), filename, file["url"]))
    if not candidates:
        raise RuntimeError(f"{package}: 找不到适用于 {','.join(tags)} 的 wheel")
    candidates.sort()
    return candidates[-1][2]


def wheel_tags() -> List[str]:
    major, minor = sys.version_info[:2]
    machine = platform.machine().lower()
    arch = "win_amd64" if "64" in machine or machine == "amd64" else "win32"
    return [
        f"cp{major}{minor}-cp{major}{minor}-{arch}",
        f"-py3-none-{arch}",
        "-py3-none-any",
    ]


def install_wheel(url: str, site_packages: str) -> None:
    os.makedirs(site_packages, exist_ok=True)
    with urlopen(url, timeout=60) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(site_packages)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="依赖自检与部署")
    parser.add_argument("--check", action="store_true", help="只自检")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--offline", action="store_true", help="不联网补装")
    args = parser.parse_args(argv)

    install_root, site_packages = running_in_install_layout()
    log_lines: List[str] = []
    failures = 0

    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)

    for module, package in PACKAGES.items():
        ok, message = check_import(module)
        log_lines.append(f"[{'OK' if ok else 'MISSING'}] {module} ({package}): {message}")
        if ok:
            continue
        failures += 1
        if args.check or args.offline:
            continue
        try:
            url = pick_wheel(package)
            install_wheel(url, site_packages)
            ok, message = check_import(module)
            log_lines.append(f"[FIXED] {module}: {message} <- {os.path.basename(url)}")
            if ok:
                failures -= 1
        except Exception as exc:
            log_lines.append(f"[FAIL] {module}: 自动补装失败 {exc}")

    log_text = "\n".join(log_lines)
    if not args.quiet:
        print(log_text)
    try:
        log_path = os.path.join(install_root, "runtime", "bootstrap.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(log_text + "\n")
    except Exception:
        pass
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
