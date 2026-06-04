"""
温度数据管理模块

功能：
- 按通道存储温度数据（使用 deque 自动限制内存）
- 获取历史数据（支持按时间范围查询）
- 导出数据为 CSV / Excel 格式
"""

import csv
from collections import deque
from datetime import datetime

from openpyxl import Workbook
from PySide6.QtCore import QObject, Signal


class DataManager(QObject):
    """温度数据管理器，支持多通道数据存储和导出"""

    # 数据更新信号，参数为通道号
    data_updated = Signal(int)

    def __init__(self, max_records: int = 10000):
        """
        初始化数据管理器

        Args:
            max_records: 每个通道最大存储记录数，超出后自动丢弃旧数据
        """
        super().__init__()
        self.max_records = max_records
        # 按通道存储数据，每个通道使用 deque 实现 FIFO
        self._data: dict[int, deque[tuple[datetime, float]]] = {}

    def _ensure_channel(self, channel: int):
        """确保指定通道的数据容器存在"""
        if channel not in self._data:
            self._data[channel] = deque(maxlen=self.max_records)

    def add_record(self, channel: int, temp: float, timestamp: datetime = None):
        """
        添加一条温度记录

        Args:
            channel: 通道号（1 或 2）
            temp: 温度值（摄氏度）
            timestamp: 时间戳，默认为当前时间
        """
        self._ensure_channel(channel)
        self._data[channel].append((timestamp or datetime.now(), temp))
        self.data_updated.emit(channel)

    def get_history(self, channel: int, seconds: int = 300) -> list[tuple[datetime, float]]:
        """
        获取指定通道的历史数据

        Args:
            channel: 通道号
            seconds: 获取最近多少秒的数据，0 表示全部

        Returns:
            [(时间戳, 温度值), ...] 的列表
        """
        self._ensure_channel(channel)
        if seconds <= 0:
            return list(self._data[channel])
        now = datetime.now()
        cutoff = now.timestamp() - seconds
        return [(ts, t) for ts, t in self._data[channel] if ts.timestamp() >= cutoff]

    def get_all(self, channel: int) -> list[tuple[datetime, float]]:
        """获取指定通道的全部数据"""
        self._ensure_channel(channel)
        return list(self._data[channel])

    def export_csv(self, filepath: str, channels: list[int]):
        """
        导出数据为 CSV 文件

        Args:
            filepath: 保存路径
            channels: 要导出的通道列表
        """
        rows = self._merge_channels(channels)
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            # 写入表头
            header = ["时间戳"]
            for ch in channels:
                header.append(f"CH{ch}温度(°C)")
            writer.writerow(header)
            # 写入数据行
            for row in rows:
                writer.writerow(row)

    def export_excel(self, filepath: str, channels: list[int]):
        """
        导出数据为 Excel 文件

        Args:
            filepath: 保存路径
            channels: 要导出的通道列表
        """
        rows = self._merge_channels(channels)
        wb = Workbook()
        ws = wb.active
        ws.title = "温度数据"
        # 写入表头
        header = ["时间戳"]
        for ch in channels:
            header.append(f"CH{ch}温度(°C)")
        ws.append(header)
        # 写入数据行
        for row in rows:
            ws.append(row)
        wb.save(filepath)

    def _merge_channels(self, channels: list[int]) -> list[list]:
        """
        合并多个通道的数据，按时间戳对齐

        Args:
            channels: 通道列表

        Returns:
            合并后的数据行列表，格式为 [时间戳, CH1温度, CH2温度, ...]
        """
        timestamps: set[str] = set()

        # 收集所有通道的数据，按时间戳索引
        channel_data = {}
        for ch in channels:
            self._ensure_channel(ch)
            channel_data[ch] = {}
            for ts, temp in self._data[ch]:
                ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # 精确到毫秒
                channel_data[ch][ts_str] = temp
                timestamps.add(ts_str)

        # 按时间戳排序，生成合并行
        sorted_ts = sorted(timestamps)
        rows = []
        for ts_str in sorted_ts:
            row = [ts_str]
            for ch in channels:
                row.append(channel_data[ch].get(ts_str, ""))  # 缺失数据填空
            rows.append(row)
        return rows

    def clear(self, channel: int = None):
        """
        清空数据

        Args:
            channel: 指定通道号清空，None 表示清空所有通道
        """
        if channel is None:
            self._data.clear()
        elif channel in self._data:
            self._data[channel].clear()

    def record_count(self, channel: int) -> int:
        """获取指定通道的记录数"""
        self._ensure_channel(channel)
        return len(self._data[channel])
