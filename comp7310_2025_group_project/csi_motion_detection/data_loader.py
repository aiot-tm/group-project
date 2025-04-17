import os
import pandas as pd
import numpy as np
import re
import glob


class CSIDataLoader:
    """CSI数据加载器类"""

    def __init__(self, config=None):
        """
        初始化CSI数据加载器

        参数:
        config: 配置字典，如果为None则使用默认配置
        """
        self.config = config or {}
        self.data_cache = {}  # Data cache for loaded files

    def load_file(self, file_path, label=None):
        """
        加载单个CSI文件

        参数:
        file_path: CSV文件路径
        label: 可选标签(0=静止, 1=运动)

        返回:
        解析后的CSI数据字典
        """
        # Return cached data if available
        if file_path in self.data_cache:
            return self.data_cache[file_path]

        try:
            # Load CSV file
            df = pd.read_csv(file_path)

            # Extract CSI data
            csi_data = self._extract_csi_data(df)

            # Return None if no valid data
            if csi_data.size == 0:
                print(f"Warning: No valid CSI data extracted from {file_path}")
                return None

            # Create result dictionary
            result = {
                'file_path': file_path,
                'filename': os.path.basename(file_path),
                'csi_data': csi_data,
                'label': label,
                'n_samples': csi_data.shape[0],
                'n_subcarriers': csi_data.shape[1] if csi_data.ndim > 1 else 0
            }

            # Cache the result
            self.data_cache[file_path] = result

            return result

        except Exception as e:
            print(f"Error loading file {file_path}: {e}")
            return None

    def load_directory(self, dir_path, label=None, file_pattern='*.csv'):
        """
        加载目录中的所有CSV文件

        参数:
        dir_path: 目录路径
        label: 可选标签(0=静止, 1=运动)
        file_pattern: 文件匹配模式

        返回:
        成功加载的文件列表
        """
        # Get matching files
        file_paths = glob.glob(os.path.join(dir_path, file_pattern))

        if not file_paths:
            print(f"Warning: No files matching {file_pattern} found in {dir_path}")
            return []

        # Load each file
        loaded_files = []
        for file_path in file_paths:
            data = self.load_file(file_path, label)
            if data:
                loaded_files.append(data)

        print(f"Loaded {len(loaded_files)}/{len(file_paths)} files from directory {dir_path}")

        return loaded_files

    # def _extract_csi_data(self, df):
    #     """
    #     从DataFrame中提取CSI数据
    #
    #     参数:
    #     df: 包含CSI数据的DataFrame
    #
    #     返回:
    #     3D numpy数组: [sample, subcarrier, real/imag]
    #     """
    #     csi_data_list = []
    #     expected_length = None
    #
    #     for i, row in df.iterrows():
    #         # Check 'data' column exists
    #         if 'data' not in row:
    #             continue
    #
    #         # Parse CSI data string
    #         data_str = row['data']
    #
    #         # Extract data with regex
    #         match = re.search(r'\[(.*)\]', data_str)
    #         if not match:
    #             continue
    #
    #         # Convert to numerical values
    #         try:
    #             values = [float(val) for val in match.group(1).split(',')]
    #         except ValueError:
    #             continue
    #
    #         # Ensure even number of values (real/imag pairs)
    #         if len(values) % 2 != 0:
    #             continue
    #
    #         # Set expected length
    #         if expected_length is None:
    #             expected_length = len(values)
    #
    #         # Skip data with wrong length
    #         if len(values) != expected_length:
    #             continue
    #
    #         # Reshape data to [subcarrier, real/imag] format
    #         n_subcarriers = len(values) // 2
    #         structured_data = np.zeros((n_subcarriers, 2))
    #
    #         for j in range(n_subcarriers):
    #             real_idx = j * 2
    #             imag_idx = j * 2 + 1
    #             structured_data[j, 0] = values[real_idx]  # Real part
    #             structured_data[j, 1] = values[imag_idx]  # Imaginary part
    #
    #         csi_data_list.append(structured_data)
    #
    #     # Check for valid data
    #     if not csi_data_list:
    #         return np.array([])
    #
    #     # Return 3D array: [sample, subcarrier, real/imag]
    #     return np.array(csi_data_list)
    def _extract_csi_data(self, df):
        """
        从DataFrame中提取CSI数据

        参数:
        df: 包含CSI数据的DataFrame

        返回:
        3D numpy数组: [sample, subcarrier, real/imag]
        """
        csi_data_list = []
        expected_length = None

        for i, row in df.iterrows():
            # Check 'data' column exists
            if 'data' not in row:
                continue

            # Parse CSI data string
            data_str = row['data']

            # 处理可能包含UIDS前缀的情况
            if "UIDS-" in data_str and "CSI_DATA" in data_str:
                uid_part, data_part = data_str.split(",CSI_DATA,", 1)
                data_str = "CSI_DATA," + data_part

            # Extract data with regex
            match = re.search(r'\[(.*)\]', data_str)
            if not match:
                continue

            # Convert to numerical values
            try:
                values = [float(val) for val in match.group(1).split(',')]
            except ValueError:
                continue

            # Ensure even number of values (real/imag pairs)
            if len(values) % 2 != 0:
                continue

            # Set expected length
            if expected_length is None:
                expected_length = len(values)

            # Skip data with wrong length
            if len(values) != expected_length:
                continue

            # Reshape data to [subcarrier, real/imag] format
            n_subcarriers = len(values) // 2
            structured_data = np.zeros((n_subcarriers, 2))

            for j in range(n_subcarriers):
                real_idx = j * 2
                imag_idx = j * 2 + 1
                structured_data[j, 0] = values[real_idx]  # Real part
                structured_data[j, 1] = values[imag_idx]  # Imaginary part

            csi_data_list.append(structured_data)

        # Check for valid data
        if not csi_data_list:
            return np.array([])

        # Return 3D array: [sample, subcarrier, real/imag]
        return np.array(csi_data_list)