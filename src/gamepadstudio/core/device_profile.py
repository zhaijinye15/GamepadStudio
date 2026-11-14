"""按手柄保存的校准方案（一套设备一份 JSON）.

存储位置：``%APPDATA%\\GamepadStudio\\calibrations\\*.json``
匹配顺序：GUID 全等 -> VID/PID 相同 -> 名称相同，命中即自动加载。

按名称兜底是必要的：同一个型号换 USB 口或换蓝牙连接时 SDL 的 GUID 会变，
但用户显然希望"我这个 Xbox 手柄"始终用同一套手感。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .calibration import DeviceCalibration
from .model import DeviceInfo

SCHEMA_VERSION = 1


@dataclass
class DeviceProfile:
    id: str = ""
    label: str = ""
    device_name: str = ""
    guid: str = ""
    vendor_id: int = 0
    product_id: int = 0
    layout: str = "generic"
    calibration: DeviceCalibration = field(default_factory=DeviceCalibration)
    updated: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema": SCHEMA_VERSION,
            "id": self.id,
            "label": self.label or self.device_name,
            "device": {
                "name": self.device_name,
                "guid": self.guid,
                "vendor_id": int(self.vendor_id),
                "product_id": int(self.product_id),
                "layout": self.layout,
            },
            "calibration": self.calibration.to_dict(),
            "updated": self.updated or time.time(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceProfile":
        device = data.get("device") if isinstance(data.get("device"), dict) else {}
        return cls(
            id=str(data.get("id") or ""),
            label=str(data.get("label") or ""),
            device_name=str(device.get("name") or ""),
            guid=str(device.get("guid") or ""),
            vendor_id=_as_int(device.get("vendor_id")),
            product_id=_as_int(device.get("product_id")),
            layout=str(device.get("layout") or "generic"),
            calibration=DeviceCalibration.from_dict(data.get("calibration")),
            updated=_as_float(data.get("updated")),
        )

    def matches(self, device: DeviceInfo) -> int:
        """返回匹配强度，0 表示不匹配；数字越大越精确."""
        if self.guid and device.guid and self.guid.lower() == device.guid.lower():
            return 3
        if (self.vendor_id and self.product_id
                and self.vendor_id == device.vendor_id
                and self.product_id == device.product_id):
            return 2
        if self.device_name and _normalize(self.device_name) == _normalize(device.name):
            return 1
        return 0


class ProfileStore:
    """方案库：读、写、删、匹配、导入导出."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._cache: List[DeviceProfile] = []
        self.reload()

    # -------------------------------------------------------------- 读写
    def reload(self) -> List[DeviceProfile]:
        profiles: List[DeviceProfile] = []
        try:
            files = sorted(self.directory.glob("*.json"))
        except Exception:
            files = []
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            profile = DeviceProfile.from_dict(data)
            if not profile.id:
                profile.id = path.stem
            profiles.append(profile)
        self._cache = profiles
        return profiles

    @property
    def profiles(self) -> List[DeviceProfile]:
        if not self._cache:
            self.reload()
        return self._cache

    def save(self, profile: DeviceProfile, unique: bool = False) -> Optional[Path]:
        if not profile.id:
            base = _base_id(profile)
            profile.id = _unique_id(base, self.directory) if unique else base
        profile.updated = time.time()
        path = self.directory / f"{profile.id}.json"
        try:
            path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except Exception:
            return None
        self.reload()
        return path

    def delete(self, profile_id: str) -> bool:
        path = self.directory / f"{profile_id}.json"
        try:
            if path.exists():
                path.unlink()
                self.reload()
                return True
        except Exception:
            return False
        return False

    # -------------------------------------------------------------- 匹配
    def find_by_id(self, profile_id: str) -> Optional[DeviceProfile]:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def match(self, device: Optional[DeviceInfo]) -> Optional[DeviceProfile]:
        """返回匹配强度最高的方案；同分时取最近更新的一个."""
        if device is None:
            return None
        best: Optional[DeviceProfile] = None
        best_score = 0
        for profile in self.profiles:
            score = profile.matches(device)
            if score <= 0:
                continue
            if score > best_score or (score == best_score and best is not None
                                      and profile.updated > best.updated):
                best, best_score = profile, score
        return best

    def upsert_for_device(self, device: DeviceInfo, calibration: DeviceCalibration,
                          label: str = "") -> Optional[DeviceProfile]:
        """保存（或覆盖）当前手柄的方案."""
        existing = self.match(device)
        profile = existing or DeviceProfile(id=_base_id_from_device(device))
        profile.label = label or profile.label or device.name
        profile.device_name = device.name
        profile.guid = device.guid
        profile.vendor_id = device.vendor_id
        profile.product_id = device.product_id
        profile.layout = device.layout
        profile.calibration = calibration
        if not profile.id:
            profile.id = _base_id(profile)
        self.save(profile)
        return profile

    def import_file(self, path: Path) -> List[DeviceProfile]:
        """导入外部 JSON（支持单份方案或方案数组）."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        imported: List[DeviceProfile] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            profile = DeviceProfile.from_dict(item)
            profile.id = ""
            if not self.save(profile, unique=True):
                continue
            imported.append(profile)
        return imported

    def export_file(self, profile: DeviceProfile, path: Path) -> bool:
        try:
            Path(path).write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            return True
        except Exception:
            return False


# ------------------------------------------------------------------ 工具
def _slug(text: str) -> str:
    ascii_slug = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-").lower()
    return ascii_slug or "pad"


def _base_id_from_device(device: DeviceInfo) -> str:
    if device.vendor_id and device.product_id:
        return f"pad-{device.vendor_id:04x}-{device.product_id:04x}"
    return "pad-" + _slug(device.name)


def _base_id(profile: DeviceProfile) -> str:
    if profile.vendor_id and profile.product_id:
        return f"pad-{profile.vendor_id:04x}-{profile.product_id:04x}"
    return "pad-" + _slug(profile.device_name)


def _unique_id(base: str, directory: Path) -> str:
    """导入时避免覆盖同名方案：已存在就追加 -2、-3 …"""
    candidate = base
    index = 2
    while (Path(directory) / f"{candidate}.json").exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
