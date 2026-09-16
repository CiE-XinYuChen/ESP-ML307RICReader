# xmini-c3-4g STA MAC / ICCID / IMEI 读取器

本项目包含两部分：

- `firmware`（项目根目录和 `main/`）：ESP-IDF 5.5 固件，读取 ESP32-C3 STA MAC，通过 ML307R AT 指令读取 SIM ICCID 和模组 IMEI。
- `gui/`：Python/Tk 桌面端，支持 macOS 和 Windows，每 250 ms 检测 USB 串口拓扑变化。

数据只在 USB 串口与本地 GUI 之间传输，不需要联网。

## 硬件与协议依据

参考 `xiaozhi-2.2.6+` 的 `xmini-c3-4g` 板级定义：

| 信号 | ESP32-C3 端 | 说明 |
| --- | --- | --- |
| ML307R TX | GPIO2 | ESP 发送 / 模组接收 |
| ML307R RX | GPIO0 | ESP 接收 / 模组发送 |
| ML307R DTR | GPIO1 | 低电平唤醒模组 |
| PC 通信 | USB Serial/JTAG | ESP32-C3 原生 USB |

原小智固件会将 ML307R 设为 921600 baud。本固件会先探测 921600，同时兼容 115200、460800、230400、57600、38400、19200 和 9600，不依赖模组当前的持久化波特率。ICCID 使用 `AT+ICCID` 读取，无需等待蜂窝网络注册；兼容部分 ML307R/SIM 返回值中出现的十六进制字符 `A-F`。

IMEI 使用 `AT+CGSN=1` 读取，接受 15 位数字（带 `+CGSN:` 前缀、引号或纯数字响应）。即使未插 SIM 卡也会尝试读取；成功后缓存，失败后每 1.5 秒重试，重新探测模组时清空缓存。GUI 支持显示和复制 IMEI，历史记录会在 IMEI 延迟读到后补全。

JSON 新增 `imei` 字段，未读到时为空字符串。协议名保持不变，`status` 仍表示原有模组/ICCID 状态，IMEI 是否成功以该字段为准；新 GUI 兼容没有 `imei` 字段的旧固件。

固件通过 USB 约每 500 ms 输出一行 JSON（AT 查询期间可能延迟）：

```json
{"protocol":"xmini-id-v1","board":"xmini-c3-4g","status":"ready","sta_mac":"A0:B1:C2:D3:E4:F5","iccid":"89860012345678901234","imei":"868482050123456","modem_baud":921600,"uptime_ms":1234}
```

GUI 只接受 `xmini-id-v1` + `xmini-c3-4g` 握手，普通串口日志不会被误判为目标设备。

## 1. 编译和烧录固件

> 烧录本固件会覆盖设备上现有的小智固件。

```bash
cd /Users/shaynechen/shayne/esp/xiaozhi/ml307riccidreaderesp32
idf55
idf.py set-target esp32c3
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash
idf.py merge-bin -o xmini_iccid_reader-merged.bin
```

`idf.py flash` 会按正确地址分别烧录 bootloader、分区表和应用程序。不要将 `build/xmini_iccid_reader.bin` 烧录到 `0x0`；它只是应用程序镜像，偏移地址是 `0x10000`。

需要单文件烧录时，先执行上面的 `merge-bin` 命令。生成的 `build/xmini_iccid_reader-merged.bin` 已包含所有镜像，只有这个合并文件应烧录到 Flash 偏移地址 `0x0`。

如果当前机器的 `idf55` 别名提示缺少 `idf5.5_py3.14_env`，而已安装环境是 Python 3.13，可仅在当前终端使用：

```bash
conda activate esp-idf-5.5
export IDF_PYTHON_ENV_PATH=/Users/shaynechen/.espressif/python_env/idf5.5_py3.13_env
source /Users/shaynechen/shayne/esp/esp-idf-v5.5.4/export.sh
```

Windows 上的烧录端口形如 `COM8`。实际端口可用以下命令查看：

```bash
python -m serial.tools.list_ports -v
```

## 2. 运行 GUI 源码

macOS：

```bash
cd /Users/shaynechen/shayne/esp/xiaozhi/ml307riccidreaderesp32/gui
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_gui.py
```

Windows PowerShell：

```powershell
cd "ml307riccidreaderesp32\gui"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run_gui.py
```

默认只会打开 Espressif VID `0x303A` 的原生 USB 串口。如果未来的硬件改用 CH340/CP210x，可在启动 GUI 前设置 `XMINI_SCAN_ALL_PORTS=1`，GUI 仍会通过协议握手确认设备。

## 3. 打包 macOS / Windows 独立应用

Windows 安装 Python 3.10 或更新版本（包含 Tk 和 Python Launcher）后，可双击 `gui/build_windows.cmd`。脚本会创建虚拟环境、安装依赖、运行测试并生成 `gui/dist/XMiniICCIDReader.exe`，最终用户无需安装 Python。

也可通过 `.github/workflows/windows-exe.yml` 在 GitHub Actions 的 Windows x64 环境构建。上传 GUI 或工作流修改后自动触发，也支持手动运行；构建成功后，在对应运行的 Artifacts 中下载 `XMiniICCIDReader-Windows-x64`，其中包含 EXE 和 SHA256 校验文件。

PyInstaller 不能交叉编译，请分别在 macOS 和 Windows 上执行：

```bash
python -m pip install -r requirements-build.txt
python build_gui.py
```

输出位于 `gui/dist/`：macOS 为 `XMiniICCIDReader.app`，Windows 为 `XMiniICCIDReader.exe`。
请在目标系统/架构上打包（例如 Apple Silicon 和 Intel Mac 分别打包）；对外分发 macOS 版时建议再用 Developer ID 签名并公证。

## 热插拔行为

- 插入：250 ms 轮询发现 USB 端口，收到固件心跳后显示 STAIF MAC、ICCID 和 IMEI。
- 拔出：立即关闭对应串口会话并清空当前值。
- 插入下一块：自动选中最新插入的端口，不需要手动点击刷新。
- 读取成功的设备会加入本次运行的历史表，方便连续扫描。

## 测试 GUI 逻辑

```bash
cd gui
python -m unittest discover -s tests -v
```
