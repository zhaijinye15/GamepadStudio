"""程序入口：日志、DPI 适配、异常兜底与命令行参数."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import traceback

from . import APP_NAME, __version__
from .paths import logs_dir


def setup_logging(verbose: bool = False) -> None:
    handlers: list[logging.Handler] = []
    # pythonw.exe 下没有控制台，sys.stdout / stderr 为 None
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir() / "app.log", maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        handlers.append(file_handler)
    except Exception:
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def setup_dpi_awareness() -> None:
    """让窗口在 125%/150% 缩放的高分屏上保持清晰."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def render_screenshots(output_dir: str, demo: bool = False) -> int:
    """开发自检：把四个页面各渲染一张 PNG（无需真实手柄）."""
    import pygame

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from .gui.app import App

    os.makedirs(output_dir, exist_ok=True)
    app = App((1220, 800))
    if demo:
        _inject_demo_device(app)
    for tab in ("tester", "mapping", "rumble", "about"):
        app.tab = tab
        if demo and tab != "tester":
            _inject_demo_device(app)
        app._draw()
        pygame.image.save(app.ui.surface, os.path.join(output_dir, f"{tab}.png"))
    app.shutdown()
    print(f"已输出页面截图到 {output_dir}")
    return 0


def _inject_demo_device(app) -> None:
    """截图自检用：注入一个虚拟设备与一帧输入，验证高亮/数值渲染路径."""
    from .core.model import DeviceInfo, PadState

    info = DeviceInfo(
        key="demo:1", name="Xbox Wireless Controller", backend="sdl", layout="xbox",
        transport="bluetooth", buttons=11, axes=6, hats=1, rumble=("sdl",), instance_id=0,
        battery=0.72,
    )
    app.manager._devices = [info]
    app.selected_key = info.key
    app.rumble.set_device(info)

    state = PadState(
        buttons={f"b{i}": i in (0, 9, 12) for i in range(11)},
        axes={"a0": 0.42, "a1": -0.31, "a2": -0.12, "a3": 0.05, "a4": -1.0, "a5": 0.42},
        hats=(0, 0),
    )
    state.semantic_buttons = {"a": True, "lb": True, "down": True, "guide": False}
    state.semantic_axes = {"lx": 0.42, "ly": -0.31, "rx": -0.12, "ry": 0.05, "lt": 0.0, "rt": 0.71}
    app.pad_state = state
    app.prev_state = state
    app.poll_rate = 120.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Windows 手柄测试与按键映射工具")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    parser.add_argument("--screenshot", metavar="DIR", help="渲染各页面截图后退出（开发自检用）")
    parser.add_argument("--demo", action="store_true", help="配合 --screenshot：注入演示设备数据")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    log = logging.getLogger("gamepadstudio")
    log.info("启动 %s %s (Python %s)", APP_NAME, __version__, sys.version.split()[0])

    if args.screenshot:
        return render_screenshots(args.screenshot, demo=args.demo)

    setup_dpi_awareness()
    from .gui.app import App

    try:
        app = App()
        app.run()
    except Exception:
        log.exception("程序异常退出")
        try:
            import pygame
            pygame.quit()
        except Exception:
            pass
        _show_error_dialog(traceback.format_exc())
        return 1
    return 0


def _show_error_dialog(message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                message[-900:] + "\n\n详细日志：%APPDATA%\\GamepadStudio\\logs\\app.log",
                f"{APP_NAME} 出错",
                0x10,
            )
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
