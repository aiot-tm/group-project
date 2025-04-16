import numpy as np
import json
import time
import os


class MotionDetector:
    """CSI运动检测类"""

    def __init__(self, config=None):
        """
        初始化运动检测器

        参数:
        config: 配置字典，如果为None则使用默认配置
        """
        # Default configuration
        self.config = {
            'variance_threshold': 0.015,
            'diff_threshold': 0.025,
            'window_size': 5,
            'noise_multiplier': 2.0,
            'normalize': True,
            'adaptation_rate': 0.05,
            'coherence_threshold': 0.7  # 子载波协同性阈值
        }

        # Update with provided config
        if config:
            self.config.update(config)

        # Detector state
        self.threshold = self.config['variance_threshold']
        self.base_threshold = self.threshold
        self.noise_level = 0.0
        self.last_update_time = time.time()

        # Try loading calibration from file
        self._load_calibration()

    def _load_calibration(self):
        """从文件加载校准数据"""
        try:
            # Try loading calibration file
            calibration_file = 'motion_calibration.json'
            if os.path.exists(calibration_file):
                with open(calibration_file, 'r') as f:
                    calibration_data = json.load(f)
                    self.base_threshold = calibration_data.get('base_threshold', self.threshold)
                    self.threshold = self.base_threshold
                    self.noise_multiplier = calibration_data.get('noise_multiplier',
                                                                 self.config['noise_multiplier'])
                    print(f"Loaded calibration data: base_threshold={self.base_threshold}, noise_multiplier={self.noise_multiplier}")
            else:
                print("No calibration file found, using default threshold")
        except Exception as e:
            print(f"Error loading calibration data: {e}")

    def _save_calibration(self, calibration_data):
        """保存校准数据到文件"""
        try:
            with open('motion_calibration.json', 'w') as f:
                json.dump(calibration_data, f, indent=2)
            print("Calibration data saved")
        except Exception as e:
            print(f"Error saving calibration data: {e}")

    def preprocess(self, csi_data):
        """
        预处理CSI数据

        参数:
        csi_data: 原始CSI数据 [sample, subcarrier, real/imag]

        返回:
        处理后的数据，包含幅度和相位
        """
        # Extract real and imaginary parts
        real = csi_data[:, :, 0]  # All samples, all subcarriers, real part
        imag = csi_data[:, :, 1]  # All samples, all subcarriers, imaginary part

        # Calculate amplitude and phase
        amplitude = np.sqrt(real ** 2 + imag ** 2)
        phase = np.unwrap(np.arctan2(imag, real), axis=0)

        # Apply smoothing window
        window_size = self.config['window_size']
        if window_size > 1 and amplitude.shape[0] > window_size:
            smoothed_amplitude = np.zeros_like(amplitude)
            for i in range(amplitude.shape[1]):  # For each subcarrier
                smoothed_amplitude[:, i] = np.convolve(amplitude[:, i],
                                                       np.ones(window_size) / window_size,
                                                       mode='same')
        else:
            smoothed_amplitude = amplitude

        # Normalize
        if self.config['normalize']:
            for i in range(smoothed_amplitude.shape[1]):  # For each subcarrier
                subcarrier_data = smoothed_amplitude[:, i]
                min_val = np.min(subcarrier_data)
                max_val = np.max(subcarrier_data)
                if max_val > min_val:
                    smoothed_amplitude[:, i] = (subcarrier_data - min_val) / (max_val - min_val)

        # Estimate noise level
        subcarrier_stds = np.std(smoothed_amplitude, axis=0)
        noise_level = np.min(subcarrier_stds)

        # Get most varying subcarriers
        variance_per_subcarrier = np.var(smoothed_amplitude, axis=0)
        top_subcarriers = np.argsort(variance_per_subcarrier)[-3:]  # Top 3 most varying

        return {
            'amplitude': amplitude,
            'smoothed_amplitude': smoothed_amplitude,
            'phase': phase,
            'noise_level': noise_level,
            'top_subcarriers': top_subcarriers
        }

    def extract_features(self, processed_data):
        """
        提取运动检测特征

        参数:
        processed_data: 预处理后的数据

        返回:
        特征字典
        """
        # Get processed amplitude data
        amplitude = processed_data['smoothed_amplitude']

        # Features using all subcarriers
        features = {}

        # Key feature 1: Amplitude variance - higher during motion
        amp_variance = np.var(amplitude, axis=0)
        features['amp_variance'] = amp_variance
        features['amp_variance_mean'] = np.mean(amp_variance)

        # Key feature 2: Amplitude change rate - faster during motion
        amp_diff = np.diff(amplitude, axis=0)
        if amp_diff.size > 0:
            features['amp_diff_mean'] = np.mean(np.abs(amp_diff), axis=0)
            features['amp_diff_mean_avg'] = np.mean(features['amp_diff_mean'])
        else:
            features['amp_diff_mean'] = np.zeros(amplitude.shape[1])
            features['amp_diff_mean_avg'] = 0

        # Key feature 3: Min-max range - larger during motion
        amp_range = np.max(amplitude, axis=0) - np.min(amplitude, axis=0)
        features['amp_range'] = amp_range
        features['amp_range_mean'] = np.mean(amp_range)

        # Weight by most varying subcarriers
        top_subcarriers = processed_data['top_subcarriers']
        if len(top_subcarriers) > 0:
            features['top_subcarriers_variance'] = np.mean(amp_variance[top_subcarriers])
            features['top_subcarriers_diff'] = np.mean(features['amp_diff_mean'][top_subcarriers])
        else:
            features['top_subcarriers_variance'] = features['amp_variance_mean']
            features['top_subcarriers_diff'] = features['amp_diff_mean_avg']

        return features

    def calibrate(self, static_data_list, motion_data_list):
        """
        校准检测阈值

        参数:
        static_data_list: 静态CSI数据列表
        motion_data_list: 运动CSI数据列表

        返回:
        校准后的阈值
        """
        print("Starting motion detection threshold calibration...")

        # Process static data
        static_features = []
        for data in static_data_list:
            try:
                processed = self.preprocess(data['csi_data'])
                features = self.extract_features(processed)
                static_features.append(features)
            except Exception as e:
                print(f"Error processing static file: {e}")

        # Process motion data
        motion_features = []
        for data in motion_data_list:
            try:
                processed = self.preprocess(data['csi_data'])
                features = self.extract_features(processed)
                motion_features.append(features)
            except Exception as e:
                print(f"Error processing motion file: {e}")

        # Ensure enough data for calibration
        if len(static_features) == 0 or len(motion_features) == 0:
            print("Warning: Not enough data for calibration, using default threshold")
            return self.threshold

        # Calculate mean amplitude variance
        static_variance = np.mean([f['amp_variance_mean'] for f in static_features])
        motion_variance = np.mean([f['amp_variance_mean'] for f in motion_features])

        # Calculate mean amplitude change rate
        static_diff = np.mean([f['amp_diff_mean_avg'] for f in static_features])
        motion_diff = np.mean([f['amp_diff_mean_avg'] for f in motion_features])

        # Calculate optimal threshold - variance feature
        variance_threshold = (static_variance + motion_variance) / 2

        # Calculate optimal threshold - change rate feature
        diff_threshold = (static_diff + motion_diff) / 2

        # Update thresholds
        self.base_threshold = variance_threshold
        self.threshold = self.base_threshold
        self.config['variance_threshold'] = variance_threshold
        self.config['diff_threshold'] = diff_threshold

        # Calculate noise multiplier - based on separation between classes
        variance_ratio = motion_variance / (static_variance + 1e-10)
        self.config['noise_multiplier'] = max(1.5, min(3.0, variance_ratio * 0.7))

        print(f"Static data mean variance: {static_variance:.6f}")
        print(f"Motion data mean variance: {motion_variance:.6f}")
        print(f"Set variance threshold: {variance_threshold:.6f}")
        print(f"Set diff threshold: {diff_threshold:.6f}")
        print(f"Set noise multiplier: {self.config['noise_multiplier']:.2f}")

        # Save calibration data
        calibration_data = {
            'base_threshold': self.base_threshold,
            'variance_threshold': variance_threshold,
            'diff_threshold': diff_threshold,
            'noise_multiplier': self.config['noise_multiplier'],
            'static_variance': static_variance,
            'motion_variance': motion_variance,
            'static_diff': static_diff,
            'motion_diff': motion_diff,
            'calibration_time': time.time()
        }
        self._save_calibration(calibration_data)

        return self.threshold

    # 修改 _calculate_subcarrier_coherence 方法，增加错误处理
    def _calculate_subcarrier_coherence(self, amplitude_data):
        """
        计算子载波之间的相关性/协同性

        参数:
        amplitude_data: 振幅数据，形状为[frames, subcarriers]

        返回:
        协同性分数 (0-1之间，1表示完全协同)
        """
        try:
            # 获取子载波数量
            n_frames, n_subcarriers = amplitude_data.shape

            if n_subcarriers < 2 or n_frames < 3:
                return 0.5  # 返回一个中等值，而不是0

            # 计算每个子载波的变化率
            changes = np.diff(amplitude_data, axis=0)

            # 1. 计算变化方向的一致性
            # 对每个时间点，检查不同子载波变化方向是否一致
            change_directions = np.sign(changes)

            # 对每个时间点计算方向一致性
            direction_agreement = []
            for t in range(changes.shape[0]):
                # 获取当前时间点所有子载波的变化方向
                directions = change_directions[t, :]
                # 计算正方向和负方向的数量
                pos_count = np.sum(directions > 0)
                neg_count = np.sum(directions < 0)
                # 取较大的一方，计算一致性比例
                max_agreement = max(pos_count, neg_count) / n_subcarriers if n_subcarriers > 0 else 0.5
                direction_agreement.append(max_agreement)

            # 取平均值作为方向一致性指标
            avg_direction_agreement = np.mean(direction_agreement) if direction_agreement else 0.5

            # 2. 计算变化幅度的相关性
            # 使用相关系数矩阵来量化不同子载波间的相关性
            # 添加错误处理，防止NaN
            try:
                correlation_matrix = np.corrcoef(changes.T)
                # 检查相关系数矩阵是否包含NaN值
                if np.any(np.isnan(correlation_matrix)):
                    avg_correlation = 0.5  # 如果有NaN，使用默认值
                else:
                    # 去除自相关(对角线)，计算平均相关系数
                    np.fill_diagonal(correlation_matrix, 0)
                    avg_correlation = np.mean(np.abs(correlation_matrix))
            except Exception as e:
                print(f"计算相关系数矩阵出错: {e}")
                avg_correlation = 0.5  # 出错时使用默认值

            # 综合得分 (可以调整权重)
            coherence_score = 0.6 * avg_direction_agreement + 0.4 * avg_correlation

            # 确保结果在0-1范围内
            coherence_score = max(0.0, min(1.0, coherence_score))

            return coherence_score

        except Exception as e:
            print(f"计算子载波协同性出错: {e}")
            return 0.5  # 出错时返回一个中等值

    # 修改 detect 方法中的逻辑判断部分
    def detect(self, csi_data):
        """
        基于子载波相似度的CSI运动检测

        参数:
        csi_data: CSI数据，形状为[frames, subcarriers, 2]

        返回:
        检测结果字典
        """
        # 1. 提取振幅
        real = csi_data[:, :, 0]
        imag = csi_data[:, :, 1]
        amplitude = np.sqrt(real ** 2 + imag ** 2)

        # 2. 选择最有变化的子载波
        variance_per_subcarrier = np.var(amplitude, axis=0)
        top_k = 5  # 选择变化最大的5个子载波
        top_subcarriers_idx = np.argsort(variance_per_subcarrier)[-top_k:]

        # 3. 提取这些子载波的数据
        selected_data = amplitude[:, top_subcarriers_idx]

        # 4. 计算相似度/重合度
        # 归一化处理，便于比较
        normalized_data = np.zeros_like(selected_data)
        for i in range(top_k):
            sc_data = selected_data[:, i]
            min_val = np.min(sc_data)
            max_val = np.max(sc_data)
            if max_val > min_val:  # 避免除零
                normalized_data[:, i] = (sc_data - min_val) / (max_val - min_val)
            else:
                normalized_data[:, i] = 0.5  # 设置默认值

        # 5. 计算子载波间的差异
        subcarrier_diffs = []
        for i in range(top_k):
            for j in range(i + 1, top_k):
                # 计算两个子载波的平均差异
                diff = np.mean(np.abs(normalized_data[:, i] - normalized_data[:, j]))
                subcarrier_diffs.append(diff)

        # 6. 计算平均差异（相似度的反向指标）
        if subcarrier_diffs:
            avg_diff = np.mean(subcarrier_diffs)
            similarity = 1.0 - avg_diff  # 转换为相似度，范围0-1
        else:
            similarity = 0.0

        # 7. 计算当前振幅方差作为辅助指标
        current_variance = np.mean(variance_per_subcarrier[top_subcarriers_idx])

        # 8. 基于相似度判断运动
        # 相似度高 + 方差大 = 运动
        is_motion = similarity > 0.75 and current_variance > self.threshold

        # 9. 添加状态平滑（可选）
        if hasattr(self, 'prev_state'):
            # 如果之前是运动状态，需要更低的相似度才会变为静止
            if self.prev_state and similarity > 0.6:
                is_motion = True
            # 如果之前是静止状态，需要更高的相似度才会变为运动
            elif not self.prev_state and similarity < 0.8:
                is_motion = False

        # 保存当前状态
        self.prev_state = is_motion

        # 返回结果
        return {
            'motion_detected': is_motion,
            'features': {
                'amp_variance_mean': current_variance,
                'subcarrier_similarity': similarity,
            },
            'threshold': self.threshold,
            'coherence': similarity
        }