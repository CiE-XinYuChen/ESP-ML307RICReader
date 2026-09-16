from __future__ import annotations

from datetime import datetime
import queue
import tkinter as tk
from tkinter import ttk

from .monitor import DeviceMonitor, MonitorEvent
from .protocol import DeviceInfo


STATUS_TEXT = {
    "detecting_modem": "正在检测 ML307R…",
    "modem_not_found": "未检测到 ML307R",
    "reading_iccid": "正在读取 ICCID…",
    "ready": "设备已就绪",
    "no_sim": "未检测到 SIM 卡",
    "iccid_error": "ICCID 读取失败，正在重试",
}

STATUS_COLOR = {
    "ready": "#16A34A",
    "no_sim": "#D97706",
    "detecting_modem": "#2563EB",
    "reading_iccid": "#2563EB",
    "modem_not_found": "#DC2626",
    "iccid_error": "#DC2626",
}


class ReaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("XMini 设备标识读取器")
        self.root.geometry("920x660")
        self.root.minsize(860, 610)
        self.root.configure(background="#F3F5F8")

        self._events: queue.Queue[MonitorEvent] = queue.Queue()
        self._physical_ports: set[str] = set()
        self._devices: dict[str, DeviceInfo] = {}
        self._active_port: str | None = None
        self._history_rows: dict[tuple[str, str], str] = {}

        self.status_var = tk.StringVar(value="等待设备")
        self.port_var = tk.StringVar(value="未连接")
        self.mac_var = tk.StringVar(value="—")
        self.iccid_var = tk.StringVar(value="—")
        self.imei_var = tk.StringVar(value="—")
        self.detail_var = tk.StringVar(value="插入已烧录识别固件的 xmini-c3-4g，软件会自动刷新。")

        self._configure_style()
        self._build_ui()

        self.monitor = DeviceMonitor(self._events.put)
        self.monitor.start()
        self.root.after(50, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        for preferred in ("clam", "vista", "aqua"):
            if preferred in style.theme_names():
                style.theme_use(preferred)
                break
        style.configure("App.TFrame", background="#F3F5F8")
        style.configure("Card.TFrame", background="#FFFFFF")
        style.configure("Title.TLabel", background="#F3F5F8", foreground="#111827", font=("TkDefaultFont", 22, "bold"))
        style.configure("Subtitle.TLabel", background="#F3F5F8", foreground="#6B7280", font=("TkDefaultFont", 10))
        style.configure("CardLabel.TLabel", background="#FFFFFF", foreground="#6B7280", font=("TkDefaultFont", 10))
        style.configure("Status.TLabel", background="#FFFFFF", foreground="#111827", font=("TkDefaultFont", 12, "bold"))
        style.configure("Port.TLabel", background="#FFFFFF", foreground="#6B7280", font=("TkDefaultFont", 9))
        style.configure("Hint.TLabel", background="#F3F5F8", foreground="#6B7280", font=("TkDefaultFont", 9))
        style.configure("Treeview", rowheight=26)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(28, 24, 28, 20))
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="XMini 设备标识读取器", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="xmini-c3-4g  ·  STA MAC / SIM ICCID / ML307R IMEI  ·  USB 热插拔",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(3, 18))

        card = ttk.Frame(outer, style="Card.TFrame", padding=(22, 18))
        card.pack(fill=tk.X)

        status_row = ttk.Frame(card, style="Card.TFrame")
        status_row.pack(fill=tk.X, pady=(0, 16))
        self.status_dot = tk.Canvas(status_row, width=14, height=14, bg="#FFFFFF", highlightthickness=0)
        self.status_dot.pack(side=tk.LEFT, padx=(0, 9))
        self._paint_status_dot("#9CA3AF")
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.port_var, style="Port.TLabel").pack(side=tk.RIGHT)

        self._add_value_field(card, "STAIF MAC", self.mac_var)
        self._add_value_field(card, "ICCID", self.iccid_var)
        self._add_value_field(card, "IMEI", self.imei_var)

        ttk.Label(card, textvariable=self.detail_var, style="CardLabel.TLabel", wraplength=650).pack(
            anchor=tk.W, pady=(8, 0)
        )

        history_header = ttk.Frame(outer, style="App.TFrame")
        history_header.pack(fill=tk.X, pady=(20, 7))
        ttk.Label(history_header, text="本次读取记录", style="Subtitle.TLabel").pack(side=tk.LEFT)
        clear_button = ttk.Button(history_header, text="清空", command=self._clear_history)
        clear_button.pack(side=tk.RIGHT)

        self.history = ttk.Treeview(
            outer,
            columns=("time", "mac", "iccid", "imei"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self.history.heading("time", text="时间")
        self.history.heading("mac", text="STAIF MAC")
        self.history.heading("iccid", text="ICCID")
        self.history.heading("imei", text="IMEI")
        self.history.column("imei", width=190, minwidth=170, anchor=tk.CENTER)
        self.history.column("time", width=90, minwidth=80, anchor=tk.CENTER, stretch=False)
        self.history.column("mac", width=190, minwidth=170, anchor=tk.CENTER)
        self.history.column("iccid", width=250, minwidth=210, anchor=tk.CENTER)
        self.history.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer,
            text="数据只在本机串口与 GUI 之间传输，不会上传网络。",
            style="Hint.TLabel",
        ).pack(anchor=tk.W, pady=(12, 0))

    def _add_value_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label, style="CardLabel.TLabel").pack(anchor=tk.W)
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill=tk.X, pady=(4, 14))
        entry = ttk.Entry(row, textvariable=variable, state="readonly", font=("TkFixedFont", 16))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="复制", command=lambda value=variable: self._copy(value.get())).pack(side=tk.LEFT, padx=(10, 0))

    def _copy(self, value: str) -> None:
        if not value or value == "—":
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()

    def _paint_status_dot(self, color: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline=color)

    def _drain_events(self) -> None:
        try:
            while True:
                self._handle_event(self._events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self._drain_events)

    def _handle_event(self, event: MonitorEvent) -> None:
        if event.kind == "port_added":
            self._physical_ports.add(event.port)
            self._active_port = event.port
            self.port_var.set(event.port)
            self.mac_var.set("—")
            self.iccid_var.set("—")
            self.imei_var.set("—")
            self.status_var.set("正在识别设备…")
            self.detail_var.set("已检测到 Espressif USB 串口，正在等待固件数据。")
            self._paint_status_dot("#2563EB")
            return

        if event.kind == "device_update" and event.info is not None:
            self._devices[event.port] = event.info
            if self._active_port is None or self._active_port not in self._physical_ports:
                self._active_port = event.port
            if self._active_port == event.port:
                self._show_device(event.port, event.info)
            self._record_ready_device(event.info)
            return

        if event.kind == "port_removed":
            self._physical_ports.discard(event.port)
            self._devices.pop(event.port, None)
            if self._active_port == event.port:
                self._active_port = next(iter(self._physical_ports), None)
                if self._active_port and self._active_port in self._devices:
                    self._show_device(self._active_port, self._devices[self._active_port])
                elif self._active_port:
                    self.port_var.set(self._active_port)
                    self.mac_var.set("—")
                    self.iccid_var.set("—")
                    self.imei_var.set("—")
                    self.status_var.set("正在识别设备…")
                    self._paint_status_dot("#2563EB")
                else:
                    self._show_disconnected()
            return

        if event.kind == "port_unrecognized" and self._active_port == event.port:
            self.status_var.set("未识别到读取器固件")
            self.detail_var.set(event.message)
            self._paint_status_dot("#D97706")
            return

        if event.kind == "port_error" and self._active_port == event.port:
            self.status_var.set("串口暂时不可用")
            self.detail_var.set(f"{event.port}: {event.message}")
            self._paint_status_dot("#DC2626")
            return

        if event.kind == "scan_error" and not self._physical_ports:
            self.status_var.set("串口检测失败")
            self.detail_var.set(event.message)
            self._paint_status_dot("#DC2626")

    def _show_device(self, port: str, info: DeviceInfo) -> None:
        self.port_var.set(port)
        self.mac_var.set(info.sta_mac)
        self.iccid_var.set(info.iccid or "—")
        self.imei_var.set(info.imei or "—")
        self.status_var.set(STATUS_TEXT.get(info.status, info.status))
        self._paint_status_dot(STATUS_COLOR.get(info.status, "#9CA3AF"))
        if info.status == "ready":
            self.detail_var.set(f"ML307R 串口速率 {info.modem_baud} baud；拔出设备后界面会自动清空。")
        elif info.status == "no_sim":
            self.detail_var.set("请确认 SIM 卡已装好；固件会自动持续重试。")
        else:
            self.detail_var.set("固件正在自动检测 ML307R 并读取设备信息。")
        if not info.imei and info.modem_baud:
            self.detail_var.set(self.detail_var.get() + " IMEI 尚未读到；新固件会自动重试，旧固件需升级。")

    def _show_disconnected(self) -> None:
        self.port_var.set("未连接")
        self.mac_var.set("—")
        self.iccid_var.set("—")
        self.imei_var.set("—")
        self.status_var.set("等待设备")
        self.detail_var.set("插入已烧录识别固件的 xmini-c3-4g，软件会自动刷新。")
        self._paint_status_dot("#9CA3AF")

    def _record_ready_device(self, info: DeviceInfo) -> None:
        if info.status != "ready" or not info.iccid:
            return
        key = (info.sta_mac, info.iccid)
        if key in self._history_rows:
            if info.imei:
                self.history.set(self._history_rows[key], "imei", info.imei)
            return
        self._history_rows[key] = self.history.insert(
            "", 0, values=(datetime.now().strftime("%H:%M:%S"), info.sta_mac, info.iccid, info.imei)
        )

    def _clear_history(self) -> None:
        self._history_rows.clear()
        for item in self.history.get_children():
            self.history.delete(item)

    def _close(self) -> None:
        self.monitor.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ReaderApp(root)
    root.mainloop()
