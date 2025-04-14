import paho.mqtt.client as mqtt
import time

# Callback when the client connects to the broker
def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    # Subscribe to the esp32/csi topic
    client.subscribe("esp32/csi")

# Callback when a message is received from the broker
def on_message(client, userdata, msg):
    # Print the topic and message similar to mosquitto_sub -v format
    message = msg.payload.decode()
    print(f"{msg.topic} {message}")
    
    # Optional: Parse the CSI data if the message starts with "CSI_DATA"
    if message.startswith("CSI_DATA"):
        parse_csi_data(message)

# Function to parse the CSI data (adapt as needed)
def parse_csi_data(data_str):
    # First, remove any stray double quotes from the data string
    data_str = data_str.replace('"', '')
    
    # Split into fields.
    # In your message the CSI array is the 15th field so we set maxsplit=14.
    parts = data_str.split(",", 14)
    
    if len(parts) < 15:
        print("Received data does not have enough fields")
        return
    
    try:
        # Extract individual fields
        message_type = parts[0]
        device_id = parts[1]
        mac_address = parts[2]
        rssi = int(parts[3])
        channel = int(parts[4])
        
        # The CSI array is expected in the 15th field (index 14)
        csi_array_str = parts[14].strip()
        
        # Check for CSI array format
        if csi_array_str.startswith("[") and csi_array_str.endswith("]"):
            # Remove the square brackets
            csi_content = csi_array_str[1:-1]
            # Convert the comma-separated values into integers
            csi_values = [int(x.strip()) for x in csi_content.split(",") if x.strip()]
            print(f"Successfully parsed {len(csi_values)} CSI values")
            # Uncomment the next line to see the first few values for example:
            # print(f"RSSI: {rssi}, Channel: {channel}, First 5 CSI values: {csi_values[:5]}")
        else:
            print("Could not find expected CSI array format")
    
    except Exception as e:
        print(f"Error parsing CSI data: {e}")

# Create an MQTT client instance
client = mqtt.Client()

# Set callback functions
client.on_connect = on_connect
client.on_message = on_message

# Connect to the local MQTT broker
client.connect("localhost", 1883, 60)

# Process network traffic and callbacks in a blocking manner
try:
    print("Listening for messages on esp32/csi topic. Press Ctrl+C to exit.")
    client.loop_forever()
except KeyboardInterrupt:
    print("Script terminated by user")
    client.disconnect()