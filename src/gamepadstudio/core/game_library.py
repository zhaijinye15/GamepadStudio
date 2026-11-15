"""本地游戏库：扫描已安装游戏，并通过 MuMu 模拟器启动手游.

设计要点：
* 桌面游戏走三条来源：注册表卸载项（DisplayIcon / InstallLocation）、Steam 库
  （libraryfolders.vdf + appmanifest_*.acf）；
* 手游走 MuMu 模拟器：优先用它自带的 ``MuMuManager.exe``（info / control / adb 子命令），
  没有管理器时退回到 ``adb`` 直连 127.0.0.1:16384 起的端口；
* 启动一律在后台进程里做（DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP），
  不阻塞界面，也不弹黑框。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IS_WIN = sys.platform.startswith("win")

try:  # 仅在 Windows 上有 winreg
    import winreg  # type: ignore
except Exception:  # pragma: no cover - 非 Windows 环境导入失败属预期
    winreg = None

STEAM_LINK = "steam://rungameid/{app_id}"

# 明显不是游戏 / 不该出现在游戏库里的条目
NON_GAME_HINTS = re.compile(
    r"驱动|driver|redistributable|visual c\+\+|\.net|directx|webview|runtime|sdk|"
    r"update|hotfix|patch|插件|扩展|framework|"
    r"7-zip|winrar|bandizip|好压|压缩|看图|viewer|everything|notepad|office|wps|adobe|"
    r"chrome|edge|firefox|bonjour|apple mobile|itunes|qq|微信|wechat|钉钉|bilibili|哔哩哔哩|"
    r"网盘|迅雷|剪映|steam|epic|battle\.net|ubisoft|ea app|gog|anticheat|应用宝|"
    r"android|emulator|模拟器|xiaomi mimo|得力|打印机|输入法|"
    r"安全|卫士|管家|杀毒|密码|password|vpn|加速器|远程|remote|toolbox|idea|"
    r"visual studio|notion|vs code|vmware|桌面端|教师|teacher|seewo|希沃|root|大师|"
    r"formatter|startallback|服务|service|音乐|播放器|浏览器|邮箱|电池|风扇|键盘|鼠标|声卡|显卡",
    re.I,
)
UNINSTALLER_HINTS = re.compile(r"unins|uninst|setup|update|updater|repair|crash|report|helper", re.I)

# 正命中：名字带这些词，或装在游戏平台/游戏目录里，才算游戏
GAME_NAME_HINTS = re.compile(
    r"游戏|game|行动|派对|荣耀|英雄|传奇|之战|战场|模拟|竞速|飞车|火线|原神|崩坏|阴阳师|"
    r"明日方舟|蛋仔|光遇|我的世界|minecraft|delta force|三角洲|pubg|apex|valorant|"
    r"league|legend|war|force|craft|racing|football|fifa|2k|steam 游戏|cs2|counter-strike|"
    r"dota|overwatch|守望|暗黑|diablo|星际|starcraft|魔兽|warcraft|赛博朋克|cyberpunk|"
    r"艾尔登|elden|gta|荒野大镖客|red dead|使命召唤|call of duty|战地|battlefield|"
    r"刺客信条|assassin|孤岛惊魂|far cry|极品飞车|nfs|地平线|horizon|极限竞速|forza",
    re.I,
)
GAME_PATH_HINTS = re.compile(
    r"\\steamapps\\|\\steam\\steamapps|\\(epic games|gog|battle\.net|ubisoft|ea games|origin|"
    r"riot games|wegame|games?|游戏)\\|\\program files\\tencent\\tencent games\\|\\android\\",
    re.I,
)

# 常见手游包名 → 中文名（认不出来的就按包名末段显示）
ANDROID_NAMES = {
    "com.tencent.tmgp.sgame": "王者荣耀",
    "com.tencent.tmgp.pubgmhd": "和平精英",
    "com.tencent.tmgp.dfm": "三角洲行动",
    "com.tencent.tmgp.tft": "金铲铲之战",
    "com.tencent.tmgp.speedmobile": "QQ飞车手游",
    "com.tencent.tmgp.cf": "穿越火线手游",
    "com.tencent.lolm": "英雄联盟手游",
    "com.miHoYo.Yuanshen": "原神",
    "com.miHoYo.hkrpg": "崩坏：星穹铁道",
    "com.miHoYo.bh3": "崩坏3",
    "com.netease.party": "蛋仔派对",
    "com.netease.onmyoji": "阴阳师",
    "com.netease.sky": "光·遇",
    "com.netease.dwrg": "第五人格",
    "com.hypergryph.arknights": "明日方舟",
    "com.tencent.ig": "PUBG Mobile",
    "com.mojang.minecraftpe": "我的世界（手机版）",
}
# 模拟器里明显不是游戏的应用，扫描时剔掉
ANDROID_NOISE = re.compile(
    r"com\.tencent\.mm|com\.tencent\.mobileqq|com\.ss\.android\.ugc\.aweme|"
    r"com\.netease\.mumu|mumu|com\.xiaomi\.|com\.android\.|com\.google\.android|"
    r"com\.tencent\.qqlite|com\.qiyi|com\.youku|com\.bilibili|com\.taobao|com\.jd\.|"
    r"com\.sina\.weibo|com\.antutu|market|launcher|settings|inputmethod|keyboard",
    re.I,
)


@dataclass
class GameEntry:
    """一条可启动的条目（桌面游戏或模拟器里的手游）."""

    name: str
    kind: str = "exe"          # exe | steam | emulator
    target: str = ""           # exe 路径 / steam://… / 安卓包名
    args: str = ""
    source: str = ""           # Steam / 注册表 / MuMu
    install_dir: str = ""
    app_id: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "target": self.target,
            "args": self.args,
            "source": self.source,
            "install_dir": self.install_dir,
            "app_id": self.app_id,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameEntry":
        return cls(
            name=str(data.get("name", "")),
            kind=str(data.get("kind", "exe")),
            target=str(data.get("target", "")),
            args=str(data.get("args", "")),
            source=str(data.get("source", "")),
            install_dir=str(data.get("install_dir", "")),
            app_id=str(data.get("app_id", "")),
            note=str(data.get("note", "")),
        )


@dataclass
class MumuInfo:
    """MuMu 模拟器（含"发烧版"）的定位结果."""

    root: str
    manager: str = ""
    adb: str = ""
    version: str = ""
    index: str = "0"
    process_started: bool = False
    android_started: bool = False


def _clean_path(text: str) -> str:
    """去掉引号与 ",0" / ",1" 这类图标索引后缀."""
    text = (text or "").strip().strip('"')
    text = re.sub(r",\s*-?\d+\s*$", "", text).strip()
    return text


def _iter_uninstall_keys():
    if winreg is None:
        return
    targets = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", 0),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
    )
    for hive, path, extra in targets:
        try:
            root = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | extra)
        except OSError:
            continue
        with root:
            count = 0
            try:
                count = winreg.QueryInfoKey(root)[0]
            except OSError:
                pass
            for index in range(count):
                try:
                    name = winreg.EnumKey(root, index)
                    sub = winreg.OpenKey(root, name)
                except OSError:
                    continue
                values: Dict[str, str] = {}
                with sub:
                    for value_index in range(64):
                        try:
                            key_name, key_value, _ = winreg.EnumValue(sub, value_index)
                        except OSError:
                            break
                        if isinstance(key_value, str):
                            values[key_name] = key_value
                        elif isinstance(key_value, int):
                            values[key_name] = str(key_value)
                yield values


def _has_mumu_binaries(path: Path) -> bool:
    """判断某目录是否真的是 MuMu 根目录（必须能找到管理器或 adb）."""
    try:
        if (path / "nx_main" / "MuMuManager.exe").exists():
            return True
        if (path / "nx_main" / "adb.exe").exists():
            return True
        if (path / "shell" / "MuMuManager.exe").exists():
            return True
        if (path / "shell" / "adb.exe").exists():
            return True
        for adb in (path / "nx_device").glob("*/shell/adb.exe"):
            if adb.exists():
                return True
    except OSError:
        return False
    return False


def _find_mumu_root(start: str) -> Optional[Path]:
    """从图标/卸载路径往上找，定位真正包含 MuMu 可执行文件的根目录.

    注意：注册表里 DisplayIcon 常指向 ``overlay\\shortcut.ico``，
    overlay 目录里也有名为 nx_main / nx_device 的子目录，但它们不含可执行文件，
    所以不能只看目录名，必须校验管理器或 adb 是否落地。
    """
    if not start:
        return None
    try:
        path = Path(start)
    except Exception:
        return None
    if path.suffix:  # 传进来的是文件
        path = path.parent
    for _ in range(5):
        if _has_mumu_binaries(path):
            return path
        if path.parent == path:
            break
        path = path.parent
    return None


def detect_mumu() -> Optional[MumuInfo]:
    """检测本机 MuMu（含发烧版 / 12.x / 6.x），返回可用的管理器与 adb 路径."""
    roots: List[Path] = []
    if winreg is not None:
        for values in _iter_uninstall_keys():
            display = values.get("DisplayName", "")
            if "mumu" not in display.lower():
                continue
            for key in ("InstallLocation", "DisplayIcon", "UninstallString"):
                raw = values.get(key, "")
                if not raw:
                    continue
                cleaned = _clean_path(raw.split("|")[0])
                found = _find_mumu_root(cleaned)
                if found is not None:
                    roots.append(found)

    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramData"):
        base = os.environ.get(env_key)
        if not base:
            continue
        try:
            for child in Path(base).iterdir():
                if child.is_dir() and "mumu" in child.name.lower():
                    roots.append(child)
            netease = Path(base) / "Netease"
            if netease.exists():
                for child in netease.iterdir():
                    if child.is_dir() and "mumu" in child.name.lower():
                        roots.append(child)
        except OSError:
            continue

    unique: List[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in unique or not _has_mumu_binaries(resolved):
            continue
        unique.append(resolved)

    if not unique:
        return None

    root = unique[0]
    manager = ""
    for candidate in (root / "nx_main" / "MuMuManager.exe", root / "shell" / "MuMuManager.exe",
                      root / "MuMuManager.exe", root / "nx_main" / "mumu_manager.exe"):
        if candidate.exists():
            manager = str(candidate)
            break

    adb = ""
    adb_candidates = []
    adb_candidates.extend(sorted((root / "nx_device").glob("*/shell/adb.exe")) if (root / "nx_device").exists() else [])
    adb_candidates.extend([root / "nx_main" / "adb.exe", root / "shell" / "adb.exe", root / "adb.exe"])
    for candidate in adb_candidates:
        if candidate.exists():
            adb = str(candidate)
            break

    if not manager and not adb:
        return None

    info = MumuInfo(root=str(root), manager=manager, adb=adb)
    info.version = _manager_version(manager)
    _refresh_instance(info)
    return info


def _run(cmd: List[str], timeout: float = 25.0) -> Tuple[int, str]:
    """静默执行命令，返回 (returncode, 输出). 不弹窗、不继承控制台."""
    if not cmd:
        return 1, ""
    try:
        flags = 0
        if IS_WIN:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            cmd, capture_output=True, timeout=timeout, creationflags=flags,
            text=True, encoding="utf-8", errors="replace",
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "命令超时"
    except Exception as exc:  # 路径不存在、权限等
        return 1, str(exc)


def _manager_version(manager: str) -> str:
    if not manager:
        return ""
    code, output = _run([manager, "version"], timeout=15.0)
    match = re.search(r"\d+(?:\.\d+)+", output or "")
    return match.group(0) if match and code == 0 else ""


def _manager_info(manager: str) -> List[dict]:
    if not manager:
        return []
    code, output = _run([manager, "info", "-v", "all"], timeout=20.0)
    if not output:
        return []
    # 输出可能是单个对象，也可能是对象数组 / 每行一个 JSON
    chunks = re.findall(r"\{.*?\}", output, re.S)
    parsed: List[dict] = []
    for chunk in chunks:
        try:
            data = json.loads(chunk)
        except Exception:
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def _refresh_instance(info: MumuInfo) -> None:
    """读取实例状态（是否启动、安卓是否就绪、实例序号）."""
    entries = _manager_info(info.manager)
    if not entries:
        return
    main = entries[0]
    info.index = str(main.get("index", "0"))
    info.process_started = bool(main.get("is_process_started"))
    info.android_started = bool(main.get("is_android_started"))


def _mumu_adb(info: MumuInfo, cmd: str, timeout: float = 30.0) -> Tuple[int, str]:
    """在模拟器实例里执行 adb 命令（优先 MuMuManager adb 子命令）."""
    if info.manager:
        return _run([info.manager, "adb", "-v", info.index, "-c", cmd], timeout=timeout)
    if info.adb:
        serial = _guess_serial(info)
        return _run([info.adb, "-s", serial, cmd] if serial else [info.adb, cmd], timeout=timeout)
    return 1, "没有可用的 adb"


def _guess_serial(info: MumuInfo) -> str:
    """没管理器时按常见端口找 adb 设备（MuMu 12 / 6 用 16384 起）."""
    if not info.adb:
        return ""
    _run([info.adb, "start-server"], timeout=15.0)
    code, output = _run([info.adb, "devices"], timeout=20.0)
    for line in (output or "").splitlines():
        line = line.strip()
        if line.startswith("127.0.0.1:") or line.startswith("emulator-"):
            return line.split()[0]
    for port in range(16384, 16390):
        _run([info.adb, "connect", f"127.0.0.1:{port}"], timeout=10.0)
    code, output = _run([info.adb, "devices"], timeout=20.0)
    for line in (output or "").splitlines():
        line = line.strip()
        if line.startswith("127.0.0.1:") or line.startswith("emulator-"):
            return line.split()[0]
    return ""


# ---------------------------------------------------------------- 桌面游戏扫描
def _registry_games() -> List[GameEntry]:
    found: List[GameEntry] = []
    seen: set[str] = set()
    seen_dirs: set[str] = set()
    for values in _iter_uninstall_keys():
        display = (values.get("DisplayName") or "").strip()
        if not display:
            continue
        if values.get("SystemComponent") in ("1",) or values.get("ParentKeyName"):
            continue
        release = (values.get("ReleaseType") or "").lower()
        if release in ("update", "hotfix", "security update", "update rollup", "servicepack"):
            continue
        if NON_GAME_HINTS.search(display):
            continue

        icon = _clean_path((values.get("DisplayIcon") or "").split("|")[0])
        install_dir = _clean_path(values.get("InstallLocation") or "")
        exe = ""
        if icon.lower().endswith(".exe") and Path(icon).exists():
            exe = icon
        elif install_dir:
            try:
                candidates = [p for p in Path(install_dir).glob("*.exe")
                              if p.is_file() and not UNINSTALLER_HINTS.search(p.name)]
            except OSError:
                candidates = []
            if candidates:
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                exe = str(candidates[0])
        if not exe or not Path(exe).exists():
            continue
        if UNINSTALLER_HINTS.search(Path(exe).name):
            continue
        if install_dir and not Path(install_dir).exists():
            install_dir = str(Path(exe).parent)

        # 必须是"游戏"：名字带游戏词，或位于游戏平台 / 游戏目录
        haystack = f"{display} {install_dir} {exe}"
        if not (GAME_NAME_HINTS.search(haystack) or GAME_PATH_HINTS.search(haystack)):
            continue

        key = display.lower()
        if key in seen:
            continue
        seen.add(key)
        # 同一安装目录里的多个启动器（比如"三角洲行动"和 Delta Force launcher）只留一条，
        # 优先选不带 launcher 的那个 exe
        dir_key = (install_dir or str(Path(exe).parent)).lower()
        if dir_key in seen_dirs:
            for index, existing in enumerate(found):
                if (existing.install_dir or "").lower() != dir_key:
                    continue
                if "launcher" in Path(existing.target).name.lower() and "launcher" not in Path(exe).name.lower():
                    found[index] = GameEntry(name=display, kind="exe", target=exe, source="注册表",
                                             install_dir=install_dir or str(Path(exe).parent),
                                             app_id=values.get("DisplayVersion", ""))
                break
            continue
        seen_dirs.add(dir_key)
        found.append(GameEntry(name=display, kind="exe", target=exe, source="注册表",
                               install_dir=install_dir or str(Path(exe).parent), app_id=values.get("DisplayVersion", "")))
    return found


def _parse_vdf_int(text: str, key: str) -> str:
    match = re.search(r'"' + key + r'"\s*"([^"]*)"', text)
    return match.group(1) if match else ""


def _steam_libraries(steam_root: Path) -> List[Path]:
    libs: List[Path] = []
    if (steam_root / "steamapps").exists():
        libs.append(steam_root)
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for match in re.finditer(r'"path"\s*"((?:[^"\\]|\\.)*)"', text):
            raw = match.group(1).replace("\\\\", "\\")
            candidate = Path(raw)
            if candidate.exists() and candidate not in libs:
                libs.append(candidate)
    return libs


def _steam_games() -> List[GameEntry]:
    games: List[GameEntry] = []
    steam_root = None
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_root = Path(_clean_path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            steam_root = None
    if steam_root is None:
        default = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
        if default and (Path(default) / "Steam").exists():
            steam_root = Path(default) / "Steam"
    if steam_root is None or not steam_root.exists():
        return games

    for library in _steam_libraries(steam_root):
        apps_dir = library / "steamapps"
        if not apps_dir.exists():
            continue
        for manifest in apps_dir.glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            app_id = _parse_vdf_int(text, "appid") or manifest.stem.replace("appmanifest_", "")
            name = _parse_vdf_int(text, "name")
            install = _parse_vdf_int(text, "installdir")
            state = _parse_vdf_int(text, "StateFlags")
            if not name or not app_id:
                continue
            if state and state not in ("4", "6", "1026"):
                continue
            if re.search(r"redistribut|steamworks|proton|steam linux runtime|soundtrack", name, re.I):
                continue
            folder = apps_dir / "common" / install if install else None
            if folder is not None and not folder.exists():
                continue
            games.append(GameEntry(name=name, kind="steam", target=STEAM_LINK.format(app_id=app_id),
                                   source="Steam", install_dir=str(folder or ""), app_id=app_id))
    return games


def _android_display_name(package: str) -> str:
    if package in ANDROID_NAMES:
        return ANDROID_NAMES[package]
    tail = package.split(".")[-1]
    return tail[:1].upper() + tail[1:] if tail else package


def list_android_games(info: MumuInfo) -> List[GameEntry]:
    """列出模拟器里已安装的第三方应用，过滤掉系统 / 非游戏包."""
    if not (info.process_started or info.android_started):
        return []
    code, output = _mumu_adb(info, "shell pm list packages -3", timeout=40.0)
    entries: List[GameEntry] = []
    seen: set[str] = set()
    for line in (output or "").splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        package = line.split("package:", 1)[1].strip()
        if not package or package in seen or ANDROID_NOISE.search(package):
            continue
        seen.add(package)
        entries.append(GameEntry(name=_android_display_name(package), kind="emulator", target=package,
                                 source="MuMu", app_id=package, note="手游"))
    return entries


class GameLibrary:
    """游戏库：扫描、缓存、启动."""

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self.cache_path = cache_path
        self.games: List[GameEntry] = []
        self.mumu: Optional[MumuInfo] = None
        self.scanning = False
        self.last_error = ""
        self.loaded_from_cache = False
        self._load_cache()

    # ------------------------------------------------------------ 缓存
    def _load_cache(self) -> None:
        if self.cache_path is None or not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = data.get("games") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return
        self.games = [GameEntry.from_dict(item) for item in items if isinstance(item, dict)]
        self.loaded_from_cache = bool(self.games)

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "games": [entry.to_dict() for entry in self.games]}
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ 扫描
    def scan(self, include_android: bool = True) -> int:
        """扫描本机游戏；已启动的 MuMu 会一并列出手游."""
        self.scanning = True
        self.last_error = ""
        entries: List[GameEntry] = []
        try:
            entries.extend(_steam_games())
        except Exception as exc:
            self.last_error = f"Steam 扫描失败：{exc}"
        try:
            entries.extend(_registry_games())
        except Exception as exc:
            self.last_error = f"注册表扫描失败：{exc}"

        emu_entries: List[GameEntry] = []
        try:
            self.mumu = detect_mumu()
            if self.mumu is not None:
                _refresh_instance(self.mumu)
                if include_android:
                    emu_entries = list_android_games(self.mumu)
        except Exception as exc:
            self.last_error = f"MuMu 检测失败：{exc}"

        # 去重：同名的桌面游戏只留一条，手游按包名去重
        merged: List[GameEntry] = []
        seen: set[Tuple[str, str]] = set()
        for entry in entries:
            key = (entry.name.lower(), entry.kind)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
        for entry in emu_entries:
            key = (entry.name.lower(), "emulator")
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)

        merged.sort(key=lambda e: (0 if e.kind == "emulator" else 1, e.name.lower()))
        self.games = merged
        self.scanning = False
        self.loaded_from_cache = False
        self._save_cache()
        return len(merged)

    # ------------------------------------------------------------ 启动
    def ensure_mumu(self, on_step=None) -> Tuple[bool, str]:
        """确保 MuMu 已启动；返回 (是否就绪, 说明)."""
        if self.mumu is None:
            self.mumu = detect_mumu()
        if self.mumu is None:
            return False, "没有检测到 MuMu 模拟器"
        _refresh_instance(self.mumu)
        if self.mumu.android_started:
            return True, "MuMu 已就绪"
        if not self.mumu.manager:
            return False, "MuMu 缺少 MuMuManager.exe，无法自动启动"
        if on_step:
            on_step("正在启动 MuMu 模拟器…")
        _run([self.mumu.manager, "control", "-v", self.mumu.index, "launch"], timeout=90.0)
        deadline = time.time() + 120.0
        while time.time() < deadline:
            time.sleep(3.0)
            _refresh_instance(self.mumu)
            if self.mumu.android_started:
                return True, "MuMu 已就绪"
            if on_step:
                on_step("等待 MuMu 进入安卓系统…")
        return False, "MuMu 启动超时，请手动启动一次模拟器后重试"

    def launch(self, entry: GameEntry) -> Tuple[bool, str]:
        """启动一条条目；返回 (是否成功, 给用户看的结果)."""
        if entry.kind == "exe":
            exe = Path(entry.target)
            if not exe.exists():
                return False, f"文件不存在：{entry.target}"
            try:
                args = [str(exe)] + ([entry.args] if entry.args else [])
                cwd = entry.install_dir if entry.install_dir and Path(entry.install_dir).exists() else str(exe.parent)
                flags = 0
                if IS_WIN:
                    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                subprocess.Popen(args, cwd=cwd, close_fds=True, creationflags=flags,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"已启动：{entry.name}"
            except Exception as exc:
                return False, f"启动失败：{exc}"

        if entry.kind == "steam":
            try:
                if IS_WIN:
                    os.startfile(entry.target)  # noqa: S606 - 用系统协议启动 Steam
                else:  # pragma: no cover
                    subprocess.Popen(["xdg-open", entry.target])
                return True, f"已请求 Steam 启动：{entry.name}"
            except Exception as exc:
                return False, f"启动 Steam 失败：{exc}"

        if entry.kind == "emulator":
            ready, message = self.ensure_mumu()
            if not ready:
                return False, message
            package = entry.target
            code, output = _mumu_adb(
                self.mumu,
                f"shell monkey -p {package} -c android.intent.category.LAUNCHER 1",
                timeout=45.0,
            )
            if code == 0 and "No activities found" not in (output or ""):
                return True, f"已在 MuMu 里启动：{entry.name}"
            # monkey 失败时退回 am start（需要先解析启动组件）
            code2, output2 = _mumu_adb(
                self.mumu,
                f"shell cmd package resolve-activity --brief {package}",
                timeout=30.0,
            )
            component = ""
            for line in (output2 or "").splitlines():
                if "/" in line and "." in line:
                    component = line.strip()
            if component:
                code3, output3 = _mumu_adb(
                    self.mumu, f"shell am start -n {component}", timeout=45.0)
                if code3 == 0:
                    return True, f"已在 MuMu 里启动：{entry.name}"
                return False, f"启动失败：{output3.strip()[:120]}"
            return False, f"启动失败：{(output or '未知错误').strip()[:120]}"

        return False, "未知条目类型"

    def refresh_android(self) -> int:
        """只重扫模拟器里的手游（MuMu 已在运行时用）."""
        if self.mumu is None:
            self.mumu = detect_mumu()
        if self.mumu is None:
            return 0
        _refresh_instance(self.mumu)
        android = list_android_games(self.mumu)
        keep = [entry for entry in self.games if entry.kind != "emulator"]
        android.extend(keep)
        android.sort(key=lambda e: (0 if e.kind == "emulator" else 1, e.name.lower()))
        self.games = android
        self._save_cache()
        return len([entry for entry in self.games if entry.kind == "emulator"])

    @property
    def mumu_summary(self) -> str:
        if self.mumu is None:
            return "未检测到 MuMu 模拟器"
        state = "安卓已就绪" if self.mumu.android_started else (
            "已启动，加载中" if self.mumu.process_started else "未启动")
        version = f" {self.mumu.version}" if self.mumu.version else ""
        return f"MuMu{version} · {state}"
