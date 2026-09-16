from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Callable

import serial
from serial import SerialException
from serial.tools import list_ports

from .protocol import DeviceInfo, parse_device_line


ESPRESSIF_USB_VID = 0x303A


@dataclass(frozen=True, slots=True)
class MonitorEvent:
    kind: str
    port: str
    info: DeviceInfo | None = None
    message: str = ""


def is_candidate_port(port: object, scan_all: bool = False) -> bool:
    """Return true for Espressif native USB ports, with an opt-in broad scan."""
    vid = getattr(port, "vid", None)
    if vid == ESPRESSIF_USB_VID:
        return True

    description = str(getattr(port, "description", "") or "").lower()
    manufacturer = str(getattr(port, "manufacturer", "") or "").lower()
    hwid = str(getattr(port, "hwid", "") or "").lower()
    device = str(getattr(port, "device", "") or "").lower()

    if "303a" in hwid and ("vid" in hwid or "usb" in hwid):
        return True
    if "espressif" in manufacturer and any(word in description for word in ("jtag", "serial", "esp32")):
        return True

    if not scan_all or "bluetooth" in description or "bluetooth" in device:
        return False
    return device.startswith("com") or device.startswith("/dev/cu.") or device.startswith("/dev/tty")


class _PortSession(threading.Thread):
    def __init__(
        self,
        port: str,
        callback: Callable[[MonitorEvent], None],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name=f"xmini-port-{port}", daemon=True)
        self.port = port
        self._callback = callback
        self._global_stop = stop_event
        self._local_stop = threading.Event()
        self._serial: serial.Serial | None = None

    def stop(self) -> None:
        self._local_stop.set()
        connection = self._serial
        if connection is not None:
            try:
                connection.cancel_read()
            except (AttributeError, OSError, SerialException):
                pass

    def _stopped(self) -> bool:
        return self._global_stop.is_set() or self._local_stop.is_set()

    def run(self) -> None:
        identified = False
        opened_at = time.monotonic()
        unrecognized_sent = False
        try:
            kwargs: dict[str, object] = {
                "port": self.port,
                "baudrate": 115200,
                "timeout": 0.15,
                "write_timeout": 0.25,
            }
            if os.name != "nt":
                kwargs["exclusive"] = True

            with serial.Serial(**kwargs) as connection:
                self._serial = connection
                try:
                    connection.reset_input_buffer()
                except SerialException:
                    pass

                while not self._stopped():
                    raw = connection.read_until(b"\n", size=1024)
                    if raw:
                        info = parse_device_line(raw)
                        if info is not None:
                            identified = True
                            self._callback(MonitorEvent("device_update", self.port, info=info))

                    if not identified and not unrecognized_sent and time.monotonic() - opened_at >= 3.0:
                        unrecognized_sent = True
                        self._callback(
                            MonitorEvent(
                                "port_unrecognized",
                                self.port,
                                message="端口已连接，但未检测到 xmini-id-v1 固件。",
                            )
                        )
        except (OSError, SerialException) as exc:
            if not self._stopped():
                self._callback(MonitorEvent("port_error", self.port, message=str(exc)))
        finally:
            self._serial = None


class DeviceMonitor:
    """Poll serial topology and keep a reader attached to each candidate USB device."""

    def __init__(
        self,
        callback: Callable[[MonitorEvent], None],
        scan_interval: float = 0.25,
        scan_all: bool | None = None,
    ) -> None:
        self._callback = callback
        self._scan_interval = max(0.1, scan_interval)
        self._scan_all = (
            os.environ.get("XMINI_SCAN_ALL_PORTS", "").strip().lower() in {"1", "true", "yes"}
            if scan_all is None
            else scan_all
        )
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._scan_loop, name="xmini-usb-monitor", daemon=True)
        self._sessions: dict[str, _PortSession] = {}
        self._lock = threading.Lock()
        self._retry_after: dict[str, float] = {}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.stop()
        self._thread.join(timeout=1.0)
        for session in sessions:
            session.join(timeout=0.4)

    def _scan_loop(self) -> None:
        present: set[str] = set()
        while not self._stop_event.is_set():
            try:
                candidates = {
                    port.device: port
                    for port in list_ports.comports()
                    if is_candidate_port(port, self._scan_all)
                }
            except Exception as exc:  # Serial backends can fail transiently during USB topology changes.
                self._callback(MonitorEvent("scan_error", "", message=str(exc)))
                self._stop_event.wait(self._scan_interval)
                continue

            current = set(candidates)
            for removed_port in present - current:
                with self._lock:
                    session = self._sessions.pop(removed_port, None)
                if session is not None:
                    session.stop()
                self._retry_after.pop(removed_port, None)
                self._callback(MonitorEvent("port_removed", removed_port))

            now = time.monotonic()
            for added_port in current - present:
                self._callback(MonitorEvent("port_added", added_port))

            with self._lock:
                dead_ports = [port for port, session in self._sessions.items() if not session.is_alive()]
                for port in dead_ports:
                    self._sessions.pop(port, None)
                    self._retry_after[port] = now + 0.3

                for port in current:
                    if port in self._sessions or now < self._retry_after.get(port, 0):
                        continue
                    session = _PortSession(port, self._callback, self._stop_event)
                    self._sessions[port] = session
                    session.start()

            present = current
            self._stop_event.wait(self._scan_interval)

        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()
