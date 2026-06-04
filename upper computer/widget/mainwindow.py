"""
温度采集系统上位机 - 主窗口模块

功能：
- 1-8路温度采集模式切换
- 串口配置（支持扫描虚拟串口）
- 实时温度表格显示
- pyqtgraph 实时曲线图（合并窗口/独立窗口模式）
- 使用 QStackedWidget 延迟创建页面，优化内存占用
- 按通道独立报警（温度超限变红）
- 数据导出（CSV / Excel）
- 配置持久化（config.json）
- 原始数据日志显示
"""

import json
import os
from collections import deque
from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.alarm import AlarmManager
from core.data_manager import DataManager
from core.serial_worker import SerialWorker, list_available_ports

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

# 常量
# 波特率选项列表，用于串口通信设置
BAUDRATES = ["4800", "9600", "19200", "38400", "57600", "115200"]
# 显示选项字典，键为显示时间范围描述，值为对应的秒数
DISPLAY_OPTIONS = {"1分钟": 60, "5分钟": 300, "10分钟": 600, "30分钟": 1800, "全部": 0}
# 曲线颜色列表，用于图表显示，每个颜色后附有注释说明
CURVE_COLORS = [
    "#00BFFF",  # 蓝色
    "#FF6347",  # 红色
    "#32CD32",  # 绿色
    "#FFD700",  # 金色
    "#9370DB",  # 紫色
    "#FF69B4",  # 粉色
    "#00CED1",  # 青色
    "#FF8C00",  # 橙色
]
# 曲线显示模式字典，键为显示模式描述，值为对应的标识符
CURVE_DISPLAY_MODES = {"合并窗口": "merged", "独立窗口": "separate"}
# 曲线显示的最小高度值，单位为像素
CURVE_MIN_HEIGHT = 200
# 表格列宽设置，单位为像素
TABLE_COL_WIDTH = 80


