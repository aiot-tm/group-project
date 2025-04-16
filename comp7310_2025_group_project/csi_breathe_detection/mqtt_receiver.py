import json
import time
import argparse
import paho.mqtt.client as mqtt
import numpy as np
import re

from breathing_estimator import BreathingEstimator


def load_config(config_path='config.json'):
    """Load configuration file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config file: {e}")
        return {}


def parse_csi_string(csi_str):
    """Parse CSI data string"""
    try:
        # Split CSV format data
        parts = csi_str.split(',')

        # Extract CSI data array
        data_part = parts[-1].strip('"[]')
        csi_values = [float(x) for x in data_part.split(',')]

        # Ensure data length is even
        if len(csi_values) % 2 != 0:
            return None

        # Restructure data to [subcarrier, real/imag] format
        n_subcarriers = len(csi_values) // 2
        structured_data = np.zeros((1, n_subcarriers, 2))

        for j in range(n_subcarriers):
            real_idx = j * 2
            imag_idx = j * 2 + 1
            structured_data[0, j, 0] = csi_values[real_idx]  # Real part
            structured_data[0, j, 1] = csi_values[imag_idx]  # Imaginary part

        return structured_data

    except Exception as e:
        print(f"Error parsing CSI data: {e}")
        return None


def main():
    """Main function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='CSI Breathing Rate Estimation MQTT Receiver')
    parser.add_argument('--config', type=str, default='config.json', help='Path to config file')
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    mqtt_config = config.get('mqtt', {})

    # Create breathing rate estimator
    estimator = BreathingEstimator(config.get('breathing_estimator', {}))

    # Setup data buffer
    buffer = []
    buffer_size = estimator.config['window_size']  # Use window size as buffer size
    step_size = int(buffer_size * (1 - estimator.config['overlap']))  # Step size
    last_estimation_time = 0
    estimation_interval = 5  # Estimate breathing rate every 5 seconds

    # Store breathing rate history for display
    breathing_history = []
    time_history = []

    # Define MQTT callbacks
    def on_connect(client, userdata, flags, rc):
        print(f"Connected to MQTT Broker: {mqtt_config.get('host', 'localhost')}")
        client.subscribe(mqtt_config.get('topic_csi', 'esp32/csi_data'))

    def on_message(client, userdata, msg):
        nonlocal buffer, last_estimation_time, breathing_history, time_history

        try:
            # Parse CSI data
            csi_data = parse_csi_string(msg.payload.decode())

            if csi_data is None:
                return

            # Add to buffer
            buffer.append(csi_data[0])  # Add single sample

            # Limit buffer size, keep most recent data
            if len(buffer) > buffer_size * 2:  # Allow buffer to be a bit larger
                buffer = buffer[-buffer_size:]

            # Only estimate when buffer is large enough and interval is sufficient
            current_time = time.time()
            if (len(buffer) >= buffer_size and
                    (current_time - last_estimation_time) > estimation_interval):

                # Convert to numpy array
                csi_array = np.array(buffer[-buffer_size:])

                # Estimate breathing rate
                result = estimator.estimate_breathing_rate(csi_array)

                if result['breathing_rates']:
                    br = result['breathing_rates'][-1]  # Use latest estimate
                    timestamp = int(current_time * 1000)

                    # Update history
                    breathing_history.append(br)
                    time_history.append(current_time)

                    # Keep history at fixed length
                    if len(breathing_history) > 30:  # Keep last 30 estimates
                        breathing_history.pop(0)
                        time_history.pop(0)

                    print(f"[{timestamp}] Estimated breathing rate: {br} BPM")

                    # Publish breathing rate result
                    result_json = json.dumps({
                        'breathing_rate': br,
                        'timestamp': timestamp,
                        'confidence': 0.8,  # Simple fixed value
                        'window_size': buffer_size / 100  # Window size (seconds)
                    })

                    client.publish(mqtt_config.get('topic_result', 'esp32/breathing_result'), result_json)

                    # Update last estimation time
                    last_estimation_time = current_time

        except Exception as e:
            print(f"Error processing message: {e}")

    # Create MQTT client
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to MQTT Broker
    broker_host = mqtt_config.get('host', 'localhost')
    broker_port = mqtt_config.get('port', 1883)

    try:
        client.connect(broker_host, broker_port, 60)
        print(f"Connecting to MQTT Broker: {broker_host}:{broker_port}")

        # Start loop
        client.loop_forever()

    except Exception as e:
        print(f"MQTT connection failed: {e}")


if __name__ == "__main__":
    main()