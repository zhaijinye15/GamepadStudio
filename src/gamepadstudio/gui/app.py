"""应用外壳：窗口、主循环、侧边栏、状态栏与各页面调度."""
from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

import pygame

from .. import __version__
from ..core.calibration import DeviceCalibration
from ..core.community import CommunityClient
from ..core.device_manager import DeviceManager
from ..core.device_profile import ProfileStore
from ..core.game_library import GameLibrary
from ..core.mapping import BindingRuntime, MappingProfile, load_builtin_profiles
from ..core.model import PadState
from ..core.poll_stats import PollStats
from ..core.rumble import RumbleEngine
from ..core.virtual_pad import VirtualPad, availability as vigem_availability
from ..paths import asset_path, bundled_profiles_dir, logs_dir, profiles_dir, user_data_dir
from ..platform.win_dialog import open_json, save_csv, save_json
from ..platform.win_keyboard import KeyboardInjector
from ..settings import load_settings, save_settings
from . import theme
from .theme import Fonts
from .widgets import UI

log = logging.getLogger(__name__)

SIDEBAR_WIDTH = 244
FOOTER_HEIGHT = 34
HEADER_HEIGHT = 68
MIN_SIZE = (1000, 640)
DEFAULT_SIZE = (1220, 800)

TABS = (("tester", "测试台"), ("library", "游戏库"), ("community", "社区"),
        ("calibration", "摇杆校准"), ("model3d", "3D 模型"), ("mapping", "按键映射"),
        ("stats", "轮询统计"), ("rumble", "震动测试"), ("about", "关于"))


