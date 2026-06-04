# 多通道温度监控系统

基于 Python 的多通道温度监控系统，包含上位机和下位机（模拟器），支持串口通信、实时数据可视化、报警和数据导出。

## 项目结构

```
Temperature-Monitoring-System/
├── upper computer/          # 上位机（PySide6 GUI）
│   ├── main.py              # 程序入口
│   ├── config.json          # 配置文件（运行时自动生成）
│   ├── pyproject.toml       # 项目依赖配置
│   ├── core/                # 核心功能模块
│   │   ├── alarm.py         # 报警管理器
│   │   ├── data_manager.py  # 数据管理器
│   │   └── serial_worker.py # 串口通信工作线程
│   └── widget/              # 界面模块
│       └── mainwindow.py    # 主窗口界面
└── lower computer/          # 下位机模拟器
    ├── main.py              # 温度数据发送程序
    ├── PROTOCOL.md          # 通信协议文档
    └── pyproject.toml       # 项目依赖配置
```

## 功能特性

### 上位机

- 支持 1-8 路温度采集模式切换
- 串口自动扫描（支持物理串口和虚拟串口）
- 实时温度表格显示
- pyqtgraph 实时曲线图（合并窗口/独立窗口模式）
- 温度超限报警（可配置上下限）
- 数据导出（CSV/Excel 格式）
- 配置持久化（JSON 格式）
- 原始数据日志显示
- 采集间隔可配置（100ms ~ 10s）

### 下位机模拟器

- 模拟 8 通道温度传感器
- 按自定义二进制协议发送数据
- 温度范围 -10.0°C ~ 50.0°C
- XOR 校验保证数据完整性

## 快速开始

### 环境要求

- Python 3.13 或更高版本
- 操作系统：Windows 10/11

### 安装依赖

推荐使用 [uv](https://github.com/astral-sh/uv) 包管理器：

**上位机：**

```bash
cd "upper computer"
uv sync
```

**下位机模拟器：**

```bash
cd "lower computer"
uv sync
```

### 运行

**1. 启动下位机模拟器（模拟温度数据）：**

```bash
cd "lower computer"
uv run main.py
```

**2. 启动上位机：**

```bash
cd "upper computer"
uv run main.py
```

> 注意：运行前需使用虚拟串口软件（如 VSPD、com0com）创建串口对，将下位机发送端和上位机接收端连接到同一对串口。

## 通信协议

### 串口配置

| 参数 | 值 |
|------|-----|
| 波特率 | 9600 |
| 数据位 | 8 |
| 校验位 | None |
| 停止位 | 1 |

### 数据帧格式

帧长度可变，结构如下：

```
┌──────┬────┬─────────────────────────┬──────┬──────┐
│ 0xAA │ N  │ CH1 DATA ... CHn DATA   │ XOR  │ 0x0A │
│ 起始  │ 通道数 │ N组通道数据(每组3字节) │ 校验 │ 结束 │
└──────┴────┴─────────────────────────┴──────┴──────┘
  Byte0  Byte1  Byte2 ~ Byte(N×3+1)   Byte(N×3+2)  Byte(N×3+3)
```

帧总长度 = N × 3 + 4 字节

### 温度编码

- 类型：16 位有符号整数（Big-Endian）
- 分辨率：0.1°C
- 编码公式：`编码值 = 温度值 × 10`

| 温度值 | 编码值 | Data_H | Data_L |
|--------|--------|--------|--------|
| 25.5°C | 255 | 0x00 | 0xFF |
| -3.1°C | -31 | 0xFF | 0xE1 |
| 100.0°C | 1000 | 0x03 | 0xE8 |

### 校验计算

```
XOR = N ^ CH1 ^ Data_H1 ^ Data_L1 ^ CH2 ^ Data_H2 ^ Data_L2 ^ ... ^ CHn ^ Data_Hn ^ Data_Ln
```

### 示例帧

```
单通道 (CH1 25.5°C):     AA 01 01 00 FF FF 0A
双通道 (CH1 -3.1°C, CH2 26.3°C): AA 02 01 FF E1 02 01 07 19 0A
```

详细协议文档见 [PROTOCOL.md](lower%20computer/PROTOCOL.md)

## 配置说明

上位机配置文件 `config.json`（运行时自动生成）：

```json
{
    "mode": "single",
    "serial": {
        "port": "COM10",
        "baudrate": 9600
    },
    "channels": {
        "1": {"alarm": {"enabled": true, "low_limit": 0, "high_limit": 50}},
        "2": {"alarm": {"enabled": true, "low_limit": 0, "high_limit": 50}}
    },
    "acquisition": {"max_records": 10000, "display_seconds": 300, "interval": 100}
}
```

| 参数 | 说明 |
|------|------|
| mode | 采集模式（single/dual） |
| serial.port | 串口号 |
| serial.baudrate | 波特率 |
| channels.X.alarm.enabled | 是否启用报警 |
| channels.X.alarm.low_limit | 温度下限（°C） |
| channels.X.alarm.high_limit | 温度上限（°C） |
| acquisition.max_records | 最大记录数 |
| acquisition.display_seconds | 曲线显示时间范围（秒） |
| acquisition.interval | 采集间隔（毫秒） |

## 依赖项

### 上位机

- PySide6 >= 6.11.1
- pyserial >= 3.5
- pyqtgraph >= 0.13
- openpyxl >= 3.1

### 下位机

- pyserial >= 3.5

## 许可证

MIT License
