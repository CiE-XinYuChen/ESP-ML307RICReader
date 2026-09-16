from __future__ import annotations

from dataclasses import dataclass
import json
import re


PROTOCOL_NAME = "xmini-id-v1"
BOARD_NAME = "xmini-c3-4g"
VALID_STATUSES = {
    "detecting_modem",
    "modem_not_found",
    "reading_iccid",
    "ready",
    "no_sim",
    "iccid_error",
}

_MAC_RE = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
_IMEI_RE = re.compile(r"^[0-9]{15}$")
_ICCID_RE = re.compile(r"^[0-9A-F]{18,24}$")


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    board: str
    status: str
    sta_mac: str
    iccid: str
    modem_baud: int
    uptime_ms: int
    imei: str = ""


def parse_device_line(raw: bytes | str) -> DeviceInfo | None:
    """Parse one log line, ignoring normal ESP-IDF boot and diagnostic output."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="ignore")
    else:
        text = raw

    begin = text.find("{")
    end = text.rfind("}")
    if begin < 0 or end <= begin:
        return None

    try:
        payload = json.loads(text[begin : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None

    if payload.get("protocol") != PROTOCOL_NAME or payload.get("board") != BOARD_NAME:
        return None

    status = payload.get("status")
    sta_mac = str(payload.get("sta_mac", "")).upper()
    iccid = str(payload.get("iccid", "")).upper()
    imei = payload.get("imei", "")
    if not isinstance(imei, str) or (imei and not _IMEI_RE.fullmatch(imei)):
        return None
    if status not in VALID_STATUSES or not _MAC_RE.fullmatch(sta_mac):
        return None
    if iccid and not _ICCID_RE.fullmatch(iccid):
        return None

    try:
        modem_baud = int(payload.get("modem_baud", 0))
        uptime_ms = int(payload.get("uptime_ms", 0))
    except (TypeError, ValueError):
        return None
    if modem_baud < 0 or uptime_ms < 0:
        return None

    return DeviceInfo(
        board=BOARD_NAME,
        status=status,
        sta_mac=sta_mac,
        iccid=iccid,
        modem_baud=modem_baud,
        uptime_ms=uptime_ms,
        imei=imei,
    )
