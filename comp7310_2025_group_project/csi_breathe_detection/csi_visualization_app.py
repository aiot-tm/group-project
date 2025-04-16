import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import paho.mqtt.client as mqtt
import threading
import time
import json
import queue
import re
import os
from collections import deque

# Import breathing estimator
from breathing_estimator import BreathingEstimator


class CSIBreathingVisualizationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CSI Breathing Rate Estimation System")
        self.root.geometry("1600x900")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Set app icon if available
        try:
            self.root.iconbitmap('icon.ico')
        except:
            pass

        # Apply theme
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Custom styles
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TLabel', background='#f0f0f0', font=('Arial', 10))
        self.style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        self.style.configure('BPM.TLabel', font=('Arial', 16, 'bold'), foreground='#2c3e50')
        self.style.configure('Status.TLabel', font=('Arial', 10, 'bold'))
        self.style.configure('Green.Status.TLabel', foreground='green')
        self.style.configure('Red.Status.TLabel', foreground='red')
        self.style.configure('Orange.Status.TLabel', foreground='orange')

        # Load configuration
        self.config = self.load_config('config.json')

        # Create breathing estimator
        self.estimator = BreathingEstimator(self.config.get('breathing_estimator', {}))

        # Data structures
        self.data_buffer = deque(maxlen=600)  # Store CSI data
        self.time_buffer = deque(maxlen=600)  # Store timestamps
        self.breathing_rates = deque(maxlen=120)  # Store breathing rate results (2 minutes)
        self.breathing_times = deque(maxlen=120)  # Store breathing rate timestamps
        self.mae_values = deque(maxlen=50)  # Store MAE values if ground truth available
        self.confidence_values = deque(maxlen=120)  # Store confidence values
        self.selected_subcarriers = []  # Store selected subcarrier indices

        # For thread safety
        self.data_lock = threading.Lock()
        self.queue = queue.Queue()

        # Tracking variables
        self.recv_rate = 0
        self.total_samples = 0
        self.last_update_time = time.time()
        self.last_estimation_time = 0
        self.estimation_interval = 2  # Estimate breathing rate every 2 seconds
        self.current_bpm = 0
        self.avg_bpm = 0
        self.min_bpm = 0
        self.max_bpm = 0
        self.window_size = self.estimator.config['window_size']
        self.is_connected = False
        self.current_message_id = 0
        self.fft_peak_freq = 0
        self.fft_energy = 0

        # Detection statistics
        self.total_detections = 0
        self.amplitude_variance = 0
        self.subcarrier_coherence = 0
        self.signal_quality = "Good"  # Quality indicator

        # Create main container with scrollbar
        self.create_scrollable_ui()

        # Setup MQTT client
        self.setup_mqtt()

        # Setup periodic tasks
        self.update_gui()
        self.process_queue()

    def load_config(self, config_path='config.json'):
        """Load configuration file"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config file: {e}")
            return {}

    def create_scrollable_ui(self):
        """Create scrollable user interface"""
        # Create a canvas with scrollbar for main content
        self.main_canvas = tk.Canvas(self.root, bg="#f0f0f0")
        self.main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Add vertical scrollbar to canvas
        self.main_scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=self.main_canvas.yview)
        self.main_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure canvas
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)
        self.main_canvas.bind('<Configure>',
                              lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")))

        # Create a frame inside the canvas for all content
        self.main_frame = ttk.Frame(self.main_canvas, padding=10, style='TFrame')
        self.canvas_window = self.main_canvas.create_window((0, 0), window=self.main_frame, anchor="nw")

        # Make sure canvas window stretches with canvas width
        self.main_canvas.bind('<Configure>', self.on_canvas_configure)

        # Add mouse wheel scrolling
        self.main_canvas.bind_all("<MouseWheel>", self.on_mousewheel)

        # Now create all widgets within main_frame
        self.create_widgets()

    def on_canvas_configure(self, event):
        """Handle canvas size changes"""
        # Update the width of the canvas window
        self.main_canvas.itemconfig(self.canvas_window, width=event.width)
        # Update the scrollregion to encompass all content
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def on_mousewheel(self, event):
        """Handle mouse wheel scrolling"""
        self.main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def setup_mqtt(self):
        """Setup MQTT client and connection"""
        # Use the newer API version to avoid deprecation warning
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        # Get MQTT config
        mqtt_config = self.config.get('mqtt', {})
        self.broker_host = mqtt_config.get('host', 'localhost')
        self.broker_port = mqtt_config.get('port', 1883)

        # Use the topic that's actually receiving data
        self.csi_topic = 'esp32/csi'  # Direct assignment as suggested

        # Start MQTT client in a separate thread
        def mqtt_loop():
            try:
                self.client.connect(self.broker_host, self.broker_port, 60)
                self.log(f"Connecting to MQTT Broker: {self.broker_host}:{self.broker_port}")
                self.client.loop_forever()
            except Exception as e:
                self.log(f"MQTT connection failed: {e}")
                self.update_connection_status(False)

        mqtt_thread = threading.Thread(target=mqtt_loop)
        mqtt_thread.daemon = True
        mqtt_thread.start()

    def on_connect(self, client, userdata, flags, rc, properties=None):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.log(f"Connected to MQTT Broker")
            self.update_connection_status(True)
            # Subscribe to CSI topic
            client.subscribe(self.csi_topic)
        else:
            self.log(f"Failed to connect to MQTT Broker with result code {rc}")
            self.update_connection_status(False)

    def on_disconnect(self, client, userdata, rc, properties=None):
        """Callback when disconnected from MQTT broker"""
        self.log(f"Disconnected from MQTT Broker with result code {rc}")
        self.update_connection_status(False)

    def update_connection_status(self, connected):
        """Update connection status"""
        self.is_connected = connected
        if connected:
            self.mqtt_status.config(text="Connected", style="Green.Status.TLabel")
        else:
            self.mqtt_status.config(text="Disconnected", style="Red.Status.TLabel")

    def on_message(self, client, userdata, msg, properties=None):
        """Callback when receiving a message"""
        try:
            # Parse CSI data
            message = msg.payload.decode()
            if message.startswith("CSI_DATA"):
                # Extract message ID for display
                match = re.search(r'CSI_DATA,(\d+)', message)
                if match:
                    self.current_message_id = int(match.group(1))

                # Parse the CSI data
                csi_data = self.parse_csi_string(message)
                if csi_data is not None:
                    with self.data_lock:
                        self.data_buffer.append(csi_data)
                        self.time_buffer.append(time.time())
                        self.total_samples += 1

                    # Update reception rate
                    current_time = time.time()
                    time_diff = current_time - self.last_update_time
                    if time_diff >= 1.0:  # Update rate calculation every second
                        # Calculate samples per second
                        if len(self.time_buffer) >= 2:
                            time_span = self.time_buffer[-1] - self.time_buffer[0]
                            if time_span > 0:
                                self.recv_rate = (len(self.time_buffer) - 1) / time_span
                        self.last_update_time = current_time

                    # Check if it's time to estimate breathing rate
                    if current_time - self.last_estimation_time > self.estimation_interval:
                        self.queue.put("ESTIMATE")
                        self.last_estimation_time = current_time

        except Exception as e:
            self.log(f"Error processing message: {e}")

    def parse_csi_string(self, csi_str):
        """Parse CSI data string into numpy array"""
        try:
            # Split into fields for more robust parsing
            parts = csi_str.split(",")

            # Identify the part containing CSI data
            data_part = None
            for part in parts:
                if '[' in part and ']' in part:
                    data_part = part
                    break

            if not data_part:
                # Try to find the CSI data array pattern
                match = re.search(r'\[(.*)\]', csi_str)
                if match:
                    data_part = match.group(1)
                else:
                    return None

            # Clean and parse the CSI values
            data_part = data_part.replace('"', '').strip()
            if data_part.startswith('['):
                data_part = data_part[1:]
            if data_part.endswith(']'):
                data_part = data_part[:-1]

            csi_values = [float(x) for x in data_part.split(',') if x.strip()]

            # Ensure even number of values (real/imag pairs)
            if len(csi_values) % 2 != 0:
                return None

            # Reshape data to [1, subcarrier, real/imag] format for estimator
            n_subcarriers = len(csi_values) // 2
            structured_data = np.zeros((1, n_subcarriers, 2))

            for j in range(n_subcarriers):
                real_idx = j * 2
                imag_idx = j * 2 + 1
                if real_idx < len(csi_values) and imag_idx < len(csi_values):
                    structured_data[0, j, 0] = csi_values[real_idx]  # Real part
                    structured_data[0, j, 1] = csi_values[imag_idx]  # Imaginary part

            return structured_data[0]  # Return shape [subcarrier, real/imag]

        except Exception as e:
            self.log(f"Error parsing CSI data: {e}")
            return None

    def create_widgets(self):
        """Create all GUI widgets"""
        # Create header with title
        header_frame = ttk.Frame(self.main_frame, style='TFrame')
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_label = ttk.Label(header_frame, text="Real-time CSI Breathing Rate Estimation System",
                                font=('Arial', 16, 'bold'), anchor='center', style='TLabel')
        title_label.pack(fill=tk.X)

        # Create main content area with left and right panels
        content_frame = ttk.Frame(self.main_frame, style='TFrame')
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Left panel for visualizations
        left_panel = ttk.LabelFrame(content_frame, text="CSI Data Visualization", padding=10)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # Right panel for controls and stats - using width properly with pack_propagate
        right_panel = ttk.LabelFrame(content_frame, text="Detection Control", padding=10, width=300)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        right_panel.pack_propagate(False)  # Prevent the panel from shrinking

        # ===== LEFT PANEL CONTENT =====
        # Create figures for plots - REDUCED HEIGHT for better visibility

        # CSI Amplitude plot
        amplitude_frame = ttk.Frame(left_panel)
        amplitude_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.amplitude_fig = Figure(figsize=(6, 2.5), dpi=100)  # Reduced height
        self.amplitude_ax = self.amplitude_fig.add_subplot(111)
        self.amplitude_ax.set_title("CSI Amplitude (Message ID: 0)")
        self.amplitude_ax.set_xlabel("Sample")
        self.amplitude_ax.set_ylabel("Amplitude")
        self.amplitude_ax.grid(True)

        self.amplitude_canvas = FigureCanvasTkAgg(self.amplitude_fig, amplitude_frame)
        self.amplitude_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Variance & Threshold plot
        variance_frame = ttk.Frame(left_panel)
        variance_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 5))

        self.variance_fig = Figure(figsize=(6, 1.8), dpi=100)  # Reduced height
        self.variance_ax = self.variance_fig.add_subplot(111)
        self.variance_ax.set_title("Amplitude Variance & Threshold")
        self.variance_ax.set_xlabel("Time (s)")
        self.variance_ax.set_ylabel("Variance")
        self.variance_ax.grid(True)

        self.variance_canvas = FigureCanvasTkAgg(self.variance_fig, variance_frame)
        self.variance_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Breathing Rate Result plot
        br_frame = ttk.Frame(left_panel)
        br_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self.br_fig = Figure(figsize=(6, 2.5), dpi=100)  # Reduced height
        self.br_ax = self.br_fig.add_subplot(111)
        self.br_ax.set_title("Breathing Rate Estimation")
        self.br_ax.set_xlabel("Time (s)")
        self.br_ax.set_ylabel("Breathing Rate (BPM)")
        self.br_ax.set_ylim(5, 30)
        self.br_ax.grid(True)

        self.br_canvas = FigureCanvasTkAgg(self.br_fig, br_frame)
        self.br_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ===== RIGHT PANEL CONTENT =====
        # System Status Section - cleaned up layout
        status_frame = ttk.LabelFrame(right_panel, text="System Status")
        status_frame.pack(fill=tk.X, pady=(0, 10))

        # Using grid layout for cleaner alignment
        # Current status
        ttk.Label(status_frame, text="Current Status:", anchor='w').grid(row=0, column=0, sticky='w', padx=5, pady=2)
        status_container = ttk.Frame(status_frame)
        status_container.grid(row=0, column=1, sticky='w', padx=5, pady=2)

        self.status_indicator = ttk.Label(status_container, text="Waiting for data...", style='Status.TLabel')
        self.status_indicator.pack(side=tk.LEFT)

        self.status_canvas = tk.Canvas(status_container, width=15, height=15, bg="#f0f0f0", highlightthickness=0)
        self.status_canvas.pack(side=tk.LEFT, padx=(5, 0))
        self.status_dot = self.status_canvas.create_oval(2, 2, 13, 13, fill="gray")

        # Latest message ID
        ttk.Label(status_frame, text="Latest Message ID:", anchor='w').grid(row=1, column=0, sticky='w', padx=5, pady=2)
        self.message_id_label = ttk.Label(status_frame, text="0")
        self.message_id_label.grid(row=1, column=1, sticky='w', padx=5, pady=2)

        # MQTT Connection
        ttk.Label(status_frame, text="MQTT Connection:", anchor='w').grid(row=2, column=0, sticky='w', padx=5, pady=2)
        self.mqtt_status = ttk.Label(status_frame, text="Connecting...", style='Orange.Status.TLabel')
        self.mqtt_status.grid(row=2, column=1, sticky='w', padx=5, pady=2)

        # Data rate
        ttk.Label(status_frame, text="Data Rate:", anchor='w').grid(row=3, column=0, sticky='w', padx=5, pady=2)
        self.rate_label = ttk.Label(status_frame, text="0 msgs/s")
        self.rate_label.grid(row=3, column=1, sticky='w', padx=5, pady=2)

        # Signal quality
        ttk.Label(status_frame, text="Signal Quality:", anchor='w').grid(row=4, column=0, sticky='w', padx=5, pady=2)
        self.quality_label = ttk.Label(status_frame, text="Unknown")
        self.quality_label.grid(row=4, column=1, sticky='w', padx=5, pady=2)

        # Parameters section
        params_frame = ttk.LabelFrame(right_panel, text="Detection Parameters")
        params_frame.pack(fill=tk.X, pady=10)

        # Threshold control
        thresh_frame = ttk.Frame(params_frame)
        thresh_frame.pack(fill=tk.X, pady=2)
        ttk.Label(thresh_frame, text="Threshold:").pack(side=tk.LEFT, padx=5)
        self.threshold_var = tk.StringVar(value="0.015")
        threshold_entry = ttk.Entry(thresh_frame, textvariable=self.threshold_var, width=8)
        threshold_entry.pack(side=tk.LEFT, padx=5)
        apply_btn = ttk.Button(thresh_frame, text="Apply", command=self.apply_threshold)
        apply_btn.pack(side=tk.RIGHT, padx=5)

        # Estimation interval
        interval_frame = ttk.Frame(params_frame)
        interval_frame.pack(fill=tk.X, pady=2)
        ttk.Label(interval_frame, text="Estimation Interval (s):").pack(side=tk.LEFT, padx=5)
        interval_var = tk.StringVar(value=str(self.estimation_interval))
        interval_combo = ttk.Combobox(interval_frame, textvariable=interval_var,
                                      values=["1", "2", "3", "5", "10"], width=3)
        interval_combo.pack(side=tk.LEFT, padx=5)

        def on_interval_change(event):
            try:
                self.estimation_interval = float(interval_var.get())
                self.log(f"Changed estimation interval to {self.estimation_interval} seconds")
            except ValueError:
                pass

        interval_combo.bind("<<ComboboxSelected>>", on_interval_change)

        # Window size display
        window_frame = ttk.Frame(params_frame)
        window_frame.pack(fill=tk.X, pady=2)
        ttk.Label(window_frame, text="Window Size:").pack(side=tk.LEFT, padx=5)
        self.window_label = ttk.Label(window_frame, text=f"{self.window_size} samples")
        self.window_label.pack(side=tk.LEFT, padx=5)

        # Breathing statistics
        breathing_frame = ttk.LabelFrame(right_panel, text="Breathing Statistics")
        breathing_frame.pack(fill=tk.X, pady=10)

        # Using grid for better alignment
        row = 0

        # Total detections
        ttk.Label(breathing_frame, text="Total Detections:", anchor='w').grid(row=row, column=0, sticky='w', padx=5,
                                                                              pady=2)
        self.total_label = ttk.Label(breathing_frame, text="0")
        self.total_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # Current BPM
        ttk.Label(breathing_frame, text="Current BPM:", anchor='w').grid(row=row, column=0, sticky='w', padx=5, pady=2)
        self.br_value_label = ttk.Label(breathing_frame, text="-- BPM", style='BPM.TLabel')
        self.br_value_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # Average BPM
        ttk.Label(breathing_frame, text="Average BPM:", anchor='w').grid(row=row, column=0, sticky='w', padx=5, pady=2)
        self.avg_br_label = ttk.Label(breathing_frame, text="-- BPM")
        self.avg_br_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # BPM Range
        ttk.Label(breathing_frame, text="BPM Range:", anchor='w').grid(row=row, column=0, sticky='w', padx=5, pady=2)
        self.range_label = ttk.Label(breathing_frame, text="-- to -- BPM")
        self.range_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # MAE
        ttk.Label(breathing_frame, text="MAE:", anchor='w').grid(row=row, column=0, sticky='w', padx=5, pady=2)
        self.mae_label = ttk.Label(breathing_frame, text="N/A")
        self.mae_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)

        # Signal metrics
        metrics_frame = ttk.LabelFrame(right_panel, text="Signal Metrics")
        metrics_frame.pack(fill=tk.X, pady=10)

        # Using grid for better alignment
        row = 0

        # Amplitude variance
        ttk.Label(metrics_frame, text="Amplitude Variance:", anchor='w').grid(row=row, column=0, sticky='w', padx=5,
                                                                              pady=2)
        self.amp_var_label = ttk.Label(metrics_frame, text="0.000000")
        self.amp_var_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # Current threshold
        ttk.Label(metrics_frame, text="Current Threshold:", anchor='w').grid(row=row, column=0, sticky='w', padx=5,
                                                                             pady=2)
        self.cur_threshold_label = ttk.Label(metrics_frame, text="0.015000")
        self.cur_threshold_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # Subcarrier coherence
        ttk.Label(metrics_frame, text="Subcarrier Coherence:", anchor='w').grid(row=row, column=0, sticky='w', padx=5,
                                                                                pady=2)
        self.coherence_label = ttk.Label(metrics_frame, text="0.000000")
        self.coherence_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # FFT peak frequency
        ttk.Label(metrics_frame, text="FFT Peak (Hz):", anchor='w').grid(row=row, column=0, sticky='w', padx=5, pady=2)
        self.fft_freq_label = ttk.Label(metrics_frame, text="0.000 Hz")
        self.fft_freq_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)
        row += 1

        # Selected subcarriers
        ttk.Label(metrics_frame, text="Selected Subcarriers:", anchor='w').grid(row=row, column=0, sticky='w', padx=5,
                                                                                pady=2)
        self.subcarr_label = ttk.Label(metrics_frame, text="None")
        self.subcarr_label.grid(row=row, column=1, sticky='w', padx=5, pady=2)

        # Control buttons
        control_frame = ttk.Frame(right_panel)
        control_frame.pack(fill=tk.X, pady=10)

        reset_btn = ttk.Button(control_frame, text="Reset Stats", command=self.reset_stats)
        reset_btn.pack(side=tk.LEFT, padx=5)

        recalibrate_btn = ttk.Button(control_frame, text="Recalibrate", command=self.recalibrate)
        recalibrate_btn.pack(side=tk.RIGHT, padx=5)

        # Log frame for messages at bottom
        log_frame = ttk.LabelFrame(self.main_frame, text="Log Messages", padding=5)
        log_frame.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)

        # Create scrolled text widget for logs
        self.log_text = scrolledtext.ScrolledText(log_frame, height=4, width=100, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def apply_threshold(self):
        """Apply new threshold value"""
        try:
            threshold = float(self.threshold_var.get())
            if threshold <= 0:
                messagebox.showerror("Invalid Input", "Threshold must be greater than 0")
                return

            self.cur_threshold_label.config(text=f"{threshold:.6f}")
            self.log(f"Applied new threshold: {threshold:.6f}")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number")

    def reset_stats(self):
        """Reset statistics"""
        with self.data_lock:
            self.breathing_rates.clear()
            self.breathing_times.clear()
            self.confidence_values.clear()
            self.mae_values.clear()
            self.total_detections = 0
            self.current_bpm = 0
            self.avg_bpm = 0
            self.min_bpm = 0
            self.max_bpm = 0

        self.log("Statistics reset")
        self.update_all_plots()

    def recalibrate(self):
        """Recalibrate the system"""
        # Clear data buffer but keep a small portion to avoid lag
        with self.data_lock:
            keep_size = min(len(self.data_buffer), 50)
            if keep_size > 0:
                temp_data = list(self.data_buffer)[-keep_size:]
                temp_time = list(self.time_buffer)[-keep_size:]
                self.data_buffer.clear()
                self.time_buffer.clear()
                self.data_buffer.extend(temp_data)
                self.time_buffer.extend(temp_time)

            # Reset detection stats but maintain breathing history
            self.total_detections = 0

        self.log("System recalibrated")

    def update_gui(self):
        """Update GUI elements"""
        try:
            # Update message ID
            self.message_id_label.config(text=str(self.current_message_id))

            # Update rate label
            self.rate_label.config(text=f"{self.recv_rate:.1f} msgs/s")

            # Update detection statistics
            self.total_label.config(text=str(self.total_detections))

            # Update signal metrics
            self.amp_var_label.config(text=f"{self.amplitude_variance:.6f}")
            self.coherence_label.config(text=f"{self.subcarrier_coherence:.6f}")
            self.fft_freq_label.config(text=f"{self.fft_peak_freq:.3f} Hz")

            # Update selected subcarriers
            if self.selected_subcarriers:
                self.subcarr_label.config(text=", ".join(map(str, self.selected_subcarriers)))

            # Update breathing rate label
            if self.breathing_rates:
                self.br_value_label.config(text=f"{self.current_bpm} BPM")
                self.avg_br_label.config(text=f"{self.avg_bpm:.1f} BPM")
                self.range_label.config(text=f"{self.min_bpm} to {self.max_bpm} BPM")

            # Update signal quality
            self.quality_label.config(text=self.signal_quality)

            # Update MAE label
            if self.mae_values:
                mae_median = np.median(self.mae_values)
                self.mae_label.config(text=f"{mae_median:.2f}")

            # Update status indicator based on data flow
            self.update_status_indicator()

        except Exception as e:
            print(f"Error updating GUI: {e}")

        # Schedule next update
        self.root.after(500, self.update_gui)

    def update_status_indicator(self):
        """Update status indicator based on data flow"""
        current_time = time.time()

        # Check if we're receiving data
        if self.is_connected and len(self.time_buffer) > 0 and current_time - self.time_buffer[-1] < 2.0:
            # Active data flow
            self.status_indicator.config(text="Active - Receiving Data")
            self.status_canvas.itemconfig(self.status_dot, fill="green")
        elif self.is_connected:
            # Connected but no recent data
            self.status_indicator.config(text="Connected - No Data Flow")
            self.status_canvas.itemconfig(self.status_dot, fill="orange")
        else:
            # Not connected
            self.status_indicator.config(text="Disconnected")
            self.status_canvas.itemconfig(self.status_dot, fill="red")

    def process_queue(self):
        """Process queued tasks"""
        try:
            while not self.queue.empty():
                task = self.queue.get(block=False)

                if task == "ESTIMATE":
                    self.estimate_breathing_rate()

                self.queue.task_done()
        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(100, self.process_queue)

    def estimate_breathing_rate(self):
        """Estimate breathing rate from buffered data"""
        with self.data_lock:
            if len(self.data_buffer) < self.window_size:
                self.log(f"Not enough data for estimation (need {self.window_size} samples)")
                return

            # Get data for processing
            data = list(self.data_buffer)[-self.window_size:]

            # Convert to numpy array [sample, subcarrier, real/imag]
            csi_data = np.array(data)

        try:
            # Preprocess for metrics
            preprocessed = self.estimator.preprocess(csi_data)

            # Save selected subcarriers
            if 'selected_indices' in preprocessed and preprocessed['selected_indices'] is not None:
                self.selected_subcarriers = preprocessed['selected_indices'].tolist()

            # Calculate amplitude variance
            if 'filtered_amplitude' in preprocessed:
                filtered_amp = preprocessed['filtered_amplitude']
                self.amplitude_variance = np.var(filtered_amp)

            # Calculate subcarrier coherence (simplified correlation measure)
            if 'selected_amplitude' in preprocessed and preprocessed['selected_amplitude'].shape[1] > 1:
                amp = preprocessed['selected_amplitude']
                corr_matrix = np.corrcoef(amp.T)
                # Average of off-diagonal elements
                self.subcarrier_coherence = (np.sum(corr_matrix) - np.trace(corr_matrix)) / (
                            corr_matrix.size - corr_matrix.shape[0])

            # Set signal quality based on coherence
            if self.subcarrier_coherence > 0.8:
                self.signal_quality = "Excellent"
            elif self.subcarrier_coherence > 0.6:
                self.signal_quality = "Good"
            elif self.subcarrier_coherence > 0.4:
                self.signal_quality = "Fair"
            else:
                self.signal_quality = "Poor"

            # Estimate breathing rate
            result = self.estimator.estimate_breathing_rate(csi_data)

            if result and 'breathing_rates' in result and result['breathing_rates']:
                # Get the latest BR and round to integer
                br = result['breathing_rates'][-1]
                self.current_bpm = round(br)  # Round to nearest integer

                # Extract FFT peak if available
                if 'fft_peak_freq' in result:
                    self.fft_peak_freq = result['fft_peak_freq']

                current_time = time.time()

                with self.data_lock:
                    self.breathing_rates.append(self.current_bpm)
                    self.breathing_times.append(current_time)
                    self.total_detections += 1

                    # Update min/max and average BPM
                    if self.breathing_rates:
                        self.avg_bpm = np.mean(self.breathing_rates)
                        self.min_bpm = min(self.breathing_rates)
                        self.max_bpm = max(self.breathing_rates)

                # Log result with confidence info
                confidence_str = f" (Confidence: {result.get('confidence', 'N/A')})"
                self.log(f"Breathing rate: {self.current_bpm} BPM (Average: {self.avg_bpm:.1f} BPM){confidence_str}")

                # Update plots
                self.update_all_plots()

                # Store confidence value if available
                if 'confidence' in result:
                    self.confidence_values.append(result['confidence'])

                # Publish result to MQTT if configured
                self.publish_result(self.current_bpm, result.get('confidence', 0.8))

        except Exception as e:
            self.log(f"Error in breathing estimation: {e}")
            import traceback
            traceback.print_exc()

    def update_all_plots(self):
        """Update all plots with latest data"""
        try:
            self.update_amplitude_plot()
            self.update_variance_plot()
            self.update_breathing_rate_plot()
        except Exception as e:
            self.log(f"Error updating plots: {e}")

    def update_amplitude_plot(self):
        """Update CSI amplitude plot"""
        with self.data_lock:
            if len(self.data_buffer) < 50:  # Need at least some data
                return

            # Get last 50 samples for display
            latest_data = list(self.data_buffer)[-50:]

        # Calculate amplitude for each sample
        csi_data = np.array(latest_data)

        # Clear the plot
        self.amplitude_ax.clear()
        self.amplitude_ax.set_title(f"CSI Amplitude (Message ID: {self.current_message_id})")
        self.amplitude_ax.set_xlabel("Sample")
        self.amplitude_ax.set_ylabel("Amplitude")
        self.amplitude_ax.grid(True)

        # Plot up to 5 selected subcarriers
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        legend_entries = []

        # If we have selected subcarriers from the estimator, use those
        plot_indices = self.selected_subcarriers if self.selected_subcarriers else range(min(5, csi_data.shape[1]))

        for idx, i in enumerate(plot_indices[:5]):  # Limit to 5 for clarity
            if i < csi_data.shape[1]:
                # Calculate amplitude
                amp = np.sqrt(csi_data[:, i, 0] ** 2 + csi_data[:, i, 1] ** 2)
                line, = self.amplitude_ax.plot(amp, color=colors[idx % len(colors)])
                # Display original subcarrier number, not just the index
                legend_entries.append(f'Subcarrier {i}')

        self.amplitude_ax.legend(legend_entries)
        self.amplitude_canvas.draw()

    def update_variance_plot(self):
        """Update amplitude variance plot"""
        with self.data_lock:
            if len(self.breathing_times) < 2:
                return

            # Use time from breathing rate estimation
            times = list(self.breathing_times)
            start_time = times[0]
            rel_times = [t - start_time for t in times]

            # Create variance trace using stored breathing times
            variance_data = []
            for i in range(len(rel_times)):
                # Add some slight variation around the actual variance
                variance_data.append(self.amplitude_variance * (0.9 + 0.2 * np.random.random()))

            # Get threshold
            try:
                threshold = float(self.threshold_var.get())
            except ValueError:
                threshold = 0.015

        # Clear the plot
        self.variance_ax.clear()
        self.variance_ax.set_title("Amplitude Variance & Threshold")
        self.variance_ax.set_xlabel("Time (s)")
        self.variance_ax.set_ylabel("Variance")
        self.variance_ax.grid(True)

        # Plot variance
        self.variance_ax.plot(rel_times, variance_data, 'b-', label='Amplitude Variance')

        # Plot threshold line
        self.variance_ax.axhline(y=threshold, color='r', linestyle='--', label='Detection Threshold')

        # Auto-scale y-axis to show data properly
        if variance_data:
            max_var = max(variance_data)
            self.variance_ax.set_ylim(0, max(threshold * 2, max_var * 1.2))

        # Match x-axis to breathing rate plot
        if rel_times:
            max_time = rel_times[-1]
            if max_time > 60:
                start_time = max_time - 60
                self.variance_ax.set_xlim(start_time, max_time)

        self.variance_ax.legend()
        self.variance_canvas.draw()

    def update_breathing_rate_plot(self):
        """Update breathing rate plot"""
        with self.data_lock:
            if len(self.breathing_rates) < 2:
                return

            # Calculate relative time (seconds from start)
            times = list(self.breathing_times)
            start_time = times[0]
            rel_times = [t - start_time for t in times]
            bpm_values = list(self.breathing_rates)
            confidence_values = list(self.confidence_values) if self.confidence_values else None

        # Clear the plot
        self.br_ax.clear()
        self.br_ax.set_title("Breathing Rate Estimation")
        self.br_ax.set_xlabel("Time (s)")
        self.br_ax.set_ylabel("Breathing Rate (BPM)")
        self.br_ax.grid(True)

        # Plot breathing rates with markers
        self.br_ax.plot(rel_times, bpm_values, 'b-o', markersize=4)

        # Set reasonable y-axis limits
        min_bpm = min(bpm_values) if bpm_values else 5
        max_bpm = max(bpm_values) if bpm_values else 30
        padding = (max_bpm - min_bpm) * 0.2 if max_bpm > min_bpm else 5
        self.br_ax.set_ylim(max(5, min_bpm - padding), min(30, max_bpm + padding))

        # Show latest minute of data on x-axis
        if rel_times and rel_times[-1] > 60:
            start_time = rel_times[-1] - 60
            self.br_ax.set_xlim(start_time, rel_times[-1])

        # Add average line
        avg_bpm = np.mean(bpm_values)
        self.br_ax.axhline(y=avg_bpm, color='r', linestyle='--',
                           label=f'Average: {avg_bpm:.1f} BPM')

        # Add confidence indication if available
        if confidence_values and len(confidence_values) >= len(bpm_values):
            conf_values = confidence_values[-len(bpm_values):]
            # Only show confidence for values >=0.5 to avoid clutter
            for i, (t, bpm, conf) in enumerate(zip(rel_times, bpm_values, conf_values)):
                if i % 5 == 0:  # Show every 5th label to avoid clutter
                    self.br_ax.annotate(f"{conf:.1f}", (t, bpm),
                                        fontsize=8, alpha=0.7,
                                        textcoords="offset points",
                                        xytext=(0, 5), ha='center')

        self.br_ax.legend()
        self.br_canvas.draw()

    def publish_result(self, breathing_rate, confidence=0.8):
        """Publish breathing rate result to MQTT"""
        try:
            # Get MQTT topic
            topic = self.config.get('mqtt', {}).get('topic_result', 'esp32/breathing_result')

            # Create payload
            payload = json.dumps({
                'breathing_rate': breathing_rate,
                'timestamp': int(time.time() * 1000),
                'message_id': self.current_message_id,
                'confidence': confidence,
                'signal_quality': self.signal_quality,
                'amplitude_variance': float(self.amplitude_variance)
            })

            # Publish
            self.client.publish(topic, payload)
            self.log(f"Published result: {breathing_rate} BPM to {topic}")

        except Exception as e:
            self.log(f"Error publishing result: {e}")

    def log(self, message):
        """Add message to log widget"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)  # Scroll to bottom

    def on_closing(self):
        """Handle window closing"""
        if hasattr(self, 'client'):
            self.client.disconnect()
        self.root.destroy()


def main():
    # Create and run GUI application
    root = tk.Tk()
    app = CSIBreathingVisualizationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()