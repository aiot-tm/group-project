import json
import time
import argparse
import paho.mqtt.client as mqtt
import numpy as np
import re

from motion_detector import MotionDetector


def load_config(config_path='config.json'):
    """加载配置文件"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载配置文件出错: {e}")
        return {}


def parse_csi_string(csi_str):
    """解析CSI数据字符串"""
    try:
        # 分割CSV格式数据
        parts = csi_str.split(',')

        # 提取CSI数据数组
        data_part = parts[-1].strip('"[]')
        csi_values = [float(x) for x in data_part.split(',')]

        # 确保数据长度为偶数
        if len(csi_values) % 2 != 0:
            return None

        # 重构数据为[subcarrier, real/imag]形式
        n_subcarriers = len(csi_values) // 2
        structured_data = np.zeros((1, n_subcarriers, 2))

        for j in range(n_subcarriers):
            real_idx = j * 2
            imag_idx = j * 2 + 1
            structured_data[0, j, 0] = csi_values[real_idx]  # 实部
            structured_data[0, j, 1] = csi_values[imag_idx]  # 虚部

        return structured_data

    except Exception as e:
        print(f"解析CSI数据出错: {e}")
        return None


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='CSI运动检测MQTT接收器')
    parser.add_argument('--config', type=str, default='config.json', help='配置文件路径')
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    mqtt_config = config.get('mqtt', {})

    # 创建运动检测器
    detector = MotionDetector(config.get('motion_detector', {}))

    # 保存最近的检测状态
    last_state = False
    buffer = []
    buffer_size = 10  # 缓冲区大小

    # 定义MQTT回调函数
    def on_connect(client, userdata, flags, rc):
        print(f"已连接到MQTT Broker: {mqtt_config.get('host', 'localhost')}")
        client.subscribe(mqtt_config.get('topic_csi', 'esp32/csi_data'))

    def on_message(client, userdata, msg):
        nonlocal last_state, buffer

        try:
            # 解析CSI数据
            csi_data = parse_csi_string(msg.payload.decode())

            if csi_data is None:
                return

            # 添加到缓冲区
            buffer.append(csi_data)
            if len(buffer) > buffer_size:
                buffer.pop(0)

            # 只有当缓冲区足够大时才进行检测
            if len(buffer) >= buffer_size:
                # 合并缓冲区数据
                combined_data = np.vstack(buffer)

                # 检测运动
                result = detector.detect(combined_data)
                current_state = result['motion_detected']

                # 如果状态变化，才输出和发布
                if current_state != last_state:
                    last_state = current_state
                    motion_status = "运动" if current_state else "静止"
                    timestamp = int(time.time() * 1000)

                    print(f"[{timestamp}] 检测到: {motion_status}")

                    # 发布检测结果
                    result_json = json.dumps({
                        'motion_detected': current_state,
                        'timestamp': timestamp,
                        'features': {
                            'variance': float(result['features']['amp_variance_mean']),
                            'threshold': float(result['threshold'])
                        }
                    })

                    client.publish(mqtt_config.get('topic_result', 'esp32/motion_result'), result_json)

        except Exception as e:
            print(f"处理消息出错: {e}")

    # 创建MQTT客户端
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    # 连接到MQTT Broker
    broker_host = mqtt_config.get('host', 'localhost')
    broker_port = mqtt_config.get('port', 1883)

    try:
        client.connect(broker_host, broker_port, 60)
        print(f"连接到MQTT Broker: {broker_host}:{broker_port}")

        # 启动循环
        client.loop_forever()

    except Exception as e:
        print(f"MQTT连接失败: {e}")


if __name__ == "__main__":
    main()