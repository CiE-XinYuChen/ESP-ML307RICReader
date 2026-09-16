import json
import unittest

from xmini_reader.protocol import parse_device_line


class ProtocolTests(unittest.TestCase):
    def valid_payload(self) -> dict[str, object]:
        return {
            "protocol": "xmini-id-v1",
            "board": "xmini-c3-4g",
            "status": "ready",
            "sta_mac": "A0:B1:C2:D3:E4:F5",
            "iccid": "89860012345678901234",
            "imei": "868482050123456",
            "modem_baud": 921600,
            "uptime_ms": 1234,
        }

    def test_parses_valid_json_line(self) -> None:
        result = parse_device_line(json.dumps(self.valid_payload()).encode())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.sta_mac, "A0:B1:C2:D3:E4:F5")
        self.assertEqual(result.iccid, "89860012345678901234")
        self.assertEqual(result.imei, "868482050123456")

    def test_accepts_old_firmware_without_imei(self) -> None:
        payload = self.valid_payload()
        del payload["imei"]
        result = parse_device_line(json.dumps(payload))
        self.assertIsNotNone(result)
        self.assertEqual(result.imei, "")

    def test_accepts_empty_imei_while_retrying(self) -> None:
        payload = self.valid_payload()
        payload["imei"] = ""
        self.assertIsNotNone(parse_device_line(json.dumps(payload)))

    def test_accepts_imei_without_sim(self) -> None:
        payload = self.valid_payload()
        payload.update(status="no_sim", iccid="")
        result = parse_device_line(json.dumps(payload))
        self.assertIsNotNone(result)
        self.assertEqual(result.imei, payload["imei"])

    def test_rejects_invalid_imei(self) -> None:
        for imei in ("1234", "8684820501234567", "86848205012345A", "８６８４８２０５０１２３４５６", 868482050123456, None):
            with self.subTest(imei=imei):
                payload = self.valid_payload()
                payload["imei"] = imei
                self.assertIsNone(parse_device_line(json.dumps(payload)))

    def test_ignores_idf_log_prefix(self) -> None:
        line = "I (123) app: " + json.dumps(self.valid_payload())
        self.assertIsNotNone(parse_device_line(line))

    def test_ignores_other_protocols(self) -> None:
        payload = self.valid_payload()
        payload["protocol"] = "something-else"
        self.assertIsNone(parse_device_line(json.dumps(payload)))

    def test_rejects_invalid_mac(self) -> None:
        payload = self.valid_payload()
        payload["sta_mac"] = "not-a-mac"
        self.assertIsNone(parse_device_line(json.dumps(payload)))

    def test_rejects_invalid_iccid(self) -> None:
        payload = self.valid_payload()
        payload["iccid"] = "1234"
        self.assertIsNone(parse_device_line(json.dumps(payload)))

    def test_accepts_hexadecimal_iccid_from_ml307r(self) -> None:
        payload = self.valid_payload()
        payload["iccid"] = "898602b9122380024381"
        result = parse_device_line(json.dumps(payload))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.iccid, "898602B9122380024381")

    def test_allows_empty_iccid_while_detecting(self) -> None:
        payload = self.valid_payload()
        payload["status"] = "reading_iccid"
        payload["iccid"] = ""
        result = parse_device_line(json.dumps(payload))
        self.assertIsNotNone(result)

    def test_ignores_boot_log(self) -> None:
        self.assertIsNone(parse_device_line("I (42) boot: ESP-IDF v5.5.4"))


if __name__ == "__main__":
    unittest.main()
