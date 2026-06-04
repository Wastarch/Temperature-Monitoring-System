"""
温度采集系统上位机 - 程序入口

启动 PySide6 应用程序并显示主窗口。
"""

import sys

from PySide6.QtWidgets import QApplication
from widget.mainwindow import MainWindow


if __name__ == "__main__":
    # 创建应用程序实例
    app = QApplication(sys.argv)

    # 创建并显示主窗口
    window = MainWindow()
    window.show()

    # 进入事件循环
    sys.exit(app.exec())
