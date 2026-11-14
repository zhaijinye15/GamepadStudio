"""安装版启动入口（runtime\\pythonw.exe app\\run_gamepad.py）.

兼容两种运行方式：
1. 安装目录：app/ 下同时存在 gamepadstudio 包与 assets/、profiles/；
2. 源码目录：src/gamepadstudio，直接 python -m gamepadstudio.main。
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    # 安装目录下把工作目录切到 app/，避免快捷方式继承奇怪的 CWD
    try:
        os.chdir(here)
    except Exception:
        pass

    from gamepadstudio.main import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
