"""
温度报警管理模块

功能：
- 按通道独立配置报警阈值（上限/下限）
- 检测温度是否超限，触发/清除报警信号
- 支持启用/禁用报警
"""

from PySide6.QtCore import QObject, Signal


class AlarmManager(QObject):
    """温度报警管理器，支持多通道独立报警"""

    # 报警触发信号：(通道号, 报警类型 "HIGH"/"LOW", 当前温度)
    alarm_triggered = Signal(int, str, float)
    # 报警清除信号：(通道号, 报警类型 "HIGH"/"LOW")
    alarm_cleared = Signal(int, str)

    def __init__(self):
        super().__init__()
        # 每通道的报警配置: {channel: {"low": float, "high": float, "enabled": bool}}
        self._config: dict[int, dict] = {}
        # 每通道的当前报警状态: {channel: {"HIGH", "LOW"}}
        self._state: dict[int, set[str]] = {}

    def setup_channel(self, channel: int, low: float = 0, high: float = 50, enabled: bool = True):
        """
        配置指定通道的报警参数

        Args:
            channel: 通道号
            low: 温度下限（°C）
            high: 温度上限（°C）
            enabled: 是否启用报警
        """
        self._config[channel] = {
            "low": low,
            "high": high,
            "enabled": enabled,
        }
        self._state[channel] = set()

    def check(self, channel: int, temp: float):
        """
        检查温度是否超限

        Args:
            channel: 通道号
            temp: 当前温度值
        """
        if channel not in self._config:
            return
        cfg = self._config[channel]
        if not cfg["enabled"]:
            return

        prev = self._state.get(channel, set())  # 之前的报警状态
        curr: set[str] = set()  # 当前应有状态

        # 判断是否超限
        if temp > cfg["high"]:
            curr.add("HIGH")
        if temp < cfg["low"]:
            curr.add("LOW")

        # 新触发的报警
        for alarm_type in curr - prev:
            self.alarm_triggered.emit(channel, alarm_type, temp)
        # 已清除的报警
        for alarm_type in prev - curr:
            self.alarm_cleared.emit(channel, alarm_type)

        self._state[channel] = curr

    def set_limits(self, channel: int, low: float, high: float):
        """更新指定通道的报警阈值"""
        if channel in self._config:
            self._config[channel]["low"] = low
            self._config[channel]["high"] = high

    def set_enabled(self, channel: int, enabled: bool):
        """启用/禁用指定通道的报警"""
        if channel in self._config:
            self._config[channel]["enabled"] = enabled
            if not enabled:
                self._state[channel] = set()  # 禁用时清空报警状态

    def get_state(self, channel: int) -> str:
        """
        获取指定通道的当前报警状态

        Returns:
            "NORMAL" / "HIGH" / "LOW"
        """
        state = self._state.get(channel, set())
        if "HIGH" in state:
            return "HIGH"
        if "LOW" in state:
            return "LOW"
        return "NORMAL"
