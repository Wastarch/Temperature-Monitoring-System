# 虚拟串口温度数据发送器 - 上位机开发文档

## 1. 串口配置

| 参数   | 值   |
| ------ | ---- |
| 波特率 | 9600 |
| 数据位 | 8    |
| 校验位 | None |
| 停止位 | 1    |

## 2. 数据帧格式

帧长度可变，结构如下：

```
┌──────┬────┬─────────────────────────┬──────┬──────┐
│ 0xAA │ N  │ CH1 DATA ... CHn DATA   │ XOR  │ 0x0A │
│ 起始  │ 通道数 │ N组通道数据(每组3字节) │ 校验 │ 结束 │
└──────┴────┴─────────────────────────┴──────┴──────┘
 Byte0  Byte1  Byte2 ~ Byte(N×3+1)   Byte(N×3+2)  Byte(N×3+3)
```

帧总长度 = N × 3 + 4 字节

## 3. 字段说明

| 字段     | 字节位置      | 值范围    | 说明               |
| -------- | ------------- | --------- | ------------------ |
| 起始位   | Byte 0        | 0xAA      | 固定值             |
| 通道数 N | Byte 1        | 0x01~0x08 | 本帧包含的通道数量 |
| CH       | Byte (2 + 3i) | 0x01~0x08 | 通道号             |
| Data_H   | Byte (3 + 3i) | 0x00~0xFF | 温度高字节         |
| Data_L   | Byte (4 + 3i) | 0x00~0xFF | 温度低字节         |
| XOR      | Byte (N×3+2)  | 0x00~0xFF | 校验字节           |
| 结束位   | Byte (N×3+3)  | 0x0A      | 固定值             |

其中 i = 0, 1, ..., N-1

## 4. 温度编码

- 类型：16 位有符号整数（Big-Endian）
- 分辨率：0.1°C
- 编码公式：`编码值 = 温度值 × 10`

| 温度值  | 编码值 | Data_H | Data_L |
| ------- | ------ | ------ | ------ |
| 25.5°C  | 255    | 0x00   | 0xFF   |
| -3.1°C  | -31    | 0xFF   | 0xE1   |
| 100.0°C | 1000   | 0x03   | 0xE8   |
| 0.0°C   | 0      | 0x00   | 0x00   |
| -10.5°C | -105   | 0xFF   | 0x97   |

负数采用补码表示：-31 的 16 位补码 = 0xFFE1 → 高字节 0xFF，低字节 0xE1

## 5. 校验计算

```
XOR = N ^ CH1 ^ Data_H1 ^ Data_L1 ^ CH2 ^ Data_H2 ^ Data_L2 ^ ... ^ CHn ^ Data_Hn ^ Data_Ln
```

校验范围：通道数字段 + 所有通道数据字段的逐字节异或

## 6. 示例帧

### 6.1 单通道帧 (N=1)

温度：CH1 25.5°C

```
AA 01 01 00 FF FF 0A
│  │  │  └──┘  │  │
│  │  │ 25.5°C │  │
│  │  CH1      │  结束
│  N=1         XOR
起始
```

校验：XOR = 1 ^ 1 ^ 0x00 ^ 0xFF = 0xFF

### 6.2 双通道帧 (N=2)

温度：CH1 -3.1°C，CH2 26.3°C

```
AA 02 01 FF E1 02 01 07 19 0A
│  │  │  └──┘  │  └──┘  │  │
│  │  │ -3.1°C │ 26.3°C │  │
│  │  CH1      CH2       │  结束
│  N=2                    XOR
起始
```

校验：XOR = 2 ^ 1 ^ 0xFF ^ 0xE1 ^ 2 ^ 1 ^ 0x07 = 0x19

### 6.3 三通道帧 (N=3)

温度：CH1 30.1°C，CH2 47.0°C，CH3 25.5°C

```
AA 03 01 01 2D 02 01 D6 03 00 FF 07 0A
│  │  │  └──┘  │  └──┘  │  └──┘  │  │
│  │  │ 30.1°C │ 47.0°C │ 25.5°C │  │
│  │  CH1      CH2       CH3      │  结束
│  N=3                             XOR
起始
```

校验：XOR = 3 ^ 1^0x01^0x2D ^ 2^0x01^0xD6 ^ 3^0x00^0xFF = 0x07

## 7. 上位机解析流程

```
1. 读取一个字节
2. 判断是否为 0xAA（起始位）
   ├─ 否 → 丢弃，回到步骤 1
   └─ 是 → 继续
3. 读取一个字节 → 通道数 N
4. 校验 N 范围 (1~8)，非法则丢弃本帧
5. 读取 N×3 字节 → 通道数据
6. 读取一个字节 → XOR 校验值
7. 计算校验：expected_XOR = N ^ 所有通道数据字节的异或
8. 比较计算值与接收的 XOR
   ├─ 不一致 → 校验失败，丢弃本帧
   └─ 一致 → 继续
9. 读取一个字节 → 判断是否为 0x0A（结束位）
   ├─ 不是 → 帧格式错误，丢弃
   └─ 是 → 帧有效，解析数据
10. 遍历 N 组通道数据：
    CH  = data[i*3]
    Data_H = data[i*3 + 1]
    Data_L = data[i*3 + 2]
    code = (Data_H << 8) | Data_L  （有符号 16 位）
    温度 = code / 10.0
```

## 8. Python 解析示例

```python
import struct

def parse_frame(frame: bytes) -> list[tuple[int, float]] | None:
    if len(frame) < 6:
        return None
    if frame[0] != 0xAA or frame[-1] != 0x0A:
        return None

    n = frame[1]
    if n < 1 or n > 8 or len(frame) != n * 3 + 4:
        return None

    data = frame[2:2 + n * 3]
    xor_recv = frame[2 + n * 3]

    xor_calc = n
    for b in data:
        xor_calc ^= b
    if xor_calc != xor_recv:
        return None

    result = []
    for i in range(n):
        ch = data[i * 3]
        code = struct.unpack(">h", data[i * 3 + 1:i * 3 + 3])[0]
        temp = code / 10.0
        result.append((ch, temp))
    return result
```

## 9. C# 解析示例

```csharp
public static List<(int channel, double temp)>? ParseFrame(byte[] frame)
{
    if (frame.Length < 6) return null;
    if (frame[0] != 0xAA || frame[^1] != 0x0A) return null;

    int n = frame[1];
    if (n < 1 || n > 8 || frame.Length != n * 3 + 4) return null;

    byte xorCalc = (byte)n;
    for (int i = 2; i < 2 + n * 3; i++)
        xorCalc ^= frame[i];

    if (xorCalc != frame[2 + n * 3]) return null;

    var result = new List<(int, double)>();
    for (int i = 0; i < n; i++)
    {
        int ch = frame[2 + i * 3];
        short code = (short)((frame[3 + i * 3] << 8) | frame[4 + i * 3]);
        double temp = code / 10.0;
        result.Add((ch, temp));
    }
    return result;
}
```
