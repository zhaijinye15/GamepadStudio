"""校准与方案库的回归测试（不依赖 pygame）."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gamepadstudio.core.calibration import (
    DeviceCalibration,
    StickSampler,
    StickSettings,
    TriggerSampler,
    TriggerSettings,
    apply_curve,
)
from gamepadstudio.core.device_profile import DeviceProfile, ProfileStore
from gamepadstudio.core.model import DeviceInfo


class CurveTests(unittest.TestCase):
    def test_linear_is_identity(self):
        for value in (-1.0, -0.5, 0.0, 0.35, 1.0):
            self.assertAlmostEqual(apply_curve(value, "linear", 2.0), value, places=6)

    def test_endpoints_and_monotonic(self):
        for kind in ("ease_in", "ease_out", "expo", "s_curve"):
            self.assertAlmostEqual(apply_curve(1.0, kind, 2.0), 1.0, places=6)
            self.assertAlmostEqual(apply_curve(-1.0, kind, 2.0), -1.0, places=6)
            previous = -1.1
            for step in range(21):
                value = -1.0 + step * 0.1
                out = apply_curve(value, kind, 2.0)
                self.assertGreaterEqual(out, previous)
                previous = out

    def test_ease_in_is_gentler_near_center(self):
        self.assertLess(apply_curve(0.3, "ease_in", 2.0), 0.3)
        self.assertGreater(apply_curve(0.3, "ease_out", 2.0), 0.3)


class StickTests(unittest.TestCase):
    def test_center_and_span_remap(self):
        stick = StickSettings(center_x=0.1, center_y=-0.05, span_x=0.8, span_y=0.9,
                              deadzone=0.0, drift=0.0, invert_y=False)
        # 中心点映射为 0
        x, y = stick.process(0.1, -0.05)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        # 推到行程极限映射为 ±1
        x, y = stick.process(0.1 + 0.8, -0.05 + 0.9)
        self.assertAlmostEqual(x, 1.0, places=6)
        self.assertAlmostEqual(y, 1.0, places=6)

    def test_drift_filter_kills_small_jitter(self):
        stick = StickSettings(deadzone=0.0, drift=0.05, invert_y=False)
        x, y = stick.process(0.03, -0.02)
        self.assertEqual((x, y), (0.0, 0.0))

    def test_radial_deadzone_scales_remainder(self):
        stick = StickSettings(deadzone=0.2, drift=0.0, invert_y=False)
        # 斜向 0.3/0.4 -> 长度 0.5，超过死区后应继续放大到 0.375 左右
        x, y = stick.process(0.3, 0.4)
        self.assertAlmostEqual((x * x + y * y) ** 0.5, (0.5 - 0.2) / 0.8, places=4)

    def test_inside_deadzone_is_zero(self):
        stick = StickSettings(deadzone=0.3, drift=0.0, invert_y=False)
        self.assertEqual(stick.process(0.05, 0.05), (0.0, 0.0))

    def test_invert_y_default(self):
        stick = StickSettings()
        self.assertTrue(stick.invert_y)
        x, y = stick.process(0.0, 0.9)
        self.assertLess(y, 0.0)

    def test_serialization_roundtrip(self):
        stick = StickSettings(deadzone=0.22, drift=0.03, curve="expo", power=2.4,
                              invert_x=True, center_x=0.01, span_y=0.85, calibrated=True)
        restored = StickSettings.from_dict(stick.to_dict())
        self.assertEqual(restored.to_dict(), stick.to_dict())

    def test_bad_values_are_clamped(self):
        restored = StickSettings.from_dict({"deadzone": 5, "span_x": 0, "curve": "nope",
                                           "power": float("nan")})
        self.assertLessEqual(restored.deadzone, 0.95)
        self.assertGreaterEqual(restored.span_x, 0.15)
        self.assertEqual(restored.curve, "linear")
        self.assertGreaterEqual(restored.power, 1.0)


class TriggerTests(unittest.TestCase):
    def test_calibrated_range(self):
        trigger = TriggerSettings(min_raw=0.1, max_raw=0.9, deadzone=0.0, calibrated=True)
        self.assertAlmostEqual(trigger.process(0.1), 0.0, places=6)
        self.assertAlmostEqual(trigger.process(1.0), 1.0, places=6)

    def test_invert(self):
        trigger = TriggerSettings(min_raw=0.0, max_raw=1.0, deadzone=0.0, invert=True)
        self.assertAlmostEqual(trigger.process(0.0), 1.0, places=6)
        self.assertAlmostEqual(trigger.process(1.0), 0.0, places=6)

    def test_deadzone(self):
        trigger = TriggerSettings(min_raw=0.0, max_raw=1.0, deadzone=0.1)
        self.assertEqual(trigger.process(0.05), 0.0)
        self.assertGreater(trigger.process(0.5), 0.4)


class SamplerTests(unittest.TestCase):
    def test_stick_sampler_uses_median_center(self):
        sampler = StickSampler("lx", "ly")
        sampler.start_center()
        for value in (0.02, 0.03, 0.9, 0.01, 0.02):
            sampler.feed_center(value, 0.0)
        center = sampler.finish_center()
        self.assertAlmostEqual(center[0], 0.02, places=6)

    def test_stick_sampler_span(self):
        sampler = StickSampler("lx", "ly")
        sampler.start_center()
        for _ in range(3):
            sampler.feed_center(0.0, 0.0)
        sampler.finish_center()
        sampler.start_span()
        sampler.feed_span(0.95, -0.4)
        sampler.feed_span(-0.8, 0.3)
        span = sampler.finish_span()
        self.assertAlmostEqual(span[0], 0.95, places=6)
        self.assertAlmostEqual(span[1], 0.4, places=6)

    def test_trigger_sampler_expands_range(self):
        sampler = TriggerSampler()
        for value in (0.02, 0.5, 0.93):
            sampler.feed(value)
        low, high = sampler.result()
        self.assertLessEqual(low, 0.04)
        self.assertGreaterEqual(high, 0.96)


class DeviceCalibrationTests(unittest.TestCase):
    def test_apply_axes_only_touches_known_axes(self):
        calib = DeviceCalibration()
        calib.reset()
        axes = calib.apply_axes({"lx": 0.0, "ly": 0.9, "lt": 0.5, "other": 0.7})
        self.assertLess(axes["ly"], 0.0)          # 默认 Y 反向
        self.assertIn("other", axes)
        self.assertEqual(axes["other"], 0.7)

    def test_roundtrip(self):
        calib = DeviceCalibration()
        calib.left.deadzone = 0.25
        calib.rt.invert = True
        restored = DeviceCalibration.from_dict(calib.to_dict())
        self.assertEqual(restored.to_dict(), calib.to_dict())


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProfileStore(Path(self.tmp.name) / "calibrations")
        self.device = DeviceInfo(key="sdl:1", name="Xbox 360 Controller", backend="sdl",
                                 guid="030000005e0400008e0200000000", vendor_id=0x045E,
                                 product_id=0x028E, layout="xbox")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_match(self):
        calib = DeviceCalibration()
        calib.left.deadzone = 0.3
        profile = self.store.upsert_for_device(self.device, calib, "我的手柄")
        self.assertIsNotNone(profile)
        matched = self.store.match(self.device)
        self.assertIsNotNone(matched)
        self.assertAlmostEqual(matched.calibration.left.deadzone, 0.3, places=4)
        self.assertEqual(matched.label, "我的手柄")

    def test_same_model_other_port_matches_by_vid_pid(self):
        self.store.upsert_for_device(self.device, DeviceCalibration(), "x")
        other_port = DeviceInfo(key="sdl:7", name="Xbox 360 Controller", backend="sdl",
                                guid="deadbeef", vendor_id=0x045E, product_id=0x028E)
        self.assertIsNotNone(self.store.match(other_port))

    def test_unrelated_device_does_not_match(self):
        self.store.upsert_for_device(self.device, DeviceCalibration(), "x")
        stranger = DeviceInfo(key="sdl:2", name="Some Other Pad", backend="sdl",
                              vendor_id=0x1234, product_id=0x5678)
        self.assertIsNone(self.store.match(stranger))

    def test_export_import(self):
        calib = DeviceCalibration()
        calib.right.deadzone = 0.4
        profile = self.store.upsert_for_device(self.device, calib, "导出方案")
        export_path = Path(self.tmp.name) / "out.json"
        self.assertTrue(self.store.export_file(profile, export_path))
        imported = self.store.import_file(export_path)
        self.assertEqual(len(imported), 1)
        self.assertAlmostEqual(imported[0].calibration.right.deadzone, 0.4, places=4)
        # 原方案不能被覆盖
        self.assertEqual(len(self.store.profiles), 2)

    def test_delete(self):
        profile = self.store.upsert_for_device(self.device, DeviceCalibration(), "删掉")
        self.assertTrue(self.store.delete(profile.id))
        self.assertIsNone(self.store.match(self.device))

    def test_label_defaults_to_device_name(self):
        profile = self.store.upsert_for_device(self.device, DeviceCalibration())
        self.assertEqual(profile.label, "Xbox 360 Controller")

    def test_corrupt_file_is_skipped(self):
        bad = Path(self.tmp.name) / "calibrations" / "broken.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.reload(), self.store.profiles)


class ProfileMatchScoreTests(unittest.TestCase):
    def test_guid_beats_vid_pid(self):
        device = DeviceInfo(key="sdl:1", name="Pad", backend="sdl", guid="ABC",
                            vendor_id=0x045E, product_id=0x028E)
        by_guid = DeviceProfile(guid="abc")
        by_vid = DeviceProfile(vendor_id=0x045E, product_id=0x028E)
        self.assertGreater(by_guid.matches(device), by_vid.matches(device))


if __name__ == "__main__":
    unittest.main()
