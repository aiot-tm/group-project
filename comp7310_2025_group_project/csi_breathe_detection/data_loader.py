import os
import pandas as pd
import numpy as np
import re
import glob


class CSIDataLoader:
    """CSI data loader class"""

    def __init__(self, config=None):
        """
        Initialize CSI data loader

        Parameters:
        config: Configuration dictionary, default to None
        """
        self.config = config or {}
        self.data_cache = {}  # Data cache

    def load_file(self, file_path, gt_path=None):
        """
        Load a single CSI file and corresponding ground truth breathing rate

        Parameters:
        file_path: CSV file path
        gt_path: Ground truth file path, optional

        Returns:
        Parsed CSI data dictionary
        """
        # Return cached data if available
        if file_path in self.data_cache:
            return self.data_cache[file_path]

        try:
            # Load CSV file
            df = pd.read_csv(file_path)

            # Extract CSI data
            csi_data = self._extract_csi_data(df)
            timestamps = self._extract_timestamps(df)

            # Return None if no valid data
            if csi_data.size == 0:
                print(f"Warning: No valid CSI data extracted from {file_path}")
                return None

            # Create result dictionary
            result = {
                'file_path': file_path,
                'filename': os.path.basename(file_path),
                'csi_data': csi_data,
                'timestamps': timestamps,
                'n_samples': csi_data.shape[0],
                'n_subcarriers': csi_data.shape[1] if csi_data.ndim > 1 else 0
            }

            # Try to load ground truth data
            if gt_path and os.path.exists(gt_path):
                breathing_rates = self._load_ground_truth(gt_path)
                if breathing_rates:
                    result['gt_breathing_rates'] = breathing_rates
                    result['gt_file_path'] = gt_path

            # Cache result
            self.data_cache[file_path] = result

            return result

        except Exception as e:
            print(f"Error loading file {file_path}: {e}")
            return None

    def load_directory(self, dir_path, file_pattern='*.csv'):
        """
        Load all CSV files in a directory

        Parameters:
        dir_path: Directory path
        file_pattern: File matching pattern

        Returns:
        List of successfully loaded files
        """
        # Get matching files
        file_paths = glob.glob(os.path.join(dir_path, file_pattern))

        if not file_paths:
            print(f"Warning: No files matching {file_pattern} found in {dir_path}")
            return []

        # Separate CSI files and ground truth files
        csi_files = [f for f in file_paths if os.path.basename(f).startswith("CSI")]
        gt_files = [f for f in file_paths if os.path.basename(f).startswith("gt_")]

        # Create a mapping from CSI filename to GT filename
        gt_map = {}
        for gt_file in gt_files:
            gt_base = os.path.basename(gt_file)
            matching_csi = "CSI" + gt_base[3:]  # Remove "gt_" and add "CSI"
            gt_map[matching_csi] = gt_file

        # Load each CSI file with its corresponding ground truth
        loaded_files = []
        for file_path in csi_files:
            base_name = os.path.basename(file_path)
            gt_path = gt_map.get(base_name)

            data = self.load_file(file_path, gt_path)
            if data:
                loaded_files.append(data)

        print(f"Loaded {len(loaded_files)}/{len(csi_files)} files from directory {dir_path}")
        return loaded_files

    def _extract_csi_data(self, df):
        """
        Extract CSI data from DataFrame

        Parameters:
        df: DataFrame containing CSI data

        Returns:
        3D numpy array: [sample, subcarrier, real/imag]
        """
        csi_data_list = []
        expected_length = None

        for i, row in df.iterrows():
            # Check if 'data' column exists
            if 'data' not in row:
                continue

            # Parse CSI data string
            data_str = row['data']

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

    def _extract_timestamps(self, df):
        """
        Extract timestamps from DataFrame

        Parameters:
        df: DataFrame containing timestamps

        Returns:
        List of timestamps
        """
        if 'timestamp' in df.columns:
            return df['timestamp'].tolist()
        return []

    def _load_ground_truth(self, gt_path):
        """
        Load ground truth breathing rate data

        Parameters:
        gt_path: Ground truth file path

        Returns:
        Dictionary of breathing rates and timestamps
        """
        try:
            gt_df = pd.read_csv(gt_path)

            # Check common column name formats
            if 'bpm' in gt_df.columns and 'time' in gt_df.columns:
                gt_df['time'] = pd.to_datetime(gt_df['time'])
                return {
                    'bpm': gt_df['bpm'].values,
                    'timestamp': gt_df['time'].values
                }
            elif 'BPM' in gt_df.columns and 'timestamp' in gt_df.columns:
                gt_df['timestamp'] = pd.to_datetime(gt_df['timestamp'])
                return {
                    'bpm': gt_df['BPM'].values,
                    'timestamp': gt_df['timestamp'].values
                }
            elif 'value' in gt_df.columns and 'timestamp' in gt_df.columns:
                gt_df['timestamp'] = pd.to_datetime(gt_df['timestamp'])
                return {
                    'bpm': gt_df['value'].values,
                    'timestamp': gt_df['timestamp'].values
                }
            else:
                # If no standard column names, try using the first two columns
                gt_df.columns = ['timestamp', 'bpm'] + list(gt_df.columns[2:])
                gt_df['timestamp'] = pd.to_datetime(gt_df['timestamp'])
                return {
                    'bpm': gt_df['bpm'].values,
                    'timestamp': gt_df['timestamp'].values
                }
        except Exception as e:
            print(f"Error loading ground truth file {gt_path}: {e}")

        return None