class MainWindow(QMainWindow):
    """温度采集系统主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("温度采集系统")
        self.resize(1600, 800)

        # 加载配置
        self.config = self._load_config()

        # 初始化核心模块
        self.data_manager = DataManager(max_records=self.config.get("acquisition", {}).get("max_records", 10000))
        self.alarm_manager = AlarmManager()

        # 串口工作线程
        self.serial_worker: SerialWorker | None = None

        # 曲线显示时长
        self._display_seconds = self.config.get("acquisition", {}).get("display_seconds", 300)

        # QStackedWidget 相关
        self._stacked_widget: QStackedWidget = None
        self._loading_page: QWidget = None

        # 页面缓存
        self._created_pages: dict[int, QWidget] = {}
        self._page_plots: dict[int, dict[int, pg.PlotWidget]] = {}
        self._page_curves: dict[int, dict[int, pg.PlotDataItem]] = {}
        self._page_plot_data: dict[int, dict[int, tuple[list, list]]] = {}

        # 当前状态
        self._current_page_index: int = -1
        self._current_channel_count: int = 1
        self._current_curve_mode: str = "merged"

        # 温度表格
        self._temp_table: QTableWidget = None

        # 定时刷新曲线（先初始化为 None，_apply_config 中 _on_interval_changed 需要检查）
        self._update_timer: QTimer | None = None

        # 初始化 UI
        self._setup_ui()
        self._connect_signals()
        self._apply_config()
        self._scan_ports()

        # 定时刷新曲线
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_all_curves)
        interval_ms = self.config.get("acquisition", {}).get("interval_ms", 1000)
        self._update_timer.start(interval_ms)

    # ==================== 配置管理 ====================

    def _load_config(self) -> dict:
        default = {
            "mode": 1,
            "curve_mode": "merged",
            "serial": {"port": "COM11", "baudrate": 9600},
            "channels": {str(i): {"alarm": {"enabled": True, "low_limit": 0, "high_limit": 50}} for i in range(1, 9)},
            "acquisition": {"max_records": 10000, "display_seconds": 300, "interval_ms": 1000},
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                for key in default:
                    if key in saved:
                        if isinstance(default[key], dict):
                            default[key].update(saved[key])
                        else:
                            default[key] = saved[key]
            except Exception:
                pass
        return default

    def _save_config(self):
        self.config["mode"] = self._current_channel_count
        self.config["curve_mode"] = self._current_curve_mode
        self.config["serial"]["port"] = self._port_combo.currentText()
        self.config["serial"]["baudrate"] = int(self._baudrate_combo.currentText())
        for ch in range(1, 9):
            ch_key = str(ch)
            if ch_key not in self.config["channels"]:
                self.config["channels"][ch_key] = {"alarm": {"enabled": True, "low_limit": 0, "high_limit": 50}}
            self.config["channels"][ch_key]["alarm"]["enabled"] = self._alarm_enabled_cbs[ch].isChecked()
            self.config["channels"][ch_key]["alarm"]["low_limit"] = self._alarm_low_spins[ch].value()
            self.config["channels"][ch_key]["alarm"]["high_limit"] = self._alarm_high_spins[ch].value()
        self.config["acquisition"]["display_seconds"] = self._display_seconds
        self.config["acquisition"]["max_records"] = self.data_manager.max_records
        self.config["acquisition"]["interval_ms"] = self._interval_spin.value()
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def _apply_config(self):
        mode = self.config.get("mode", 1)
        curve_mode = self.config.get("curve_mode", "merged")
        if isinstance(mode, str):
            mode = 1
        self._channel_combo.blockSignals(True)
        self._curve_mode_combo.blockSignals(True)
        self._channel_combo.setCurrentIndex(self._channel_combo.findData(mode))
        self._curve_mode_combo.setCurrentIndex(self._curve_mode_combo.findData(curve_mode))
        self._channel_combo.blockSignals(False)
        self._curve_mode_combo.blockSignals(False)
        serial_cfg = self.config.get("serial", {})
        self._port_combo.setCurrentText(serial_cfg.get("port", "COM11"))
        self._baudrate_combo.setCurrentText(str(serial_cfg.get("baudrate", 9600)))
        for ch in range(1, 9):
            alarm_cfg = self.config.get("channels", {}).get(str(ch), {}).get("alarm", {})
            self._alarm_enabled_cbs[ch].setChecked(alarm_cfg.get("enabled", True))
            self._alarm_low_spins[ch].setValue(int(alarm_cfg.get("low_limit", 0)))
            self._alarm_high_spins[ch].setValue(int(alarm_cfg.get("high_limit", 50)))
        self._display_seconds = self.config.get("acquisition", {}).get("display_seconds", 300)
        for text, secs in DISPLAY_OPTIONS.items():
            if secs == self._display_seconds:
                self._display_duration_combo.setCurrentText(text)
                break
        interval_ms = self.config.get("acquisition", {}).get("interval_ms", 1000)
        self._interval_spin.setValue(interval_ms)
        self._switch_mode(mode, curve_mode)

    # ==================== UI 构建 ====================

    def _setup_ui(self):
        self._create_toolbar()
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        self._config_panel = self._create_config_panel()
        main_layout.addWidget(self._config_panel, 1)

        # 中间数据显示区
        self._data_area = QWidget()
        self._data_layout = QVBoxLayout(self._data_area)

        # 温度表格（共享）
        self._temp_table = self._create_temp_table()
        self._data_layout.addWidget(self._temp_table)

        # QStackedWidget
        self._stacked_widget = QStackedWidget()
        self._data_layout.addWidget(self._stacked_widget)

        # 创建加载页面
        self._loading_page = self._create_loading_page()
        self._stacked_widget.addWidget(self._loading_page)
        main_layout.addWidget(self._data_area, 3)

        # 日志面板
        log_panel = self._create_log_panel()
        main_layout.addWidget(log_panel, 1)

        # 状态栏
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪")

    def _create_toolbar(self):
        toolbar = QToolBar("工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self._start_action = QAction("▶ 开始采集", self)
        self._stop_action = QAction("⏹ 停止采集", self)
        self._stop_action.setEnabled(False)
        self._export_csv_action = QAction("导出CSV", self)
        self._export_excel_action = QAction("导出Excel", self)
        self._clear_action = QAction("清空数据", self)
        toolbar.addAction(self._start_action)
        toolbar.addAction(self._stop_action)
        toolbar.addSeparator()
        toolbar.addAction(self._export_csv_action)
        toolbar.addAction(self._export_excel_action)
        toolbar.addSeparator()
        toolbar.addAction(self._clear_action)

    def _create_config_panel(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(280)
        container = QWidget()
        self._config_layout = QVBoxLayout(container)
        self._config_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 模式选择
        mode_group = QGroupBox("模式选择")
        mode_layout = QVBoxLayout(mode_group)
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("通道数:"))
        self._channel_combo = QComboBox()
        for i in range(1, 9):
            self._channel_combo.addItem(f"{i}路", i)
        channel_layout.addWidget(self._channel_combo)
        mode_layout.addLayout(channel_layout)
        curve_layout = QHBoxLayout()
        curve_layout.addWidget(QLabel("曲线显示:"))
        self._curve_mode_combo = QComboBox()
        for text, value in CURVE_DISPLAY_MODES.items():
            self._curve_mode_combo.addItem(text, value)
        curve_layout.addWidget(self._curve_mode_combo)
        mode_layout.addLayout(curve_layout)
        self._config_layout.addWidget(mode_group)

        # 串口设置
        serial_group = QGroupBox("串口设置")
        serial_layout = QVBoxLayout(serial_group)
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("COM:"))
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        port_layout.addWidget(self._port_combo)
        serial_layout.addLayout(port_layout)
        baud_layout = QHBoxLayout()
        baud_layout.addWidget(QLabel("波特率:"))
        self._baudrate_combo = QComboBox()
        for b in BAUDRATES:
            self._baudrate_combo.addItem(b)
        baud_layout.addWidget(self._baudrate_combo)
        serial_layout.addLayout(baud_layout)
        scan_btn = QPushButton("扫描串口")
        scan_btn.clicked.connect(self._scan_ports)
        serial_layout.addWidget(scan_btn)
        self._config_layout.addWidget(serial_group)

        # 报警配置标签页
        self._alarm_tab = QTabWidget()
        self._alarm_enabled_cbs: dict[int, QCheckBox] = {}
        self._alarm_low_spins: dict[int, QSpinBox] = {}
        self._alarm_high_spins: dict[int, QSpinBox] = {}
        for ch in range(1, 9):
            widget = self._create_alarm_config(ch)
            self._alarm_tab.addTab(widget, f"CH{ch}")
        self._config_layout.addWidget(self._alarm_tab)

        # 采集设置
        acq_group = QGroupBox("采集设置")
        acq_layout = QVBoxLayout(acq_group)
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("采集间隔:"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(100, 10000)
        self._interval_spin.setValue(1000)
        self._interval_spin.setSingleStep(100)
        self._interval_spin.setSuffix(" ms")
        interval_layout.addWidget(self._interval_spin)
        acq_layout.addLayout(interval_layout)
        dur_layout = QHBoxLayout()
        dur_layout.addWidget(QLabel("显示时长:"))
        self._display_duration_combo = QComboBox()
        for text in DISPLAY_OPTIONS:
            self._display_duration_combo.addItem(text)
        self._display_duration_combo.setCurrentText("5分钟")
        dur_layout.addWidget(self._display_duration_combo)
        acq_layout.addLayout(dur_layout)
        rec_layout = QHBoxLayout()
        rec_layout.addWidget(QLabel("最大记录数:"))
        self._max_records_spin = QSpinBox()
        self._max_records_spin.setRange(1000, 1000000)
        self._max_records_spin.setValue(self.config.get("acquisition", {}).get("max_records", 10000))
        self._max_records_spin.setSingleStep(1000)
        rec_layout.addWidget(self._max_records_spin)
        acq_layout.addLayout(rec_layout)
        self._config_layout.addWidget(acq_group)
        self._config_layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_alarm_config(self, ch: int) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        alarm_cfg = self.config.get("channels", {}).get(str(ch), {}).get("alarm", {})
        enabled_cb = QCheckBox("启用报警")
        enabled_cb.setChecked(alarm_cfg.get("enabled", True))
        layout.addWidget(enabled_cb)
        self._alarm_enabled_cbs[ch] = enabled_cb
        low_layout = QHBoxLayout()
        low_layout.addWidget(QLabel("下限:"))
        low_spin = QSpinBox()
        low_spin.setRange(-100, 200)
        low_spin.setValue(int(alarm_cfg.get("low_limit", 0)))
        low_layout.addWidget(low_spin)
        low_layout.addWidget(QLabel("°C"))
        layout.addLayout(low_layout)
        self._alarm_low_spins[ch] = low_spin
        high_layout = QHBoxLayout()
        high_layout.addWidget(QLabel("上限:"))
        high_spin = QSpinBox()
        high_spin.setRange(-100, 200)
        high_spin.setValue(int(alarm_cfg.get("high_limit", 50)))
        high_layout.addWidget(high_spin)
        high_layout.addWidget(QLabel("°C"))
        layout.addLayout(high_layout)
        self._alarm_high_spins[ch] = high_spin
        self.alarm_manager.setup_channel(ch, low=low_spin.value(), high=high_spin.value(), enabled=enabled_cb.isChecked())
        layout.addStretch()
        return widget

    def _create_log_panel(self) -> QGroupBox:
        group = QGroupBox("原始数据日志")
        layout = QVBoxLayout(group)
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(1000)
        self._log_text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        self._log_text.setMinimumWidth(250)
        self._log_text.setMaximumWidth(500)
        layout.addWidget(self._log_text)
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self._log_text.clear)
        layout.addWidget(clear_btn)
        return group

    def _create_loading_page(self) -> QWidget:
        """创建加载页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_label = QLabel("正在加载，请稍候...")
        loading_label.setFont(QFont("Microsoft YaHei", 16))
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_label.setStyleSheet("color: #666666;")
        layout.addWidget(loading_label)
        return page

    def _create_temp_table(self) -> QTableWidget:
        """创建温度表格"""
        table = QTableWidget(1, 8)
        table.setHorizontalHeaderLabels([f"CH{i}" for i in range(1, 9)])
        table.verticalHeader().setVisible(False)
        table.setFixedHeight(60)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setDefaultSectionSize(TABLE_COL_WIDTH)
        for col in range(8):
            item = QTableWidgetItem("-- °C")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(0, col, item)
        return table

    # ==================== 页面索引 ====================

    def _get_page_index(self, channel_count: int, curve_mode: str) -> int:
        base = (channel_count - 1) * 2
        if curve_mode == "separate":
            base += 1
        return base

    def _calc_cols(self, num_channels: int) -> int:
        if num_channels <= 2:
            return num_channels
        elif num_channels <= 4:
            return 2
        elif num_channels <= 6:
            return 3
        else:
            return 4

    # ==================== 页面创建 ====================

    def _create_page(self, channel_count: int, curve_mode: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        channels = list(range(1, channel_count + 1))
        plots = {}
        curves = {}
        plot_data = {}

        if curve_mode == "merged":
            # 合并窗口模式：一个图表，多条曲线
            plot_widget = pg.PlotWidget(title="实时温度曲线")
            plot_widget.setLabel("left", "温度", units="°C")
            plot_widget.setLabel("bottom", "时间")
            plot_widget.showGrid(x=True, y=True, alpha=0.3)
            plot_widget.setBackground("#1e1e2e")
            plot_widget.setYRange(0, 100)

            for ch in channels:
                color = CURVE_COLORS[(ch - 1) % len(CURVE_COLORS)]
                pen = pg.mkPen(color=color, width=2)
                curve = plot_widget.plot(pen=pen, name=f"CH{ch}")
                curves[ch] = curve
                plot_data[ch] = ([], [])

            plots[0] = plot_widget
            layout.addWidget(plot_widget)

            # 图例行（居中显示，带线条样式）
            legend_widget = QWidget()
            legend_layout = QHBoxLayout(legend_widget)
            legend_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            legend_layout.setContentsMargins(0, 5, 0, 0)

            for ch in channels:
                color = CURVE_COLORS[(ch - 1) % len(CURVE_COLORS)]
                legend_item = QWidget()
                item_layout = QHBoxLayout(legend_item)
                item_layout.setContentsMargins(5, 0, 5, 0)
                line_label = QLabel("—")
                line_label.setStyleSheet(f"color: {color}; font-size: 24px;font-weight: bold;")
                item_layout.addWidget(line_label)
                name_label = QLabel(f"CH{ch}")
                name_label.setStyleSheet(f"font-size: 12px;")
                item_layout.addWidget(name_label)
                legend_layout.addWidget(legend_item)

            layout.addWidget(legend_widget)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            container = QWidget()
            container_layout = QVBoxLayout(container)
            for ch in channels:
                plot_widget, curve = self._create_curve_widget(ch)
                plot_widget.setMinimumHeight(CURVE_MIN_HEIGHT)
                container_layout.addWidget(plot_widget)
                plots[ch] = plot_widget
                curves[ch] = curve
                plot_data[ch] = ([], [])
            container_layout.addStretch()
            scroll.setWidget(container)
            layout.addWidget(scroll)

        page_index = self._get_page_index(channel_count, curve_mode)
        self._page_plots[page_index] = plots
        self._page_curves[page_index] = curves
        self._page_plot_data[page_index] = plot_data
        return page

    def _create_curve_widget(self, ch: int) -> tuple[pg.PlotWidget, pg.PlotDataItem]:
        plot_widget = pg.PlotWidget(title=f"CH{ch} 实时温度曲线")
        plot_widget.setLabel("left", "温度", units="°C")
        plot_widget.setLabel("bottom", "时间")
        plot_widget.showGrid(x=True, y=True, alpha=0.3)
        plot_widget.setBackground("#1e1e2e")
        color = CURVE_COLORS[(ch - 1) % len(CURVE_COLORS)]
        pen = pg.mkPen(color=color, width=2)
        curve = plot_widget.plot(pen=pen)
        return plot_widget, curve

    def _load_history_to_page(self, page_index: int, channel_count: int):
        if page_index not in self._page_plot_data:
            return
        channels = list(range(1, channel_count + 1))
        for ch in channels:
            history = self.data_manager.get_history(ch, seconds=0)
            if history and ch in self._page_plot_data[page_index]:
                x_data, y_data = self._page_plot_data[page_index][ch]
                if history:
                    base_time = history[0][0].timestamp()
                    for ts, temp in history:
                        x_data.append(ts.timestamp() - base_time)
                        y_data.append(temp)
                    if ch in self._page_curves[page_index]:
                        self._page_curves[page_index][ch].setData(x_data, y_data)

    # ==================== 信号连接 ====================

    def _connect_signals(self):
        """
        连接各种UI控件与对应的处理函数，建立信号与槽的连接关系
        """
        # 连接通道和曲线模式选择框的变更事件
        self._channel_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._curve_mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        # 连接开始和停止采集按钮的触发事件
        self._start_action.triggered.connect(self._start_acquisition)
        self._stop_action.triggered.connect(self._stop_acquisition)
        # 连接导出功能的触发事件
        self._export_csv_action.triggered.connect(self._export_csv)
        self._export_excel_action.triggered.connect(self._export_excel)
        # 连接清除数据按钮的触发事件
        self._clear_action.triggered.connect(self._clear_data)
        # 连接时间间隔和显示时长控件的值变更事件
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        self._display_duration_combo.currentTextChanged.connect(self._on_display_duration_changed)
        # 连接最大记录数控件的值变更事件
        self._max_records_spin.valueChanged.connect(self._on_max_records_changed)
        # 为每个通道(1-8)连接报警相关的控件事件
        for ch in range(1, 9):
            # 连接报警使能复选框的切换事件
            self._alarm_enabled_cbs[ch].toggled.connect(lambda checked, c=ch: self.alarm_manager.set_enabled(c, checked))
            # 连接报警下限值输入框的值变更事件
            self._alarm_low_spins[ch].valueChanged.connect(lambda val, c=ch: self.alarm_manager.set_limits(c, val, self._alarm_high_spins[c].value()))
            # 连接报警上限值输入框的值变更事件
            self._alarm_high_spins[ch].valueChanged.connect(lambda val, c=ch: self.alarm_manager.set_limits(c, self._alarm_low_spins[c].value(), val))
        # 连接报警管理器的报警触发和清除事件
        self.alarm_manager.alarm_triggered.connect(self._on_alarm_triggered)
        self.alarm_manager.alarm_cleared.connect(self._on_alarm_cleared)

    # ==================== 模式切换 ====================

    def _on_mode_changed(self):
        new_channel_count = self._channel_combo.currentData()
        new_curve_mode = self._curve_mode_combo.currentData()
        if new_channel_count == self._current_channel_count and new_curve_mode == self._current_curve_mode:
            return

        need_confirm = False
        confirm_msg = ""
        if self.serial_worker is not None and self.serial_worker.isRunning():
            need_confirm = True
            confirm_msg = "正在采集中，切换模式将停止采集，是否继续？"
        elif self._has_data():
            need_confirm = True
            confirm_msg = '存在历史数据，是否清空曲线数据？\n（选择"是"清空数据并释放旧页面，选择"否"保留数据）'

        clear_data = False
        if need_confirm:
            reply = QMessageBox.question(
                self, "切换模式", confirm_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                self._channel_combo.blockSignals(True)
                self._curve_mode_combo.blockSignals(True)
                self._channel_combo.setCurrentIndex(self._channel_combo.findData(self._current_channel_count))
                self._curve_mode_combo.setCurrentIndex(self._curve_mode_combo.findData(self._current_curve_mode))
                self._channel_combo.blockSignals(False)
                self._curve_mode_combo.blockSignals(False)
                return
            elif reply == QMessageBox.StandardButton.Yes:
                clear_data = True

        self._stop_acquisition()
        old_page_index = self._current_page_index
        if clear_data:
            self.data_manager.clear()
        self._switch_mode(new_channel_count, new_curve_mode)
        if clear_data and old_page_index >= 0:
            self._release_page(old_page_index)

    def _has_data(self) -> bool:
        for ch in range(1, 9):
            if self.data_manager.record_count(ch) > 0:
                return True
        return False

    def _switch_mode(self, channel_count: int, curve_mode: str):
        page_index = self._get_page_index(channel_count, curve_mode)
        if page_index in self._created_pages:
            self._apply_switch(page_index, channel_count, curve_mode)
            return
        self._stacked_widget.setCurrentWidget(self._loading_page)
        QTimer.singleShot(100, lambda: self._create_and_switch_page(page_index, channel_count, curve_mode))

    def _create_and_switch_page(self, page_index: int, channel_count: int, curve_mode: str):
        page = self._create_page(channel_count, curve_mode)
        self._stacked_widget.addWidget(page)
        self._created_pages[page_index] = page
        self._load_history_to_page(page_index, channel_count)
        self._apply_switch(page_index, channel_count, curve_mode)

    def _apply_switch(self, page_index: int, channel_count: int, curve_mode: str):
        page = self._created_pages[page_index]
        self._stacked_widget.setCurrentWidget(page)
        self._current_page_index = page_index
        self._current_channel_count = channel_count
        self._current_curve_mode = curve_mode
        for ch in range(1, 9):
            self._alarm_tab.setTabEnabled(ch - 1, ch <= channel_count)
        self._update_status_bar()

    def _release_page(self, page_index: int):
        if page_index not in self._created_pages:
            return
        page = self._created_pages[page_index]
        self._stacked_widget.removeWidget(page)
        page.deleteLater()
        if page_index in self._page_plots:
            del self._page_plots[page_index]
        if page_index in self._page_curves:
            del self._page_curves[page_index]
        if page_index in self._page_plot_data:
            del self._page_plot_data[page_index]
        if page_index in self._created_pages:
            del self._created_pages[page_index]

    # ==================== 串口扫描 ====================

    def _scan_ports(self):
        ports = list_available_ports()
        current = self._port_combo.currentText()
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)
        elif ports:
            self._port_combo.setCurrentIndex(0)
        else:
            self._port_combo.setCurrentText(current)
        self._port_combo.blockSignals(False)

    # ==================== 采集控制 ====================

    def _start_acquisition(self):
        if self.serial_worker is not None and self.serial_worker.isRunning():
            return
        port = self._port_combo.currentText()
        baudrate = int(self._baudrate_combo.currentText())
        interval_ms = self._interval_spin.value()
        if not port:
            QMessageBox.warning(self, "警告", "未选择串口")
            return
        channels = list(range(1, self._current_channel_count + 1))
        for ch in channels:
            self.alarm_manager.setup_channel(ch, low=self._alarm_low_spins[ch].value(), high=self._alarm_high_spins[ch].value(), enabled=self._alarm_enabled_cbs[ch].isChecked())
        self.serial_worker = SerialWorker(port, baudrate, interval_ms)
        self.serial_worker.temperature_received.connect(self._on_temperature)
        self.serial_worker.raw_data_received.connect(self._on_raw_data)
        self.serial_worker.connection_changed.connect(self._on_connection_changed)
        self.serial_worker.error_occurred.connect(self._on_serial_error)
        self.serial_worker.finished.connect(self._on_worker_finished)
        self.serial_worker.start()
        self._set_panel_enabled(False)
        self._start_action.setEnabled(False)
        self._stop_action.setEnabled(True)
        self._update_status_bar()

    def _stop_acquisition(self):
        if self.serial_worker is not None:
            self.serial_worker.stop()
            self.serial_worker = None
        self._set_panel_enabled(True)
        self._start_action.setEnabled(True)
        self._stop_action.setEnabled(False)
        self._update_status_bar()

    def _on_worker_finished(self):
        self.serial_worker = None
        self._set_panel_enabled(True)
        self._start_action.setEnabled(True)
        self._stop_action.setEnabled(False)
        self._update_status_bar()

    def _set_panel_enabled(self, enabled: bool):
        self._port_combo.setEnabled(enabled)
        self._baudrate_combo.setEnabled(enabled)
        self._channel_combo.setEnabled(enabled)
        self._curve_mode_combo.setEnabled(enabled)
        for ch in range(1, 9):
            self._alarm_enabled_cbs[ch].setEnabled(enabled)
            self._alarm_low_spins[ch].setEnabled(enabled)
            self._alarm_high_spins[ch].setEnabled(enabled)
        self._interval_spin.setEnabled(enabled)
        self._max_records_spin.setEnabled(enabled)

    # ==================== 数据处理 ====================

    def _on_raw_data(self, hex_str: str, result: list[tuple[int, float]]):
        """
        显示原始数据到日志面板

        Args:
            hex_str: 原始数据十六进制字符串
            result: 解析结果 [(通道号, 温度值), ...]
        """
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        channel_count = len(result)
        channel_info = " ".join([f"CH{ch}：{temp:.1f}°C" for ch, temp in result])
        # log_msg = f"[{timestamp}] {channel_count}通道 {channel_info} -> {hex_str}"
        log_msg = f"[{timestamp}] {channel_count}通道 {channel_info}"
        self._log_text.appendPlainText(log_msg)
        self._log_text.verticalScrollBar().setValue(self._log_text.verticalScrollBar().maximum())

    def _on_temperature(self, ch: int, temp: float):
        col = ch - 1
        if self._temp_table and col < self._temp_table.columnCount():
            item = QTableWidgetItem(f"{temp:.1f} °C")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if self.alarm_manager.get_state(ch) != "NORMAL":
                item.setForeground(QColor("red"))
            self._temp_table.setItem(0, col, item)
        now = datetime.now()
        self.data_manager.add_record(ch, temp, now)
        page_index = self._current_page_index
        if page_index in self._page_plot_data:
            if ch in self._page_plot_data[page_index]:
                x_data, y_data = self._page_plot_data[page_index][ch]
                x_data.append(now.timestamp())
                y_data.append(temp)
        self.alarm_manager.check(ch, temp)

    def _update_all_curves(self):
        page_index = self._current_page_index
        if page_index in self._page_curves:
            max_temp = float('-inf')
            min_temp = float('inf')

            for ch, curve in self._page_curves[page_index].items():
                if ch in self._page_plot_data[page_index]:
                    x_data, y_data = self._page_plot_data[page_index][ch]
                    if x_data:
                        if self._display_seconds > 0:
                            cutoff = datetime.now().timestamp() - self._display_seconds
                            while x_data and x_data[0] < cutoff:
                                x_data.pop(0)
                                y_data.pop(0)
                        if x_data:
                            base = x_data[0]
                            rel_x = [x - base for x in x_data]
                            curve.setData(rel_x, y_data)
                            if y_data:
                                max_temp = max(max_temp, max(y_data))
                                min_temp = min(min_temp, min(y_data))

            # 合并窗口模式：智能调整Y轴
            if self._current_curve_mode == "merged":
                if 0 in self._page_plots[page_index]:
                    plot_widget = self._page_plots[page_index][0]
                    y_range = plot_widget.viewRange()[1]
                    y_min, y_max = y_range

                    need_update = False
                    new_y_min = y_min
                    new_y_max = y_max

                    if max_temp > y_max:
                        new_y_max = max_temp * 1.2
                        need_update = True

                    if min_temp < y_min:
                        new_y_min = min_temp * 1.2 if min_temp < 0 else 0
                        need_update = True

                    if need_update:
                        plot_widget.setYRange(new_y_min, new_y_max)

    # ==================== 连接状态 ====================

    def _on_connection_changed(self, connected: bool):
        self._update_status_bar()

    def _on_serial_error(self, error: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_text.appendHtml(
            f'<span style="background-color: #FF0000; color: white;">[{timestamp}] 错误: {error}</span>'
        )
        self._log_text.verticalScrollBar().setValue(self._log_text.verticalScrollBar().maximum())

    # ==================== 报警处理 ====================

    def _on_alarm_triggered(self, ch: int, alarm_type: str, temp: float):
        col = ch - 1
        if self._temp_table and col < self._temp_table.columnCount():
            item = self._temp_table.item(0, col)
            if item:
                item.setForeground(QColor("red"))
        self._update_status_bar()

    def _on_alarm_cleared(self, ch: int, alarm_type: str):
        col = ch - 1
        if self._temp_table and col < self._temp_table.columnCount():
            item = self._temp_table.item(0, col)
            if item:
                item.setForeground(QColor("black"))
        self._update_status_bar()

    # ==================== 状态栏 ====================

    def _update_status_bar(self):
        port = self._port_combo.currentText()
        channels = list(range(1, self._current_channel_count + 1))
        parts = []
        if self.serial_worker is not None and self.serial_worker.isRunning():
            parts.append(f"{port} 已连接")
        else:
            parts.append(f"{port} 未连接")
        for ch in channels:
            state = self.alarm_manager.get_state(ch)
            parts.append(f"CH{ch}: {state}")
        self._status_bar.showMessage(" | ".join(parts))

    # ==================== 采集设置 ====================

    def _on_interval_changed(self, value: int):
        if self._update_timer is not None and self._update_timer.isActive():
            self._update_timer.start(value)

    def _on_display_duration_changed(self, text: str):
        self._display_seconds = DISPLAY_OPTIONS.get(text, 300)

    def _on_max_records_changed(self, value: int):
        self.data_manager.max_records = value
        for ch in self.data_manager._data:
            self.data_manager._data[ch] = deque(self.data_manager._data[ch], maxlen=value)

    # ==================== 数据导出 ====================

    def _export_csv(self):
        channels = self._get_export_channels()
        if not channels:
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "导出CSV", f"temperature_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "CSV文件 (*.csv)")
        if filepath:
            try:
                self.data_manager.export_csv(filepath, channels)
                QMessageBox.information(self, "导出成功", f"数据已导出到:\n{filepath}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _export_excel(self):
        channels = self._get_export_channels()
        if not channels:
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "导出Excel", f"temperature_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", "Excel文件 (*.xlsx)")
        if filepath:
            try:
                self.data_manager.export_excel(filepath, channels)
                QMessageBox.information(self, "导出成功", f"数据已导出到:\n{filepath}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _get_export_channels(self) -> list[int]:
        channels = list(range(1, self._current_channel_count + 1))
        has_data = [ch for ch in channels if self.data_manager.record_count(ch) > 0]
        if not has_data:
            QMessageBox.information(self, "提示", "没有数据可导出")
            return []
        if len(has_data) == 1:
            return has_data
        items = [f"CH{ch} ({self.data_manager.record_count(ch)}条)" for ch in has_data]
        selected, ok = QInputDialog.getItem(self, "选择导出通道", "导出通道:", items, 0, False)
        if ok and selected:
            ch = int(selected.split("CH")[1].split(" ")[0])
            return [ch]
        return []

    # ==================== 数据清空 ====================

    def _clear_data(self):
        reply = QMessageBox.question(self, "清空数据", "确定要清空所有数据吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # 1. 清空底层数据
            self.data_manager.clear()
            
            # 2. 清空当前页面的画布数据并刷新曲线
            page_index = self._current_page_index
            if page_index in self._page_plot_data:
                # 遍历当前页面的所有通道
                for ch, (x_data, y_data) in self._page_plot_data[page_index].items():
                    x_data.clear()  # 清空 x 轴缓存数据
                    y_data.clear()  # 清空 y 轴缓存数据
                    
                    # 清空画布上对应的曲线
                    if page_index in self._page_curves and ch in self._page_curves[page_index]:
                        self._page_curves[page_index][ch].setData([], [])
                        
            # 3. 重置温度表格显示
            if self._temp_table:
                for col in range(self._temp_table.columnCount()):
                    item = self._temp_table.item(0, col)
                    if item:
                        item.setText("-- °C")
                        item.setForeground(QColor("black")) # 同时恢复字体颜色为黑色（取消报警红色）


    # ==================== 窗口事件 ====================

    def closeEvent(self, event):
        self._stop_acquisition()
        self._save_config()
        event.accept()
