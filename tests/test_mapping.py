"""映射方案与输入换算测试."""
import json
import tempfile
import unittest
from pathlib import Path

from gamepadstudio.core import layouts
from gamepadstudio.core.mapping import (
    Binding,
    MappingProfile,
    all_sources,
    detect_capture,
    describe_action,
    describe_source,
)
from gamepadstudio.core.model import PadState, apply_deadzone, normalize_trigger, radial_deadzone


def make_state(**kwargs) -> PadState:
    buttons = {name: False for name in (
        "a", "b", "x", "y", "lb", "rb", "lt", "rt", "up", "down", "left", "right",
        "back", "start", "guide", "l3", "r3")}
    buttons.update(kwargs.pop("buttons", {}))
    axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0}
    axes.update(kwargs.pop("axes", {}))
    return PadState(semantic_buttons=buttons, semantic_axes=axes)


class TestModelHelpers(unittest.TestCase):
    def test_deadzone_zeroes_small_values(self):
        self.assertEqual(apply_deadzone(0.1, 0.2), 0.0)
        self.assertGreater(apply_deadzone(0.9, 0.2), 0.8)

    def test_radial_deadzone_keeps_direction(self):
        x, y = radial_deadzone(0.5, 0.5, 0.2)
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)
        self.assertAlmostEqual(x, y)
        self.assertEqual(radial_deadzone(0.05, 0.02, 0.2), (0.0, 0.0))

    def test_trigger_normalization(self):
        self.assertEqual(normalize_trigger(-1.0), 0.0)
        self.assertEqual(normalize_trigger(1.0), 1.0)
        self.assertAlmostEqual(normalize_trigger(0.0), 0.5)


class TestLayouts(unittest.TestCase):
    def test_hat_becomes_dpad(self):
        buttons, _ = layouts.sdl_state({}, {}, (1, 1))
        self.assertTrue(buttons["up"])
        self.assertTrue(buttons["right"])

    def test_trigger_axes_normalized(self):
        _, axes = layouts.sdl_state({}, {"a4": -1.0, "a5": 1.0}, (0, 0))
        self.assertEqual(axes["lt"], 0.0)
        self.assertEqual(axes["rt"], 1.0)

    def test_layout_detection(self):
        self.assertEqual(layouts.detect_layout("Xbox Wireless Controller"), "xbox")
        self.assertEqual(layouts.detect_layout("Wireless Controller"), "playstation")
        self.assertEqual(layouts.detect_layout("Joy-Con (R)"), "switch")
        self.assertEqual(layouts.detect_layout("USB Gamepad"), "generic")


class TestMappingProfile(unittest.TestCase):
    def test_json_roundtrip(self):
        profile = MappingProfile(
            name="测试方案",
            target="keyboard",
            deadzone=0.2,
            bindings=[Binding("button:a", "keyboard:W"), Binding("axis:rt:+", "keyboard:SPACE")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            profile.save(path)
            loaded = MappingProfile.load(path)
        self.assertEqual(loaded.name, "测试方案")
        self.assertEqual(len(loaded.bindings), 2)
        self.assertEqual(loaded.to_dict(), profile.to_dict())

    def test_unknown_source_is_dropped(self):
        profile = MappingProfile.from_dict({
            "schema": "gamepadstudio.mapping/1",
            "bindings": [{"source": "button:unknown", "action": "keyboard:W"},
                          {"source": "button:a", "action": "keyboard:W"}],
        })
        self.assertEqual(len(profile.bindings), 1)
        self.assertTrue(profile.warnings)

    def test_unknown_key_becomes_none(self):
        profile = MappingProfile.from_dict({
            "bindings": [{"source": "button:a", "action": "keyboard:NOT_A_KEY"}],
        })
        self.assertEqual(profile.bindings[0].action, "none")

    def test_bad_schema_rejected(self):
        with self.assertRaises(ValueError):
            MappingProfile.from_dict({"schema": "other/9"})

    def test_active_sources(self):
        state = make_state(buttons={"a": True}, axes={"rt": 0.7})
        profile = MappingProfile(deadzone=0.1)
        active = profile.active_sources(state)
        self.assertIn("button:a", active)
        self.assertIn("axis:rt:+", active)
        self.assertAlmostEqual(active["axis:rt:+"], 0.7)

    def test_deadzone_applies_to_sticks(self):
        profile = MappingProfile(deadzone=0.3, invert_axes=[])
        axes = profile.resolved_axes(make_state(axes={"lx": 0.1, "ly": 0.05}))
        self.assertEqual((axes["lx"], axes["ly"]), (0.0, 0.0))

    def test_invert_flips_axis(self):
        profile = MappingProfile(invert_axes=["ly"])
        axes = profile.resolved_axes(make_state(axes={"ly": 0.8}))
        self.assertLess(axes["ly"], 0)

    def test_axis_threshold_blocks_small_movement(self):
        profile = MappingProfile(deadzone=0.0, bindings=[Binding("axis:lx:+", "keyboard:D", threshold=0.6)])
        outputs = profile.evaluate(make_state(axes={"lx": 0.4}))
        self.assertNotIn("keyboard:D", outputs)
        outputs = profile.evaluate(make_state(axes={"lx": 0.9}))
        self.assertIn("keyboard:D", outputs)

    def test_button_binding(self):
        profile = MappingProfile(bindings=[Binding("button:a", "keyboard:SPACE")])
        outputs = profile.evaluate(make_state(buttons={"a": True}))
        self.assertIn("keyboard:SPACE", outputs)


class TestCapture(unittest.TestCase):
    def test_button_press_capture(self):
        previous = make_state()
        current = make_state(buttons={"rb": True})
        self.assertEqual(detect_capture(previous, current, 0.15), "button:rb")

    def test_trigger_capture(self):
        previous = make_state(axes={"rt": 0.0})
        current = make_state(axes={"rt": 0.6})
        self.assertEqual(detect_capture(previous, current, 0.15), "axis:rt:+")

    def test_no_change(self):
        state = make_state()
        self.assertIsNone(detect_capture(state, state, 0.15))


class TestDescriptions(unittest.TestCase):
    def test_source_description(self):
        self.assertIn("A", describe_source("button:a"))
        self.assertIn("左摇杆", describe_source("axis:lx:-"))

    def test_action_description(self):
        self.assertEqual(describe_action("keyboard:W"), "按键 W")
        self.assertEqual(describe_action("none"), "不输出")

    def test_all_sources_are_describable(self):
        for source in all_sources():
            self.assertTrue(describe_source(source))


if __name__ == "__main__":
    unittest.main()
