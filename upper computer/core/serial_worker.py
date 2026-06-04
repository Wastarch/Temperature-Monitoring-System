"""
串口通信模块

功能：
- 串口扫描（支持检测 Windows 注册表中的虚拟串口）
- 串口数据读取（后台线程）
- 解析下位机发送的二进制温度数据帧
- 支持配置数据处理间隔

数据帧格式（可变长度）：
┌──────┬────┬─────────────────────────┬──────┬──────┐
│ 0xAA │ N  │ CH1 DATA ... CHn DATA   │ XOR  │ 0x0A │
│ 起始  │ 通道数 │ N组通道数据(每组3字节) │ 校验 │ 结束 │
└──────┴────┴─────────────────────────┴──────┴──────┘

帧总长度 = N x 3 + 4 字节

- 起始位：0xAA（固定）
- 通道数 N：0x01~0x08
- 每组通道数据：CH(1字节) + Data_H(1字节) + Data_L(1字节)
- 校验：XOR = N ^ CH1 ^ Data_H1 ^ Data_L1 ^ ... ^ CHn ^ Data_Hn ^ Data_Ln
- 结束符：0x0A（固定）
"""

import sys
import time

import serial
import serial.tools.list_ports
from PySide6.QtCore import QThread, Signal


# 帧常量
FRAME_START = 0xAA
FRAME_END = 0x0A
FRAME_MIN_LENGTH = 6  # 最小帧长度（1通道：起始+通道数+3字节数据+校验+结束）


def parse_binary_frame(data: bytes) -> list[tuple[int, float]] | None:
    """
    解析二进制温度数据帧

    Args:
        data: 帧数据（可变长度）

    Returns:
        [(通道号, 温度值), ...] 列表，解析失败返回 None

    帧格式：[0xAA] [N] [CH1 Data_H Data_L ... CHn Data_H Data_L] [XOR] [0x0A]
    """
    # 基本长度检查
    if len(data) < FRAME_MIN_LENGTH:
        return None

    # 检查起始位和结束位
    if data[0] != FRAME_START or data[-1] != FRAME_END:
        return None

    # 获取通道数
    n = data[1]
    if n < 1 or n > 8:
        return None

    # 检查帧长度
    expected_len = n * 3 + 4
    if len(data) != expected_len:
        return None

    # 提取数据区
    channel_data = data[2:2 + n * 3]
    xor_recv = data[2 + n * 3]

    # 计算校验
    xor_calc = n
    for b in channel_data:
        xor_calc ^= b

    if xor_calc != xor_recv:
        return None

    # 解析各通道数据
    result = []
    for i in range(n):
        ch = channel_data[i * 3]
        data_h = channel_data[i * 3 + 1]
        data_l = channel_data[i * 3 + 2]

        # 解析温度（16位有符号整数，大端序）
        raw_value = (data_h << 8) | data_l
        if raw_value > 32767:
            raw_value -= 65536
        temp = raw_value / 10.0

        result.append((ch, temp))

    return result


def list_available_ports() -> list[str]:
    """
    扫描系统可用的串口

    Returns:
        串口设备名列表，按 COM 号排序
    """
    # 方法1: pyserial 标准扫描
    ports = [p.device for p in serial.tools.list_ports.comports()]

    # 方法2: Windows 注册表扫描（检测虚拟串口）
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DEVICEMAP\SERIALCOMM",
            )
            i = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, i)
                    if value not in ports:
                        ports.append(value)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    # 按 COM 号数字排序
    def port_sort_key(port: str):
        if port.startswith("COM"):
            try:
                return (0, int(port[3:]))
            except ValueError:
                pass
        return (1, port)

    ports.sort(key=port_sort_key)
    return ports


class SerialWorker(QThread):
    """
    串口通信工作线程

    支持单串口多通道模式：从一个串口接收多个通道的二进制数据帧
    支持配置数据处理间隔

    信号：
        temperature_received(channel_id, temp): 接收到温度数据
        raw_data_received(hex_str, result): 接收到原始数据和解析结果
        connection_changed(connected): 连接状态变化
        error_occurred(error_msg): 发生错误
    """

    temperature_received = Signal(int, float)
    raw_data_received = Signal(str, list)
    connection_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, port: str, baudrate: int = 9600, interval_ms: int = 1000):
        """
        初始化串口工作线程

        Args:
            port: 串口设备名（如 "COM10"）
            baudrate: 波特率
            interval_ms: 数据处理间隔（毫秒）
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.interval_ms = interval_ms
        self._running = False

    def run(self):
        """线程主循环：打开串口，持续读取并解析二进制帧"""
        self._running = True

        # 打开串口
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
            self.connection_changed.emit(True)
        except Exception as e:
            self.error_occurred.emit(f"串口打开失败: {e}")
            self.connection_changed.emit(False)
            return

        # 循环读取数据
        try:
            buffer = bytearray()
            last_process_time = time.time() * 1000

            while self._running:
                # 读取可用数据
                data = ser.read(ser.in_waiting or 1)
                if not data:
                    continue
                buffer.extend(data)

                # 检查是否到达处理间隔
                current_time = time.time() * 1000
                if current_time - last_process_time < self.interval_ms:
                    continue

                # 从缓冲区中查找帧
                while len(buffer) >= FRAME_MIN_LENGTH:
                    # 查找起始位 0xAA
                    start_idx = buffer.find(FRAME_START)
                    if start_idx < 0:
                        buffer.clear()
                        break

                    # 移除起始位之前的数据
                    if start_idx > 0:
                        buffer = buffer[start_idx:]

                    # 检查是否有足够的数据读取通道数
                    if len(buffer) < 2:
                        break

                    # 获取通道数
                    n = buffer[1]
                    if n < 1 or n > 8:
                        # 无效通道数，跳过这个起始位
                        hex_str = " ".join(f"{b:02X}" for b in buffer[:min(len(buffer), 20)])
                        self.error_occurred.emit(f"通道数错误: {n} (应为1-8) -> {hex_str}")
                        buffer = buffer[1:]
                        continue

                    # 计算帧长度
                    frame_len = n * 3 + 4

                    # 检查是否有完整帧
                    if len(buffer) < frame_len:
                        break

                    # 提取一帧数据
                    frame = bytes(buffer[:frame_len])

                    # 解析帧
                    result = parse_binary_frame(frame)
                    if result is not None:
                        # 发送原始数据和解析结果
                        hex_str = " ".join(f"{b:02X}" for b in frame)
                        self.raw_data_received.emit(hex_str, result)

                        # 发送各通道温度数据
                        for ch, temp in result:
                            self.temperature_received.emit(ch, temp)
                    else:
                        # 校验失败
                        hex_str = " ".join(f"{b:02X}" for b in frame)
                        self.error_occurred.emit(f"校验失败: {hex_str}")

                    # 移除已处理的帧
                    buffer = buffer[frame_len:]
                    last_process_time = current_time

        except Exception as e:
            if self._running:
                self.error_occurred.emit(f"串口读取错误: {e}")
        finally:
            # 关闭串口并通知连接断开
            try:
                ser.close()
            except Exception:
                pass
            self.connection_changed.emit(False)

    def stop(self):
        """安全停止线程"""
        self._running = False
        self.wait(2000)  # 等待线程结束，超时 2 秒