class App:
    def __init__(self, size=None) -> None:
        pygame.init()
        pygame.key.set_repeat(0)
        pygame.display.set_caption("Gamepad Studio · 手柄测试与映射")
        icon_path = asset_path("icon.png")
        if icon_path.exists():
            try:
                pygame.display.set_icon(pygame.image.load(str(icon_path)))
            except Exception:
                pass
        size = self._fit_to_display(size)
        self.size = size
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.fonts = Fonts()
        self.ui = UI(size, self.fonts)
        self.settings = load_settings()

        self.manager = DeviceManager()
        self.manager.start()
        # 丢弃初始化期间 SDL 压入队列的设备热插拔事件：
        # pygame 在 joystick 重复 init 后可能重建内部实例表，残留的
        # JOYDEVICEADDED 事件会在下一次 event.get() 里抛 KeyError: 0。
        try:
            pygame.event.clear()
        except Exception:
            pass
        self.rumble = RumbleEngine(self.manager)
        self.injector = KeyboardInjector()
        self.virtual_pad = VirtualPad("virtual_xbox360")
        self.vigem_ok, self.vigem_message = vigem_availability()

        self.selected_key: Optional[str] = None
        self.pad_state: Optional[PadState] = None
        self.prev_state: Optional[PadState] = None
        self.state_age = 0.0
        self.recent_events: List[tuple[float, str]] = []
        self.poll_rate = 0.0
        self._poll_counter = 0
        self._poll_window = time.monotonic()
        self.profile = MappingProfile()
        self.profile_dirty = False
        self.profile_path = ""
        # 连发 / 切换 / 宏序列运行时，以及轮询稳定性统计
        self.binding_runtime = BindingRuntime()
        self.poll_stats = PollStats()
        self._last_poll_time: Optional[float] = None
        self._last_dt = 1.0 / 60.0
        # 校准与方案库：按手柄保存死区/曲线/行程，插上自动匹配加载
        self.calibration = DeviceCalibration()
        self.calibration.reset()
        self.cal_store = ProfileStore(user_data_dir() / "calibrations")
        self.calibration_dirty = False
        self.raw_semantic = {}
        # 游戏库：桌面游戏扫描结果缓存 + MuMu 模拟器手游
        self.library = GameLibrary(user_data_dir() / "game_library.json")
        self.game_launching = ""
        # 社区：token 存在 %APPDATA%\GamepadStudio\community.json
        self.community = CommunityClient(user_data_dir() / "community.json")
        self.status_message = "就绪"
        self.status_until = 0.0
        self._event_error_logged = False
        self.running = True
        self.tab = "tester"
        self._last_refresh = 0.0
        self._last_state_signature: Optional[tuple] = None

        builtin = load_builtin_profiles(bundled_profiles_dir())
        if builtin:
            self.profile = builtin[0]
            self.status_message = f"已载入示例方案：{self.profile.name}"
        self._select_first_device()

        from .screens.about import AboutScreen
        from .screens.calibration import CalibrationScreen
        from .screens.community import CommunityScreen
        from .screens.library import LibraryScreen
        from .screens.mapping import MappingScreen
        from .screens.model3d import Model3DScreen
        from .screens.rumble import RumbleScreen
        from .screens.stats import StatsScreen
        from .screens.tester import TesterScreen

        self.screens = {
            "tester": TesterScreen(self),
            "library": LibraryScreen(self),
            "community": CommunityScreen(self),
            "calibration": CalibrationScreen(self),
            "model3d": Model3DScreen(self),
            "mapping": MappingScreen(self),
            "stats": StatsScreen(self),
            "rumble": RumbleScreen(self),
            "about": AboutScreen(self),
        }

    def _fit_to_display(self, requested=None) -> tuple[int, int]:
        """窗口尺寸自适应：默认 1220×800，屏幕较小时收缩但保持最小可用尺寸."""
        width, height = requested or DEFAULT_SIZE
        try:
            info = pygame.display.Info()
            desktop = (info.current_w, info.current_h)
        except Exception:
            desktop = (0, 0)
        if desktop[0] > 200 and desktop[1] > 200:
            width = min(width, desktop[0] - 60)
            height = min(height, desktop[1] - 90)
        width = max(MIN_SIZE[0], width)
        height = max(MIN_SIZE[1], height)
        return width, height

    # ------------------------------------------------------------------ 设备
    def _select_first_device(self) -> None:
        devices = self.manager.devices
        if devices and self.selected_key is None:
            self.select_device(devices[0].key)

    def select_device(self, key: str) -> None:
        self.selected_key = key
        self.pad_state = None
        self.prev_state = None
        self._last_poll_time = None
        self.binding_runtime.reset()
        device = self.manager.find(key)
        self.rumble.set_device(device)
        if device is not None:
            self.log_event(f"已选择手柄：{device.name}")
            self._auto_load_calibration(device)

    def _auto_load_calibration(self, device) -> None:
        """插上/切到某手柄时，自动套用它之前保存的校准方案."""
        profile = self.cal_store.match(device)
        if profile is None:
            self.calibration = DeviceCalibration()
            self.calibration.reset()
            self.calibration_dirty = False
            return
        self.calibration = profile.calibration
        self.calibration_dirty = False
        self.set_status(f"已自动载入校准方案：{profile.label or profile.device_name}")

    @property
    def device(self):
        return self.manager.find(self.selected_key) if self.selected_key else None

    def log_event(self, text: str) -> None:
        self.recent_events.insert(0, (time.monotonic(), text))
        del self.recent_events[8:]

    def set_status(self, message: str, seconds: float = 3.0) -> None:
        self.status_message = message
        self.status_until = time.monotonic() + seconds

    # ------------------------------------------------------------------ 校准方案
    def mark_calibration_dirty(self) -> None:
        self.calibration_dirty = True

    def save_calibration_profile(self, label: str = "") -> None:
        device = self.device
        if device is None:
            self.set_status("没有选中手柄，无法保存方案")
            return
        profile = self.cal_store.upsert_for_device(device, self.calibration, label)
        if profile is None:
            self.set_status("方案保存失败（目录不可写）", 4.0)
            return
        self.calibration_dirty = False
        self.set_status(f"已保存方案：{profile.label or device.name}")

    def export_calibration(self) -> None:
        device = self.device
        if device is None:
            self.set_status("没有选中手柄")
            return
        default_name = f"{(device.name or 'gamepad').replace(' ', '-')}-calibration.json"
        path = save_json(default_name, "导出校准方案")
        if path is None:
            return
        profile = self.cal_store.upsert_for_device(device, self.calibration,
                                                  self.calibration_label(device))
        ok = profile is not None and self.cal_store.export_file(profile, path)
        self.calibration_dirty = False
        self.set_status(f"已导出到 {path}" if ok else "导出失败", 4.0)

    def import_calibration(self) -> None:
        path = open_json("导入校准方案")
        if path is None:
            return
        try:
            imported = self.cal_store.import_file(path)
        except Exception as exc:
            self.set_status(f"导入失败：{exc}", 5.0)
            return
        if not imported:
            self.set_status("文件里没有可用的方案", 4.0)
            return
        self.calibration = imported[0].calibration
        self.calibration_dirty = False
        self.set_status(f"已导入 {len(imported)} 份方案，并载入 {imported[0].label}", 4.0)

    def calibration_label(self, device) -> str:
        profile = self.cal_store.match(device)
        return (profile.label if profile and profile.label else "") or device.name

    # ------------------------------------------------------------------ 主循环
    def run(self) -> None:
        # 进入主循环前清一次事件队列：SDL 在初始化/枚举设备时可能压入
        # 与内部实例表不一致的热插拔事件，pygame 翻译它时会抛 KeyError。
        try:
            pygame.event.clear()
        except Exception:
            pass
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self._handle_events()
            self._update(dt)
            self._draw()
            pygame.display.flip()
        self.shutdown()

    def shutdown(self) -> None:
        try:
            self.rumble.stop()
            self.injector.release_all()
            self.virtual_pad.close()
            self.manager.stop()
        except Exception:
            pass
        save_settings(self.settings)
        pygame.quit()

    def _handle_events(self) -> None:
        mouse_pressed = mouse_released = False
        wheel = 0
        events = []
        try:
            batch = pygame.event.get()
        except Exception:
            # pygame 的 C 层把设备事件翻译成 Python 对象时可能抛 SystemError
            #（内部异常为 KeyError: 0）。丢弃这一帧并清队列，随后事件流即恢复。
            if not self._event_error_logged:
                log.warning("SDL 事件队列初次同步失败，已丢弃该帧事件并继续运行")
                self._event_error_logged = True
            try:
                pygame.event.clear()
            except Exception:
                pass
            batch = []
        for event in batch:
            events.append(event)
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.VIDEORESIZE:
                width = max(MIN_SIZE[0], event.w)
                height = max(MIN_SIZE[1], event.h)
                self.size = (width, height)
                self.screen = pygame.display.set_mode(self.size, pygame.RESIZABLE)
                self.ui.size = self.size
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pressed = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mouse_released = True
            elif event.type == pygame.MOUSEWHEEL:
                wheel += event.y
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F5:
                self.manager.refresh(force=True)
                self.set_status("已刷新设备列表")
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pass  # ESC 交给控件层处理（关闭输入框 / 取消捕获）
            elif event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                self.manager.refresh(force=True)
                self._select_first_device()

        mouse_pos = pygame.mouse.get_pos()
        mouse_down = pygame.mouse.get_pressed()[0]
        self.ui.begin(self.screen, mouse_pos, mouse_down, mouse_pressed, mouse_released, wheel)
        for event in events:
            self.ui.feed_event(event)
            handler = getattr(self.screens[self.tab], "handle_event", None)
            if callable(handler):
                handler(event)

    def _update(self, dt: float) -> None:
        now = time.monotonic()
        if now - self._last_refresh > 0.9:
            self.manager.refresh()
            self._last_refresh = now
            devices = self.manager.devices
            if self.selected_key and self.manager.find(self.selected_key) is None:
                self.selected_key = None
                self.rumble.set_device(None)
                self.log_event("手柄已断开")
            if self.selected_key is None and devices:
                self.select_device(devices[0].key)

        device = self.device
        if device is not None:
            self.prev_state = self.pad_state
            state = self.manager.poll(device)
            if state is not None:
                # 先留一份"校准前"的语义轴给校准页采样用，再套用校准结果
                self.raw_semantic = dict(state.semantic_axes)
                state.semantic_axes = self.calibration.apply_axes(self.raw_semantic)
                self.pad_state = state
                self.state_age = 0.0
                self._poll_counter += 1
                if self._last_poll_time is not None:
                    self.poll_stats.record((now - self._last_poll_time) * 1000.0)
                self._last_poll_time = now
                self._detect_events(state)
            else:
                self.state_age += dt
        else:
            self.pad_state = None
            self._last_poll_time = None
            self.binding_runtime.reset()

        self._last_dt = dt
        self._poll_rate_update(now)
        self.rumble.tick()
        screen = self.screens[self.tab]
        update = getattr(screen, "update", None)
        if callable(update):
            update(dt)
        self._apply_output(dt)

    def _poll_rate_update(self, now: float) -> None:
        if now - self._poll_window >= 1.0:
            self.poll_rate = self._poll_counter / (now - self._poll_window)
            self._poll_counter = 0
            self._poll_window = now

    def _detect_events(self, state: PadState) -> None:
        previous = self.prev_state
        if previous is None:
            return
        labels = {"a": "A", "b": "B", "x": "X", "y": "Y", "lb": "LB", "rb": "RB",
                  "lt": "LT", "rt": "RT", "up": "↑", "down": "↓", "left": "←", "right": "→",
                  "back": "Back", "start": "Start", "guide": "Guide", "l3": "L3", "r3": "R3"}
        for name, pressed in state.semantic_buttons.items():
            if pressed and not previous.semantic_buttons.get(name, False):
                self.log_event(f"按下 {labels.get(name, name.upper())}")
        if abs(state.axis("lt") - previous.axis("lt")) > 0.3:
            self.log_event(f"LT 行程 {state.axis('lt'):.2f}")

    def _apply_output(self, dt: float = 0.0) -> None:
        """根据映射方案决定是否向系统输出（默认关闭，避免误操作）."""
        if not self.settings.get("output_enabled") or self.pad_state is None:
            self.binding_runtime.reset()
            self.injector.update([])
            if self.virtual_pad.is_open:
                self.virtual_pad.reset()
            return
        target = self.profile.target
        outputs = self.binding_runtime.evaluate(self.profile, self.pad_state, dt or self._last_dt)
        if target == "keyboard":
            self.injector.update(outputs.keys())
        elif target.startswith("virtual"):
            if not self.virtual_pad.is_open:
                self.virtual_pad.kind = target
                self.virtual_pad.open()
            axes = self.profile.resolved_axes(self.pad_state)
            self.virtual_pad.apply(outputs, axes, {"lt": axes["lt"], "rt": axes["rt"]})

    # ------------------------------------------------------------------ 轮询统计
    def reset_poll_stats(self) -> None:
        self.poll_stats.reset()
        self._last_poll_time = None
        self.set_status("轮询统计已清零")

    def export_poll_csv(self) -> None:
        if self.poll_stats.samples <= 0:
            self.set_status("还没有采样数据，先连接手柄跑几秒", 4.0)
            return
        path = save_csv("poll-stats.csv", "导出轮询统计 CSV")
        if path is None:
            return
        ok = self.poll_stats.export_csv(path)
        self.set_status(f"已导出到 {path}" if ok else "导出失败（目标目录不可写）", 5.0)

    # ------------------------------------------------------------------ 游戏库
    def scan_games(self) -> None:
        """后台扫描本机游戏；扫描期间界面不阻塞."""
        if self.library.scanning:
            return
        self.library.scanning = True
        self.set_status("正在扫描本机游戏…", 8.0)

        def worker() -> None:
            try:
                count = self.library.scan()
                self.set_status(f"扫描完成：{count} 条（含手游）", 4.0)
            except Exception as exc:
                log.warning("游戏库扫描失败：%s", exc)
                self.set_status(f"扫描失败：{exc}", 6.0)
            finally:
                self.library.scanning = False

        threading.Thread(target=worker, name="game-scan", daemon=True).start()

    def refresh_android_games(self) -> None:
        if self.library.mumu is None:
            self.set_status("没有检测到 MuMu 模拟器", 4.0)
            return
        self.set_status("正在重扫手游…", 6.0)

        def worker() -> None:
            try:
                count = self.library.refresh_android()
                self.set_status(f"手游：{count} 个" if count else "MuMu 里还没装手游，或模拟器未进入安卓桌面", 5.0)
            except Exception as exc:
                self.set_status(f"重扫失败：{exc}", 5.0)

        threading.Thread(target=worker, name="android-scan", daemon=True).start()

    def start_mumu(self) -> None:
        if self.library.mumu is None:
            self.set_status("没有检测到 MuMu 模拟器", 4.0)
            return
        self.set_status("正在启动 MuMu…", 10.0)

        def worker() -> None:
            try:
                ok, message = self.library.ensure_mumu(on_step=lambda text: self.set_status(text, 10.0))
                if ok:
                    count = self.library.refresh_android()
                    self.set_status(f"MuMu 已就绪，找到 {count} 个手游", 5.0)
                else:
                    self.set_status(message, 8.0)
            except Exception as exc:
                self.set_status(f"启动 MuMu 失败：{exc}", 8.0)

        threading.Thread(target=worker, name="mumu-launch", daemon=True).start()

    # ------------------------------------------------------------------ 社区
    def community_auth(self, username: str, password: str, register: bool) -> None:
        """注册 / 登录都走后台线程，失败原因回写界面."""
        screen = self.screens.get("community")
        if screen is None:
            return
        screen.busy = "reg" if register else "login"
        screen.error = ""
        screen.hint = ""

        def worker() -> None:
            try:
                if register:
                    data = self.community.register(username, password)
                    screen.hint = f"注册成功：UID {data['user']['uid']}，已自动登录"
                    self.set_status(f"社区注册成功，UID {data['user']['uid']}", 5.0)
                else:
                    data = self.community.login(username, password)
                    screen.hint = f"登录成功：UID {data['user']['uid']}"
                    self.set_status(f"社区登录成功，UID {data['user']['uid']}", 5.0)
                screen.password = ""
                self.community_refresh()
            except Exception as exc:
                screen.error = str(exc)
                self.set_status(f"社区操作失败：{exc}", 6.0)
            finally:
                screen.busy = ""

        threading.Thread(target=worker, name="community-auth", daemon=True).start()

    def community_refresh(self) -> None:
        screen = self.screens.get("community")
        if screen is None or not self.community.logged_in:
            return
        screen.busy = "refresh"

        def worker() -> None:
            try:
                posts = self.community.list_posts(30)
                screen.posts = posts
                screen.loaded = True
                screen.error = ""
            except Exception as exc:
                screen.error = str(exc)
            finally:
                screen.busy = ""

        threading.Thread(target=worker, name="community-refresh", daemon=True).start()

    def community_post(self, title: str, content: str) -> None:
        screen = self.screens.get("community")
        if screen is None:
            return
        title, content = title.strip(), content.strip()
        if not title or not content:
            screen.error = "标题和正文都要写一点"
            return
        screen.busy = "post"

        def worker() -> None:
            try:
                self.community.create_post(title, content)
                screen.title = ""
                screen.content = ""
                screen.hint = "发布成功"
                screen.posts = self.community.list_posts(30)
                self.set_status("帖子已发布", 4.0)
            except Exception as exc:
                screen.error = str(exc)
            finally:
                screen.busy = ""

        threading.Thread(target=worker, name="community-post", daemon=True).start()

    def community_like(self, post_id: int) -> None:
        screen = self.screens.get("community")
        if screen is None or not post_id:
            return
        screen.busy = "like"

        def worker() -> None:
            try:
                liked, total = self.community.like(post_id)
                for post in screen.posts:
                    if int(post.get("id", 0)) == post_id:
                        post["likes"] = total
                        break
                screen.hint = "已点赞" if liked else "已取消点赞"
            except Exception as exc:
                screen.error = str(exc)
            finally:
                screen.busy = ""

        threading.Thread(target=worker, name="community-like", daemon=True).start()

    def launch_game(self, entry) -> None:
        """游戏/手游启动：全部放到后台线程，避免等待模拟器时卡住界面."""
        self.game_launching = entry.name
        self.set_status(f"正在启动 {entry.name}…", 6.0)

        def worker() -> None:
            try:
                ok, message = self.library.launch(entry)
                self.set_status(message, 6.0 if ok else 8.0)
                if ok:
                    self.log_event(f"启动游戏：{entry.name}")
            except Exception as exc:
                self.set_status(f"启动失败：{exc}", 8.0)
            finally:
                self.game_launching = ""

        threading.Thread(target=worker, name="game-launch", daemon=True).start()

    # ------------------------------------------------------------------ 绘制
    def _draw(self) -> None:
        surface = self.ui.surface
        surface.fill(theme.BG)
        self._draw_sidebar()
        self._draw_header()
        body = pygame.Rect(SIDEBAR_WIDTH, HEADER_HEIGHT + 12,
                           self.size[0] - SIDEBAR_WIDTH, self.size[1] - HEADER_HEIGHT - FOOTER_HEIGHT - 24)
        self.screens[self.tab].draw(self.ui, body)
        self._draw_footer()
        self.ui.draw_overlays()
        self.ui.draw_tooltip()
        self.ui.end()

    def _draw_sidebar(self) -> None:
        ui, surface = self.ui, self.ui.surface
        pygame.draw.rect(surface, theme.SIDEBAR, pygame.Rect(0, 0, SIDEBAR_WIDTH, self.size[1]))
        pygame.draw.line(surface, theme.BORDER_SOFT, (SIDEBAR_WIDTH - 1, 0), (SIDEBAR_WIDTH - 1, self.size[1]))

        # Logo
        logo_rect = pygame.Rect(20, 20, 42, 42)
        theme.rounded_rect(surface, logo_rect, theme.ACCENT, radius=12)
        pygame.draw.circle(surface, theme.SIDEBAR, (logo_rect.centerx - 7, logo_rect.centery), 6)
        pygame.draw.circle(surface, theme.SIDEBAR, (logo_rect.centerx + 7, logo_rect.centery), 6)
        pygame.draw.line(surface, theme.SIDEBAR, (logo_rect.centerx - 7, logo_rect.centery),
                         (logo_rect.centerx + 7, logo_rect.centery), 2)
        theme.draw_text(surface, self.fonts.get(16, bold=True), "GAMEPAD", (72, 24), theme.TEXT)
        theme.draw_text(surface, self.fonts.get(11), "S T U D I O", (73, 44), theme.TEXT_MUTED)

        # 导航
        y = 84
        spacing = 42 if len(TABS) >= 9 else (46 if len(TABS) > 7 else 50)
        for key, label in TABS:
            rect = pygame.Rect(16, y, SIDEBAR_WIDTH - 32, 40)
            active = self.tab == key
            if active:
                theme.rounded_rect(surface, rect, theme.PANEL_ALT, radius=10, border=theme.BORDER)
                pygame.draw.rect(surface, theme.ACCENT, pygame.Rect(rect.x, rect.y + 10, 3, rect.height - 20),
                                 border_radius=2)
            elif rect.collidepoint(ui.mouse):
                theme.rounded_rect(surface, rect, (22, 27, 35), radius=10)
            font = self.fonts.get(14, bold=active)
            theme.draw_text(surface, font, label, (rect.x + 18, rect.centery),
                            theme.TEXT if active else theme.TEXT_DIM, align="midleft")
            _, clicked = ui._hit(f"nav_{key}", rect)
            if clicked:
                self.tab = key
            y += spacing

        # 设备列表
        y += 18
        theme.draw_text(surface, self.fonts.get(11, bold=True), "手 柄 设 备",
                        (20, y), theme.TEXT_MUTED)
        refresh_rect = pygame.Rect(SIDEBAR_WIDTH - 76, y - 6, 56, 24)
        if ui.button("sidebar_refresh", refresh_rect, "刷新", kind="ghost", font_size=11):
            self.manager.refresh(force=True)
            self._select_first_device()
            self.set_status("已刷新设备列表")
        y += 30

        devices = self.manager.devices
        if not devices:
            note = pygame.Rect(16, y, SIDEBAR_WIDTH - 32, 96)
            theme.rounded_rect(surface, note, (22, 27, 35), radius=10, border=theme.BORDER_SOFT)
            theme.draw_text(surface, self.fonts.get(13, bold=True), "未检测到手柄",
                            (note.centerx, note.y + 26), theme.TEXT_DIM, align="center")
            small = self.fonts.get(11)
            theme.draw_text(surface, small, "USB 直连或蓝牙配对后", (note.centerx, note.y + 48),
                            theme.TEXT_MUTED, align="center")
            theme.draw_text(surface, small, "按 F5 或点刷新重试", (note.centerx, note.y + 66),
                            theme.TEXT_MUTED, align="center")
        else:
            for index, device in enumerate(devices):
                rect = pygame.Rect(16, y, SIDEBAR_WIDTH - 32, 52)
                selected = device.key == self.selected_key
                if ui.list_row(f"dev_{device.key}", rect, theme.ellipsize(
                        self.fonts.get(13), device.name, rect.width - 40), selected,
                        f"{device.describe_transport()} · {device.describe_layout()}"):
                    self.select_device(device.key)
                pygame.draw.circle(surface, theme.ACCENT if selected else theme.TEXT_MUTED,
                                   (rect.right - 14, rect.y + 16), 4)
                y += 58

        # 底部后端状态
        bottom = self.size[1] - FOOTER_HEIGHT - 100
        pygame.draw.line(surface, theme.BORDER_SOFT, (16, bottom - 14), (SIDEBAR_WIDTH - 16, bottom - 14))
        theme.draw_text(surface, self.fonts.get(11, bold=True), "运 行 环 境",
                        (20, bottom), theme.TEXT_MUTED)
        rows = [
            ("SDL2 / pygame", self.manager.sdl.available),
            ("hidapi（Nintendo）", self.manager.hid.available),
            ("ViGEmBus 虚拟手柄", self.vigem_ok),
        ]
        yy = bottom + 22
        for label, ok in rows:
            pygame.draw.circle(surface, theme.ACCENT if ok else theme.TEXT_MUTED, (24, yy + 8), 4)
            theme.draw_text(surface, self.fonts.get(12), label, (38, yy), theme.TEXT_DIM)
            yy += 26

    def _draw_header(self) -> None:
        ui, surface = self.ui, self.ui.surface
        width = self.size[0] - SIDEBAR_WIDTH
        pygame.draw.rect(surface, theme.BG, pygame.Rect(SIDEBAR_WIDTH, 0, width, HEADER_HEIGHT))
        pygame.draw.line(surface, theme.BORDER_SOFT, (SIDEBAR_WIDTH, HEADER_HEIGHT - 1),
                         (self.size[0], HEADER_HEIGHT - 1))
        title = dict(TABS)[self.tab]
        theme.draw_text(surface, self.fonts.get(22, bold=True), title, (SIDEBAR_WIDTH + 24, 22), theme.TEXT)
        device = self.device
        subtitle = device.name if device else "等待手柄连接"
        theme.draw_text(surface, self.fonts.get(12), subtitle, (SIDEBAR_WIDTH + 26, 50), theme.TEXT_MUTED)

        pills = []
        if device is not None:
            pills.append(device.describe_transport())
            pills.append(device.describe_layout())
        pills.append(f"{self.poll_rate:.0f} Hz")

        x = self.size[0] - 24
        for text in reversed(pills):
            font = self.fonts.get(11)
            pill_w = font.size(text)[0] + 20
            rect = pygame.Rect(x - pill_w, 22, pill_w, 24)
            theme.rounded_rect(surface, rect, theme.PANEL, radius=12, border=theme.BORDER_SOFT)
            theme.draw_text(surface, font, text, rect.center, theme.TEXT_DIM, align="center")
            x = rect.x - 8

    def _draw_footer(self) -> None:
        ui, surface = self.ui, self.ui.surface
        top = self.size[1] - FOOTER_HEIGHT
        pygame.draw.rect(surface, theme.SIDEBAR, pygame.Rect(0, top, self.size[0], FOOTER_HEIGHT))
        pygame.draw.line(surface, theme.BORDER_SOFT, (0, top), (self.size[0], top))

        message = self.status_message if time.monotonic() < self.status_until else "F5 刷新设备 · ESC 退出输入框"
        color = theme.ACCENT if time.monotonic() < self.status_until else theme.TEXT_MUTED
        pygame.draw.circle(surface, color, (SIDEBAR_WIDTH + 16, top + FOOTER_HEIGHT // 2), 4)
        theme.draw_text(surface, self.fonts.get(12), message, (SIDEBAR_WIDTH + 28, top + FOOTER_HEIGHT // 2),
                        color, align="midleft")

        right_text = f"v{__version__} · 方案：{theme.ellipsize(self.fonts.get(12), self.profile.name, 200)}"
        theme.draw_text(surface, self.fonts.get(12), right_text,
                        (self.size[0] - 16, top + FOOTER_HEIGHT // 2), theme.TEXT_MUTED, align="midright")
