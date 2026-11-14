"""JoyCon 协议层测试：报文解析与震动编码（不依赖硬件）."""
import unittest

import gamepadstudio.core.hid.joycon as joycon


class TestRumbleEncoding(unittest.TestCase):
    def test_zero_amplitude_is_neutral(self):
        self.assertEqual(joycon.encode_channel(0.0, 160.0), joycon.NEUTRAL_RUMBLE)
        self.assertEqual(joycon.build_rumble_report(0.0)[:9],
                         b"\x10" + joycon.NEUTRAL_RUMBLE + joycon.NEUTRAL_RUMBLE)

    def test_amplitude_encoding_is_monotonic(self):
        values = [joycon.encode_amp(a / 10) for a in range(1, 11)]
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], values[0])
        self.assertLessEqual(values[-1], 0xFF)

    def test_frequency_clamped_to_documented_range(self):
        hf, lf = joycon.encode_freq(1252.0)
        self.assertLessEqual(hf, 0x01FC)
        self.assertLessEqual(lf, 0x7F)
        hf, lf = joycon.encode_freq(5.0)
        self.assertGreaterEqual(hf, 0x0004)

    def test_rumble_report_layout(self):
        report = joycon.build_rumble_report(0.8, 160.0)
        self.assertEqual(len(report), 64)
        self.assertEqual(report[0], 0x10)
        self.assertEqual(report[9:], bytes(64 - 9))

    def test_subcommand_packet(self):
        packet = joycon.build_subcommand(3, joycon.SET_INPUT_REPORT_MODE, b"\x30")
        self.assertEqual(len(packet), 64)
        self.assertEqual(packet[0], 0x01)
        self.assertEqual(packet[1], 3)
        self.assertEqual(packet[10], joycon.SET_INPUT_REPORT_MODE)
        self.assertEqual(packet[11], 0x30)


def _build_report(a=0, b=0, x=0, y=0, plus=0, minus=0,
                  stick_left=(2048, 2048), stick_right=(2048, 2048)) -> bytes:
    """按 0x30 布局拼一帧输入报文，用于验证解析."""
    report = bytearray(49)
    report[0] = 0x30
    report[1] = 0x00
    report[2] = 0x80 | (6 << 5)  # 满电、USB 连接
    report[3] = (y & 1) | ((x & 1) << 1) | ((b & 1) << 2) | ((a & 1) << 3)
    report[4] = (minus & 1) | ((plus & 1) << 1)
    report[5] = 0
    for offset, (sx, sy) in ((6, stick_left), (9, stick_right)):
        report[offset + 0] = sx & 0xFF
        report[offset + 1] = ((sx >> 8) & 0x0F) | ((sy & 0x0F) << 4)
        report[offset + 2] = (sy >> 4) & 0xFF
    return bytes(report)


class TestInputParsing(unittest.TestCase):
    def test_face_buttons(self):
        parsed = joycon.parse_report(_build_report(a=1, b=1, x=0, y=1), joycon.PRO_CONTROLLER)
        self.assertTrue(parsed["semantic_buttons"]["a"])
        self.assertTrue(parsed["semantic_buttons"]["b"])
        self.assertFalse(parsed["semantic_buttons"]["x"])
        self.assertTrue(parsed["semantic_buttons"]["y"])

    def test_system_buttons(self):
        parsed = joycon.parse_report(_build_report(plus=1, minus=1), joycon.PRO_CONTROLLER)
        self.assertTrue(parsed["semantic_buttons"]["start"])
        self.assertTrue(parsed["semantic_buttons"]["back"])

    def test_stick_conversion(self):
        # 右满偏 -> x≈1，上满偏 -> y≈+1（协议里 Y 向下为正，解析时翻转）
        parsed = joycon.parse_report(_build_report(stick_left=(4095, 0)), joycon.PRO_CONTROLLER)
        self.assertGreater(parsed["semantic_axes"]["lx"], 0.95)
        self.assertGreater(parsed["semantic_axes"]["ly"], 0.95)
        parsed = joycon.parse_report(_build_report(stick_left=(0, 4095)), joycon.PRO_CONTROLLER)
        self.assertLess(parsed["semantic_axes"]["lx"], -0.95)
        self.assertLess(parsed["semantic_axes"]["ly"], -0.95)

    def test_center_is_zero(self):
        parsed = joycon.parse_report(_build_report(), joycon.PRO_CONTROLLER)
        self.assertAlmostEqual(parsed["semantic_axes"]["lx"], 0.0, places=3)
        self.assertAlmostEqual(parsed["semantic_axes"]["ly"], 0.0, places=3)

    def test_battery_decoding(self):
        parsed = joycon.parse_report(_build_report(), joycon.PRO_CONTROLLER)
        self.assertAlmostEqual(parsed["battery"], 1.0)
        self.assertFalse(parsed["charging"])

    def test_short_report_is_ignored(self):
        self.assertEqual(joycon.parse_report(b"\x30\x00", joycon.PRO_CONTROLLER), {})

    def test_single_joycon_only_has_one_stick(self):
        parsed = joycon.parse_report(_build_report(stick_left=(4095, 2048), stick_right=(4095, 2048)),
                                     joycon.JOYCON_R)
        self.assertEqual(parsed["semantic_axes"]["lx"], 0.0)
        self.assertGreater(parsed["semantic_axes"]["rx"], 0.95)


if __name__ == "__main__":
    unittest.main()
