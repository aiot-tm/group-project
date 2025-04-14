import paho.mqtt.client as mqtt
import time
import threading

class CSIDataCollector:
    def __init__(self, max_window_size=2000):
        self.max_window_size = max_window_size
        self.data_buffer = []
        self.last_timestamps = []
        self.lock = threading.Lock()  # For thread safety
        
    def add_data(self, parsed_data):
        """Add a new data record to the buffer"""
        with self.lock:
            # Add data to buffer
            self.data_buffer.append(parsed_data)
            
            # Add timestamp for rate calculation
            current_time = time.time()
            self.last_timestamps.append(current_time)
            
            # Trim buffer if it exceeds max window size
            if len(self.data_buffer) > self.max_window_size:
                self.data_buffer = self.data_buffer[-self.max_window_size:]
            
            # Keep only the last 10 seconds of timestamps for rate calculation
            ten_seconds_ago = current_time - 10
            self.last_timestamps = [ts for ts in self.last_timestamps if ts > ten_seconds_ago]
    
    def get_recv_rate(self):
        """Calculate reception frequency in records per second"""
        with self.lock:
            if len(self.last_timestamps) < 2:
                return 0
            
            time_span = self.last_timestamps[-1] - self.last_timestamps[0]
            if time_span <= 0:
                return 0
            
            rate = (len(self.last_timestamps) - 1) / time_span
            return rate
    
    def get_recent_window(self, window_size):
        """Get most recent records up to window_size"""
        with self.lock:
            if window_size > self.max_window_size:
                print(f"Warning: Window size limited to maximum of {self.max_window_size}")
                window_size = self.max_window_size
            
            return self.data_buffer[-min(window_size, len(self.data_buffer)):]


def parse_csi_data(data_str):
    """Parse a CSI_DATA message into a structured format"""
    try:
        # Split into fields
        parts = data_str.split(",")
        
        # Extract individual fields
        message_type = parts[0]
        device_id = parts[1]
        mac_address = parts[2]
        rssi = int(parts[3])
        rate = int(parts[4])
        noise_floor = int(parts[5])
        fft_gain = int(parts[6])
        agc_gain = int(parts[7])
        channel = int(parts[8])
        local_timestamp = int(parts[9])
        sig_len = int(parts[10])
        rx_state = int(parts[11])
        data_len = int(parts[12])
        first_word = int(parts[13])
        
        # Find and extract the CSI array
        remaining_str = ",".join(parts[14:])
        
        csi_values = []
        # Check for array format and extract
        if "[" in remaining_str and "]" in remaining_str:
            start_idx = remaining_str.find("[")
            end_idx = remaining_str.rfind("]")
            if start_idx != -1 and end_idx != -1:
                csi_str = remaining_str[start_idx+1:end_idx].replace('"', '')
                csi_values = [int(x.strip()) for x in csi_str.split(",") if x.strip()]
        
        # Create a structured data record
        parsed_data = {
            "type": message_type,
            "id": device_id,
            "mac": mac_address,
            "rssi": rssi,
            "rate": rate,
            "noise_floor": noise_floor,
            "fft_gain": fft_gain,
            "agc_gain": agc_gain,
            "channel": channel,
            "local_timestamp": local_timestamp,
            "sig_len": sig_len,
            "rx_state": rx_state,
            "len": data_len,
            "first_word": first_word,
            "data": csi_values
        }
        
        return parsed_data
    
    except Exception as e:
        print(f"Error parsing CSI data: {e}")
        return None


# Create a global data collector instance
data_collector = CSIDataCollector()

# Callback when a message is received from the broker
def on_message(client, userdata, msg):
    message = msg.payload.decode()
    print(f"{msg.topic} {message}")
    
    # Parse CSI data if applicable
    if message.startswith("CSI_DATA"):
        parsed_data = parse_csi_data(message)
        if parsed_data:
            data_collector.add_data(parsed_data)
            print(f"Successfully parsed {len(parsed_data['data'])} CSI values")

# Callback when the client connects to the broker
def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    client.subscribe("esp32/csi")

# Main function
def main():
    # Create an MQTT client instance
    client = mqtt.Client()
    
    # Set callback functions
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Connect to the local MQTT broker
    client.connect("localhost", 1883, 60)
    
    # Start a non-blocking loop
    client.loop_start()
    
    try:
        print("Listening for messages on esp32/csi topic. Press Ctrl+C to exit.")
        while True:
            # Query and display reception rate and window once per second
            rate = data_collector.get_recv_rate()
            window = data_collector.get_recent_window(10)  # Get last 10 records
            
            print("\n--- CSI Data Statistics ---")
            print(f"Reception rate: {rate:.2f} records/second")
            print(f"Buffer size: {len(data_collector.data_buffer)} records")
            if window:
                print(f"Most recent record ID: {window[-1]['id']}")
            else:
                print("No records in window yet")
            
            time.sleep(1)
    except KeyboardInterrupt:
        print("Script terminated by user")
        client.disconnect()
        client.loop_stop()

if __name__ == "__main__":
    main()