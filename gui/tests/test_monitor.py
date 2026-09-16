from types import SimpleNamespace
import unittest

from xmini_reader.monitor import is_candidate_port


def fake_port(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "vid": None,
        "pid": None,
        "description": "",
        "manufacturer": "",
        "hwid": "",
        "device": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class CandidatePortTests(unittest.TestCase):
    def test_accepts_espressif_vid(self) -> None:
        self.assertTrue(is_candidate_port(fake_port(vid=0x303A, device="COM8")))

    def test_accepts_windows_hwid(self) -> None:
        self.assertTrue(is_candidate_port(fake_port(hwid="USB VID:PID=303A:1001", device="COM8")))

    def test_rejects_unrelated_serial_port_by_default(self) -> None:
        self.assertFalse(is_candidate_port(fake_port(vid=0x1A86, device="COM3")))

    def test_scan_all_accepts_usb_serial_but_not_bluetooth(self) -> None:
        self.assertTrue(is_candidate_port(fake_port(device="/dev/cu.usbserial-10"), scan_all=True))
        self.assertFalse(
            is_candidate_port(
                fake_port(device="/dev/cu.Bluetooth-Incoming-Port", description="Bluetooth"),
                scan_all=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
