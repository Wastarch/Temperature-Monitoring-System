import random
import struct
import time

import serial

# 串口通信相关配置参数
PORT = "COM10"        # 串口号，设置为COM10
BAUD = 9600          # 波特率，设置为9600 bps
INTERVAL = 0.1      # 数据采集间隔时间，单位为秒
CHANNEL_COUNT = 8 # 通道数量，生成 CH1~CHN 的数据


def build_frame(channel_temps: list[tuple[int, float]]) -> bytes:
    """
    构建多通道温度数据的二进制通信帧。
    
    :param channel_temps: 列表，包含元组(通道号, 温度值)。例如: [(1, 25.5), (2, -10.2)]
    :return: 组装好的字节流数据帧
    """
    # 获取通道数量，将作为数据帧中的“数据长度”字段
    n = len(channel_temps)
    
    # 初始化异或(XOR)校验值，将长度 n 作为校验的初始值参与后续异或运算
    xor = n
    
    # 用于暂存打包后的数据字节（通道号 + 温度高字节 + 温度低字节）
    data = []
    
    for ch, temp in channel_temps:
        # 将浮点数温度放大10倍并转为整数，保留1位小数精度。
        # 例如: 25.5 -> 255, -10.2 -> -102
        code = int(temp * 10)
        
        # 使用 struct 将整数 code 打包为 2 字节的有符号短整型 (">h")
        # ">": 大端序(网络字节序)，高字节在前，低字节在后
        # "h": 有符号 16 位整数 (范围 -32768 ~ 32767)
        # 返回的是 bytes 对象，这里将其解包赋值给 data_h (高字节) 和 data_l (低字节)
        data_h, data_l = struct.pack(">h", code)
        
        # 将当前通道的通道号、高字节、低字节依次进行异或运算，更新校验值 xor
        xor ^= ch ^ data_h ^ data_l
        
        # 将当前通道的数据追加到 data 列表中
        data.extend([ch, data_h, data_l])
        
    # 组装完整的数据帧并转换为 bytes 对象返回
    # 帧结构: [帧头 0xAA] + [数据长度 n] + [数据体 data] + [校验位 xor] + [帧尾 0x0A]
    return bytes([0xAA, n] + data + [xor, 0x0A])



def random_temp() -> float:
    """
    生成一个随机的温度值。
    
    温度范围设定为 -10.0 到 50.0 摄氏度，并保留 1 位小数精度。
    这通常用于模拟常规环境温度传感器的数据。
    
    :return: 随机生成的浮点数温度值
    """
    # random.uniform(a, b): 生成一个在 [a, b] 范围内的随机浮点数
    # round(x, 1): 将生成的随机浮点数四舍五入保留 1 位小数
    return round(random.uniform(-10.0, 50.0), 1)


def main():
    # 初始化并打开串口
    # port: 串口设备路径 (如 Windows 的 'COM3' 或 Linux 的 '/dev/ttyUSB0')
    # baudrate: 波特率，通信双方必须一致
    # bytesize: 数据位，通常为8位
    # parity: 校验位，"N" 表示无校验
    # stopbits: 停止位，1表示1个停止位

    ser = serial.Serial(port=PORT, baudrate=BAUD, bytesize=8, parity="N", stopbits=1)
    print(f"已打开串口 {ser.name}，波特率 {BAUD}，按 Ctrl+C 停止发送")

    try:
        # 无限循环，持续发送数据
        while True:
            # 生成温度数据列表：
            # 遍历通道号 (从 1 到 CHANNEL_COUNT)
            # 使用之前定义的 random_temp() 函数为每个通道生成随机温度
            channel_temps = [(ch, random_temp()) for ch in range(1, CHANNEL_COUNT + 1)]
            
            # 调用之前定义的 build_frame() 函数，将温度数据打包成二进制数据帧
            frame = build_frame(channel_temps)
            
            # 将打包好的数据帧通过串口发送出去
            ser.write(frame)
            
            # 构建用于控制台打印的详细信息字符串
            # 使用生成器表达式将每个通道的数据格式化为 "CH1：25.5°C" 的形式，并用空格连接
            detail = " ".join(f"CH{ch}：{t}°C" for ch, t in channel_temps)
            
            # 打印发送日志
            # frame.hex(' ') 将 bytes 转为十六进制字符串，并用空格分隔 (如 "AA 03 01 00 FF ...")
            # .upper() 将十六进制字母转为大写
            print(f"[发送] {len(channel_temps)}通道 {detail} -> {frame.hex(' ').upper()}")
            
            # 线程休眠，控制发送频率 (INTERVAL 为发送间隔时间，单位秒)
            time.sleep(INTERVAL)
            
    except KeyboardInterrupt:
        # 捕获键盘中断异常 (用户按下 Ctrl+C)
        print("\n已停止发送")
        
    finally:
        # 无论程序是正常结束还是异常结束，最终都会执行此处
        # 确保串口资源被正确释放，避免端口被占用
        ser.close()
        print(f"已关闭串口 {ser.name}")

if __name__ == "__main__":
    main()
