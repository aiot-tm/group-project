import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.animation as animation
import threading
import paho.mqtt.client as mqtt
import numpy as np
import time
import queue
import json

# 导入你的运动检测器
from motion_detector import MotionDetector


class CSIVisualizationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CSI Motion Detection Visualization System")
        self.root.geometry("1600x900")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 配置
        self.config = self.load_config('config.json')

        # 创建运动检测器
        self.detector = MotionDetector(self.config.get('motion_detector', {}))

        # 创建数据队列和标志
        self.csi_data_queue = queue.Queue(maxsize=100)
        self.running = True
        self.motion_detected = False
        self.detection_history = []  # 检测历史
        self.display_buffer_size = 50  # 可视化缓冲区大小
        self.detection_buffer = []  # 检测结果缓冲
        self.variance_history = []  # 方差历史
        self.threshold_history = []  # 阈值历史
        self.last_message_id = None  # 最新消息ID

        # 创建UI
        self.create_ui()

        # 启动MQTT客户端
        self.start_mqtt_client()

        # 启动处理线程
        self.start_processing_thread()

    def load_config(self, config_path='config.json'):
        """Load configuration file"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config file: {e}")
            return {}

    def create_ui(self):
        """Create user interface"""
        # 创建主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 创建标题
        title_label = ttk.Label(main_frame, text="Real-time CSI Motion Detection System", font=("Arial", 18, "bold"))
        title_label.pack(pady=10)

        # 创建内容框架
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # 创建左侧面板 - 数据可视化
        viz_frame = ttk.LabelFrame(content_frame, text="CSI Data Visualization")
        viz_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 创建右侧面板 - 检测结果和控制
        control_frame = ttk.LabelFrame(content_frame, text="Detection Control")
        control_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=5, pady=5, ipadx=10, ipady=5)
        control_frame.pack_propagate(False)  # 不让控件根据内容调整大小
        control_frame.configure(width=300)  # 设置固定宽度

        # 在左侧面板中创建图形区域
        self.create_plots(viz_frame)

        # 在右侧面板中创建控制区域
        self.create_controls(control_frame)

    def create_plots(self, parent):
        """Create visualization plots"""
        # 创建图形
        self.fig = plt.figure(figsize=(10, 8), dpi=100)

        # CSI振幅图形
        self.ax1 = self.fig.add_subplot(311)  # 3行1列的第1个
        self.ax1.set_title("CSI Amplitude")
        self.ax1.set_ylabel("Amplitude")
        self.ax1.grid(True)
        self.amplitude_lines = []

        # 方差和阈值图形
        self.ax2 = self.fig.add_subplot(312)  # 3行1列的第2个
        self.ax2.set_title("Amplitude Variance & Threshold")
        self.ax2.set_ylabel("Variance")
        self.ax2.grid(True)
        self.variance_line, = self.ax2.plot([], [], 'b-', label='Amplitude Variance')
        self.threshold_line, = self.ax2.plot([], [], 'r--', label='Detection Threshold')
        self.ax2.legend()

        # 检测结果图形
        self.ax3 = self.fig.add_subplot(313)  # 3行1列的第3个
        self.ax3.set_title("Motion Detection Result")
        self.ax3.set_ylabel("State")
        self.ax3.set_ylim(-0.1, 1.1)
        self.ax3.set_yticks([0, 1])
        self.ax3.set_yticklabels(['Static', 'Moving'])
        self.ax3.grid(True)
        self.detection_line, = self.ax3.plot([], [], 'g-', lw=2)

        # 调整子图之间的间距
        self.fig.tight_layout()

        # 添加画布到界面
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 设置动画
        self.ani = animation.FuncAnimation(
            self.fig, self.update_plots, interval=100,
            blit=False, cache_frame_data=False)

    def create_controls(self, parent):
        """Create control panel"""
        # 状态指示器
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=10)

        ttk.Label(status_frame, text="Current Status:").pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(status_frame, text="Waiting for data...", font=("Arial", 12, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=5)

        # 状态指示灯
        self.status_indicator = tk.Canvas(status_frame, width=20, height=20, bg=self.root.cget('bg'),
                                          highlightthickness=0)
        self.status_indicator.pack(side=tk.RIGHT, padx=5)
        self.status_light = self.status_indicator.create_oval(2, 2, 18, 18, fill="gray", outline="black")

        # 消息ID框架
        msg_frame = ttk.Frame(parent)
        msg_frame.pack(fill=tk.X, pady=5)

        ttk.Label(msg_frame, text="Latest Message ID:").pack(side=tk.LEFT, padx=5)
        self.msg_id_label = ttk.Label(msg_frame, text="None")
        self.msg_id_label.pack(side=tk.LEFT, padx=5)

        # MQTT连接状态
        mqtt_frame = ttk.Frame(parent)
        mqtt_frame.pack(fill=tk.X, pady=5)

        ttk.Label(mqtt_frame, text="MQTT Connection:").pack(side=tk.LEFT, padx=5)
        self.mqtt_status = ttk.Label(mqtt_frame, text="Disconnected", foreground="red")
        self.mqtt_status.pack(side=tk.LEFT, padx=5)

        # 数据接收率
        rate_frame = ttk.Frame(parent)
        rate_frame.pack(fill=tk.X, pady=5)

        ttk.Label(rate_frame, text="Data Rate:").pack(side=tk.LEFT, padx=5)
        self.rate_label = ttk.Label(rate_frame, text="0 msgs/s")
        self.rate_label.pack(side=tk.LEFT, padx=5)

        # 检测参数
        param_frame = ttk.LabelFrame(parent, text="Detection Parameters")
        param_frame.pack(fill=tk.X, pady=10, padx=5)

        ttk.Label(param_frame, text="Threshold:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.threshold_var = tk.StringVar(value=str(self.detector.threshold))
        threshold_entry = ttk.Entry(param_frame, textvariable=self.threshold_var, width=10)
        threshold_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Button(param_frame, text="Apply", command=self.apply_threshold).grid(row=0, column=2, padx=5, pady=3)

        # 分割线
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # 检测统计
        stats_frame = ttk.LabelFrame(parent, text="Detection Statistics")
        stats_frame.pack(fill=tk.X, pady=5, padx=5)

        ttk.Label(stats_frame, text="Total Detections:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.total_count_label = ttk.Label(stats_frame, text="0")
        self.total_count_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(stats_frame, text="Motion Detections:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        self.motion_count_label = ttk.Label(stats_frame, text="0")
        self.motion_count_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(stats_frame, text="Static Detections:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        self.static_count_label = ttk.Label(stats_frame, text="0")
        self.static_count_label.grid(row=2, column=1, sticky=tk.W, padx=5, pady=3)

        # 最新数据信息
        data_frame = ttk.LabelFrame(parent, text="Latest Data Info")
        data_frame.pack(fill=tk.X, pady=5, padx=5)

        ttk.Label(data_frame, text="Amplitude Variance:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.variance_label = ttk.Label(data_frame, text="0.0")
        self.variance_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=3)

        ttk.Label(data_frame, text="Current Threshold:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        self.current_threshold_label = ttk.Label(data_frame, text="0.0")
        self.current_threshold_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=3)

        # 在现有data_frame后添加
        ttk.Label(data_frame, text="Subcarrier Coherence:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=3)
        self.coherence_label = ttk.Label(data_frame, text="0.0")
        self.coherence_label.grid(row=2, column=1, sticky=tk.W, padx=5, pady=3)

        # 控制按钮
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="Reset Stats", command=self.reset_stats).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Recalibrate", command=self.recalibrate).pack(side=tk.RIGHT, padx=5)

    # 修改 update_plots 方法，确保正确处理数据和坐标轴
    def update_plots(self, frame):
        """Update visualization plots with time series data"""
        # 更新CSI振幅图
        if hasattr(self, 'current_amplitude') and self.current_amplitude is not None and len(
                self.current_amplitude) > 0:
            # 清除现有线条
            for line in self.amplitude_lines:
                line.remove()
            self.amplitude_lines = []

            # 获取振幅数据的时间点数和子载波数量
            n_times, n_subcarriers = self.current_amplitude.shape

            # 选择最有变化的5个子载波进行显示
            if n_subcarriers > 5:
                variance_per_sub = np.var(self.current_amplitude, axis=0)
                top_subs = np.argsort(variance_per_sub)[-5:]
            else:
                top_subs = range(n_subcarriers)

            # 创建X轴时间点
            x_time = np.arange(n_times)

            # 绘制每个选择的子载波随时间的变化
            for i, sub_idx in enumerate(top_subs):
                line, = self.ax1.plot(x_time, self.current_amplitude[:, sub_idx],
                                      label=f'Subcarrier {sub_idx}')
                self.amplitude_lines.append(line)

            # 更新X轴范围以覆盖所有时间点
            self.ax1.set_xlim(0, n_times)

            # 更新Y轴范围，确保能看到数据变化
            all_values = self.current_amplitude[:, top_subs].flatten()
            if len(all_values) > 0:
                min_val = np.min(all_values)
                max_val = np.max(all_values)
                y_margin = (max_val - min_val) * 0.1  # 10%的边距
                self.ax1.set_ylim(min_val - y_margin, max_val + y_margin)

            # 更新图例
            self.ax1.legend(loc='upper right')

            # 更新标题以显示最新消息ID
            if self.last_message_id:
                self.ax1.set_title(f"CSI Amplitude (Message ID: {self.last_message_id})")

        # 更新方差和阈值图 - 关键修改
        if self.variance_history and self.threshold_history:
            # 确保使用numpy数组处理数据
            x = np.arange(len(self.variance_history))

            # 检查数据是否包含NaN值
            if np.any(np.isnan(self.variance_history)) or np.any(np.isnan(self.threshold_history)):
                print("警告: 方差或阈值历史中包含NaN值")
            else:
                # 更新数据
                self.variance_line.set_data(x, self.variance_history)
                self.threshold_line.set_data(x, self.threshold_history)

                # 设置X轴范围 - 确保从0开始
                self.ax2.set_xlim(0, max(1, len(self.variance_history)))

                # 设置Y轴范围，确保总是有正值
                if len(self.variance_history) > 0:
                    max_val = max(max(self.variance_history), max(self.threshold_history)) * 1.1
                    min_val = 0  # 强制Y轴从0开始
                    # 如果最大值太小，给一个默认范围
                    if max_val < 0.001:
                        max_val = 0.05
                    self.ax2.set_ylim(min_val, max_val)

                    # 调试输出
                    print(f"Y轴范围: {min_val} - {max_val}")

        # 更新检测结果图 - 关键修改
        if self.detection_buffer:
            x = np.arange(len(self.detection_buffer))
            self.detection_line.set_data(x, self.detection_buffer)

            # 设置X轴范围 - 确保从0开始
            self.ax3.set_xlim(0, max(1, len(self.detection_buffer)))

            # 确保Y轴范围固定为0-1，加一点边距
            self.ax3.set_ylim(-0.1, 1.1)

        # 更新画布
        self.canvas.draw_idle()

    def apply_threshold(self):
        """Apply new threshold and recalibrate detector"""
        try:
            new_threshold = float(self.threshold_var.get())
            # 更新检测器的阈值
            self.detector.base_threshold = new_threshold
            self.detector.threshold = new_threshold
            print(f"Threshold updated to: {new_threshold}")

            # 清除历史数据，以便看到新阈值的效果
            self.detection_history = []
            self.detection_buffer = []
            self.variance_history = []
            self.threshold_history = []
        except ValueError:
            # 如果输入的不是有效数字，恢复为当前值
            self.threshold_var.set(str(self.detector.threshold))

    # 添加重置函数清除所有历史数据
    def reset_stats(self):
        """Reset statistics"""
        self.detection_history = []
        self.detection_buffer = []
        self.variance_history = []
        self.threshold_history = []

        # 清除图表数据
        self.variance_line.set_data([], [])
        self.threshold_line.set_data([], [])
        self.detection_line.set_data([], [])

        # 更新UI标签
        self.total_count_label.config(text="0")
        self.motion_count_label.config(text="0")
        self.static_count_label.config(text="0")
        self.variance_label.config(text="0.0")
        self.current_threshold_label.config(text="0.0")

        # 强制更新画布
        self.canvas.draw_idle()

        print("Statistics reset")

    def recalibrate(self):
        """Recalibrate detector"""
        # 这里可以实现重新校准的逻辑
        print("Recalibration not implemented yet")

    def start_mqtt_client(self):
        """Start MQTT client"""
        # 获取MQTT配置
        mqtt_config = self.config.get('mqtt', {})
        broker_host = mqtt_config.get('host', 'localhost')
        broker_port = mqtt_config.get('port', 1883)

        # 创建MQTT客户端
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)  # 明确使用VERSION1 API
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message

        # 连接回调
        def mqtt_connect():
            try:
                self.mqtt_client.connect(broker_host, broker_port, 60)
                self.mqtt_client.loop_start()
                print(f"Connected to MQTT Broker: {broker_host}:{broker_port}")
            except Exception as e:
                print(f"MQTT connection failed: {e}")
                # 5秒后重试
                self.root.after(5000, mqtt_connect)

        # 开始连接
        mqtt_connect()

    def on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            print("Connected to MQTT Broker")
            self.mqtt_status.config(text="Connected", foreground="green")

            # 订阅CSI数据主题 - 这里改为订阅esp32/csi
            client.subscribe("esp32/csi")
        else:
            print(f"Connection failed with code: {rc}")
            self.mqtt_status.config(text=f"Connect Error: {rc}", foreground="red")

    def on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            # 解析CSI数据
            csi_str = msg.payload.decode()

            # 显示消息大小
            print(f"Received message of length: {len(csi_str)} bytes")

            # 打印截断的消息用于调试
            preview_len = 200 # 显示前50个字符
            print(f"Message preview: {csi_str[:preview_len]}{'...' if len(csi_str) > preview_len else ''}")

            # 将消息放入队列
            if not self.csi_data_queue.full():
                self.csi_data_queue.put(csi_str)

                # 更新数据速率 (简单计算，不精确)
                self.update_data_rate()
        except Exception as e:
            print(f"Error processing MQTT message: {e}")

    def update_data_rate(self):
        """Update data reception rate display"""
        current_time = time.time()
        if not hasattr(self, 'last_rate_update_time'):
            self.last_rate_update_time = current_time
            self.msg_count = 1
        else:
            self.msg_count += 1
            time_diff = current_time - self.last_rate_update_time
            if time_diff >= 1.0:  # 每秒更新一次
                rate = self.msg_count / time_diff
                self.rate_label.config(text=f"{rate:.1f} msgs/s")
                self.last_rate_update_time = current_time
                self.msg_count = 0

    def start_processing_thread(self):
        """Start data processing thread"""
        self.processing_thread = threading.Thread(target=self.process_csi_data, daemon=True)
        self.processing_thread.start()

    # 修改 process_csi_data 方法，确保正确填充数据
    def process_csi_data(self):
        """Process CSI data thread"""
        buffer = []
        buffer_size = 10  # 运动检测缓冲区大小
        last_state = False

        # 添加调试输出
        print("CSI data processing thread started")
        msg_count = 0
        last_debug_time = time.time()

        while self.running:
            try:
                # 从队列获取CSI数据
                if not self.csi_data_queue.empty():
                    csi_str = self.csi_data_queue.get(timeout=0.1)

                    # 调试消息计数
                    msg_count += 1
                    if msg_count % 100 == 0 or time.time() - last_debug_time > 5:
                        print(f"Processed {msg_count} messages. Queue size: {self.csi_data_queue.qsize()}")
                        print(f"Detection buffer size: {len(self.detection_buffer)}")
                        last_debug_time = time.time()

                    # 提取消息ID (用于显示)
                    parts = csi_str.split(',')
                    if len(parts) > 1:
                        self.last_message_id = parts[1]  # 假设ID在第二个位置
                        self.root.after(0, lambda mid=self.last_message_id: self.msg_id_label.config(text=mid))

                    # 解析CSI数据
                    csi_data = self.parse_csi_string(csi_str)

                    if csi_data is not None:
                        # 添加到缓冲区
                        buffer.append(csi_data)
                        if len(buffer) > buffer_size:
                            buffer.pop(0)

                        # 保存最新的振幅数据用于可视化
                        self.process_for_visualization(buffer)

                        # 只有当缓冲区足够大时才进行检测
                        if len(buffer) >= buffer_size:
                            # 合并缓冲区数据
                            combined_data = np.vstack(buffer)

                            # 检测运动
                            result = self.detector.detect(combined_data)
                            current_state = result['motion_detected']

                            # 更新检测结果历史 - 关键修改
                            self.detection_history.append(1 if current_state else 0)  # 确保使用0和1而非布尔值

                            # 更新方差和阈值历史 - 确保使用浮点数
                            if 'features' in result and 'amp_variance_mean' in result['features']:
                                variance = float(result['features']['amp_variance_mean'])
                                self.variance_history.append(variance)
                            else:
                                self.variance_history.append(0.0)

                            self.threshold_history.append(float(result['threshold']))

                            # 保持历史记录长度限制
                            if len(self.detection_history) > self.display_buffer_size:
                                self.detection_history.pop(0)
                            if len(self.variance_history) > self.display_buffer_size:
                                self.variance_history.pop(0)
                            if len(self.threshold_history) > self.display_buffer_size:
                                self.threshold_history.pop(0)

                            # 更新用于绘图的检测缓冲区
                            self.detection_buffer = self.detection_history.copy()

                            # 确保缓冲区非空
                            print(
                                f"Buffer updated - detection: {len(self.detection_buffer)}, variance: {len(self.variance_history)}")

                            # 如果状态变化，更新界面
                            if current_state != last_state:
                                last_state = current_state
                                self.motion_detected = current_state

                                # 在主线程中更新UI
                                self.root.after(0, self.update_detection_ui, current_state, result)

                            # 更新统计信息
                            self.root.after(0, self.update_stats_ui, result)
                else:
                    # 如果队列为空，等待一会儿
                    time.sleep(0.01)

            except queue.Empty:
                # 队列为空，继续循环
                pass
            except Exception as e:
                print(f"Error processing CSI data: {e}")
                import traceback
                traceback.print_exc()  # 添加更详细的错误信息
                time.sleep(0.1)  # 出错后暂停一小段时间

    def process_for_visualization(self, buffer):
        """Process data for visualization - keep time series data"""
        if not buffer:
            return

        # 创建时间序列数据存储
        if not hasattr(self, 'amplitude_series'):
            # 初始化存储20个时间点的数据，每个时间点包含所有子载波的振幅
            self.amplitude_series = []
            self.max_series_length = 50  # 保存50个时间点

        # 提取最近的一组CSI数据
        recent_data = buffer[-1]

        # 从CSI数据中提取振幅
        real = recent_data[:, :, 0]
        imag = recent_data[:, :, 1]
        amplitude = np.sqrt(real ** 2 + imag ** 2)

        # 添加到时间序列
        self.amplitude_series.append(amplitude[0])  # 添加一个时间点的所有子载波振幅

        # 限制序列长度
        if len(self.amplitude_series) > self.max_series_length:
            self.amplitude_series.pop(0)

        # 更新当前振幅数据为时间序列
        if self.amplitude_series:
            self.current_amplitude = np.array(self.amplitude_series)

    def parse_csi_string(self, csi_str):
        """Parse CSI data string"""
        try:
            # 检查是否为CSI数据
            if not csi_str.startswith("CSI_DATA"):
                return None

            # 首先找到引号包围的方括号部分
            if '"[' in csi_str and ']"' in csi_str:
                start_idx = csi_str.find('"[') + 2  # 跳过引号和左括号
                end_idx = csi_str.rfind(']"')

                if start_idx != -1 and end_idx != -1:
                    data_part = csi_str[start_idx:end_idx]
                    csi_values = [float(x.strip()) for x in data_part.split(',') if x.strip()]

                    print(f"Found {len(csi_values)} CSI values")

                    # 确保数据长度为偶数
                    if len(csi_values) % 2 != 0:
                        print(f"Warning: odd number of CSI values: {len(csi_values)}")
                        # 在偶数个值的情况下处理
                        # 舍弃最后一个值，保持偶数
                        csi_values = csi_values[:-1] if len(csi_values) % 2 != 0 else csi_values

                    # 重构数据为[subcarrier, real/imag]形式
                    n_subcarriers = len(csi_values) // 2
                    structured_data = np.zeros((1, n_subcarriers, 2))

                    for j in range(n_subcarriers):
                        real_idx = j * 2
                        imag_idx = j * 2 + 1
                        structured_data[0, j, 0] = csi_values[real_idx]  # 实部
                        structured_data[0, j, 1] = csi_values[imag_idx]  # 虚部

                    return structured_data
                else:
                    print("Could not find start/end quotes and brackets in data part")
            else:
                print("No CSI data array (quoted brackets) found in message")

            return None

        except Exception as e:
            print(f"Error parsing CSI data: {e}")
            import traceback
            traceback.print_exc()
            return None

    def update_detection_ui(self, is_motion, result):
        """Update detection status UI"""
        motion_status = "Motion" if is_motion else "Static"
        self.status_label.config(text=motion_status)

        # 更新状态指示灯颜色
        if is_motion:
            self.status_indicator.itemconfig(self.status_light, fill="red")
        else:
            self.status_indicator.itemconfig(self.status_light, fill="green")

    def update_stats_ui(self, result):
        """Update statistics UI"""
        # 计算统计数据
        total_detections = len(self.detection_history)
        motion_detections = sum(self.detection_history)
        static_detections = total_detections - motion_detections

        # 更新标签
        self.total_count_label.config(text=str(total_detections))
        self.motion_count_label.config(text=str(motion_detections))
        self.static_count_label.config(text=str(static_detections))

        # 更新最新数据信息
        if 'features' in result and 'amp_variance_mean' in result['features']:
            self.variance_label.config(text=f"{result['features']['amp_variance_mean']:.6f}")
        if 'threshold' in result:
            self.current_threshold_label.config(text=f"{result['threshold']:.6f}")
        if 'coherence' in result:
            self.coherence_label.config(text=f"{result['coherence']:.6f}")


    def on_closing(self):
        """Close application"""
        self.running = False
        if hasattr(self, 'mqtt_client'):
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = CSIVisualizationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()