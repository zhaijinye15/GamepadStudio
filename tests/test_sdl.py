"""SDL 后端的健壮性测试：pygame 手柄对象缺少厂商/产品号方法时不能崩."""
import unittest

from gamepadstudio.core.backend_sdl import SdlBackend, _vid_pid


class _FakeStick:
    """模拟 pygame.joystick.JoystickType：故意不提供 get_vendor_id / get_product_id."""

    def __init__(self, name="Xbox Wireless Controller", guid="030000005e0400008e02000000000000"):
        self._name = name
        self._guid = guid

    def get_init(self):
        return True

    def get_name(self):
        return self._name

    def get_guid(self):
        return self._guid

    def get_instance_id(self):
        return 7

    def get_numbuttons(self):
        return 11

    def get_numaxes(self):
        return 6

    def get_numhats(self):
        return 1

    def rumble(self, low, high, duration):
        return None


class _BrokenStick(_FakeStick):
    def get_name(self):
        raise RuntimeError("boom")


class SdlDescribeTest(unittest.TestCase):
    def test_describe_without_vendor_methods(self):
        backend = SdlBackend()
        info = backend._describe(0, _FakeStick())
        self.assertEqual(info.backend, "sdl")
        self.assertEqual(info.name, "Xbox Wireless Controller")
        self.assertEqual(info.buttons, 11)
        self.assertEqual(info.axes, 6)
        self.assertEqual(info.vendor_id, 0x045E)
        self.assertEqual(info.product_id, 0x028E)
        self.assertEqual(info.instance_id, 0)

    def test_describe_survives_broken_getter(self):
        backend = SdlBackend()
        info = backend._describe(0, _BrokenStick())
        self.assertEqual(info.name, "手柄 #0")

    def test_vid_pid_empty_guid(self):
        self.assertEqual(_vid_pid(_FakeStick(guid=""), ""), (0, 0))


if __name__ == "__main__":
    unittest.main()


class PositionMappingTest(unittest.TestCase):
    """真实案例：某只兼容手柄的序号与 SDL 标准表错位（RB 在 b5）。"""

    MAP = {"a": 0, "b": 1, "x": 2, "y": 3, "lb": 4, "rb": 5, "back": 6,
           "start": 7, "l3": 8, "r3": 9, "guide": 10}

    def _state(self, pressed_indexes):
        from gamepadstudio.core.layouts import sdl_state

        raw = {f"b{i}": (i in pressed_indexes) for i in range(16)}
        return sdl_state(raw, {}, (0, 0), button_map=self.MAP)[0]

    def test_rb_maps_to_five(self):
        semantic = self._state({5})
        self.assertTrue(semantic["rb"])
        self.assertFalse(semantic["guide"])

    def test_guide_maps_to_ten(self):
        semantic = self._state({10})
        self.assertTrue(semantic["guide"])
        self.assertFalse(semantic["rb"])

    def test_unmapped_button_does_not_leak(self):
        # b14 不属于该设备的任何语义键，不应被当成方向键
        semantic = self._state({14})
        self.assertFalse(any(semantic.values()))
