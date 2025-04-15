import numpy as np
from scipy import signal
import time


class BreathingEstimator:
    """Breathing rate estimator class"""

    def __init__(self, config=None):
        """
        Initialize breathing rate estimator

        Parameters:
        config: Configuration dictionary, default to None
        """
        # Default configuration
        self.config = {
            'window_size': 1500,  # 15 seconds * 100Hz
            'overlap': 0.5,  # 50% overlap
            'bandpass_filter': {
                'low_cut': 0.1,  # Hz
                'high_cut': 0.6,  # Hz
                'order': 4  # Filter order
            },
            'fft_method': {
                'enabled': True,
                'padding_ratio': 4  # FFT padding ratio
            },
            'subcarrier_selection': {
                'method': 'variance',  # 'variance', 'pca', 'all'
                'top_n': 5  # Number of subcarriers to select
            },
            'smoothing': {
                'enabled': True,
                'window_size': 3  # Smoothing window size
            }
        }

        # Update configuration
        if config:
            for key, value in config.items():
                if isinstance(value, dict) and key in self.config:
                    self.config[key].update(value)
                else:
                    self.config[key] = value

    def preprocess(self, csi_data):
        """
        Preprocess CSI data

        Parameters:
        csi_data: Raw CSI data [sample, subcarrier, real/imag]

        Returns:
        Processed data
        """
        # Extract real and imaginary parts
        real = csi_data[:, :, 0]  # All samples, all subcarriers, real part
        imag = csi_data[:, :, 1]  # All samples, all subcarriers, imaginary part

        # Calculate amplitude and phase
        amplitude = np.sqrt(real ** 2 + imag ** 2)
        phase = np.unwrap(np.arctan2(imag, real), axis=0)

        # Remove phase linear trend
        detrended_phase = self._detrend_phase(phase)

        # Select best subcarriers
        selected_amp, selected_indices = self._select_subcarriers(amplitude)

        # Apply bandpass filter
        filtered_amp = self._apply_bandpass_filter(selected_amp)

        return {
            'amplitude': amplitude,
            'phase': phase,
            'detrended_phase': detrended_phase,
            'selected_indices': selected_indices,
            'selected_amplitude': selected_amp,
            'filtered_amplitude': filtered_amp
        }

    def _detrend_phase(self, phase):
        """
        Remove linear trend from phase data

        Parameters:
        phase: Phase data [sample, subcarrier]

        Returns:
        Detrended phase
        """
        detrended = np.zeros_like(phase)
        for i in range(phase.shape[1]):
            detrended[:, i] = signal.detrend(phase[:, i])
        return detrended

    def _select_subcarriers(self, amplitude):
        """
        Select best subcarriers

        Parameters:
        amplitude: Amplitude data [sample, subcarrier]

        Returns:
        Selected subcarrier amplitudes and indices
        """
        method = self.config['subcarrier_selection']['method']
        top_n = self.config['subcarrier_selection']['top_n']

        if method == 'variance':
            # Select subcarriers based on variance
            var_per_subcarrier = np.var(amplitude, axis=0)
            top_indices = np.argsort(var_per_subcarrier)[-top_n:]
            selected_amp = amplitude[:, top_indices]
            return selected_amp, top_indices
        elif method == 'pca':
            # Simplified PCA method - take average as principal component
            selected_amp = np.mean(amplitude, axis=1, keepdims=True)
            return selected_amp, None
        else:  # 'all'
            return amplitude, np.arange(amplitude.shape[1])

    def _apply_bandpass_filter(self, data):
        """
        Apply bandpass filter

        Parameters:
        data: Input data [sample, subcarrier]

        Returns:
        Filtered data
        """
        # Get filter parameters
        low_cut = self.config['bandpass_filter']['low_cut']
        high_cut = self.config['bandpass_filter']['high_cut']
        order = self.config['bandpass_filter']['order']

        # Assume 100Hz sampling rate
        fs = 100.0

        # Design filter
        nyq = 0.5 * fs
        low = low_cut / nyq
        high = high_cut / nyq
        b, a = signal.butter(order, [low, high], btype='band')

        # Apply filter
        filtered_data = np.zeros_like(data)
        for i in range(data.shape[1]):
            filtered_data[:, i] = signal.filtfilt(b, a, data[:, i])

        return filtered_data

    def estimate_breathing_rate(self, csi_data, timestamps=None):
        """
        Estimate breathing rate

        Parameters:
        csi_data: CSI data [sample, subcarrier, real/imag]
        timestamps: Corresponding timestamps

        Returns:
        Estimated breathing rate results
        """
        # Preprocess data
        preprocessed = self.preprocess(csi_data)

        # Extract filtered amplitude data
        filtered_amp = preprocessed['filtered_amplitude']

        # Get window parameters
        window_size = min(self.config['window_size'], filtered_amp.shape[0])
        overlap = self.config['overlap']
        step_size = max(1, int(window_size * (1 - overlap)))

        # Store results
        breathing_rates = []
        window_times = []

        # Process each window
        for start_idx in range(0, filtered_amp.shape[0] - window_size + 1, step_size):
            # Extract window data
            end_idx = start_idx + window_size
            window_data = filtered_amp[start_idx:end_idx, :]

            # Analyze breathing rate using FFT
            if self.config['fft_method']['enabled']:
                br = self._estimate_with_fft(window_data)
            else:
                # Alternative: peak detection method
                br = self._estimate_with_peak_detection(window_data)

            # Add results
            breathing_rates.append(br)

            # Use timestamp if available
            if timestamps is not None and len(timestamps) > end_idx:
                window_times.append(timestamps[start_idx + window_size // 2])
            else:
                window_times.append(start_idx / 100)  # Assume 100Hz sampling rate

        # Smooth breathing rate results
        if self.config['smoothing']['enabled'] and len(breathing_rates) > 1:
            breathing_rates = self._smooth_results(breathing_rates)

        # Round to integer BPM
        breathing_rates = [round(br) for br in breathing_rates]

        return {
            'breathing_rates': breathing_rates,
            'timestamps': window_times,
            'window_size': window_size,
            'step_size': step_size,
            'selected_subcarriers': preprocessed['selected_indices']
        }

    def _estimate_with_fft(self, window_data):
        """
        Estimate breathing rate using FFT

        Parameters:
        window_data: Window data [window_size, n_subcarriers]

        Returns:
        Breathing rate (BPM)
        """
        # Combine data from all subcarriers
        combined_signal = np.mean(window_data, axis=1)

        # Apply window function to reduce spectral leakage
        windowed_signal = combined_signal * signal.windows.hann(len(combined_signal))

        # Calculate FFT
        n_samples = len(windowed_signal)
        padding_ratio = self.config['fft_method']['padding_ratio']
        nfft = n_samples * padding_ratio

        # Perform FFT
        fft_result = np.abs(np.fft.rfft(windowed_signal, n=nfft))
        freqs = np.fft.rfftfreq(nfft, d=1 / 100)  # Assume 100Hz sampling rate

        # Find peak in breathing frequency range
        min_freq = self.config['bandpass_filter']['low_cut']
        max_freq = self.config['bandpass_filter']['high_cut']
        valid_range = (freqs >= min_freq) & (freqs <= max_freq)

        # Find peak in valid range
        if np.any(valid_range):
            peak_idx = np.argmax(fft_result[valid_range])
            breathing_freq = freqs[valid_range][peak_idx]

            # Convert to breaths per minute (BPM)
            breathing_rate = breathing_freq * 60
        else:
            # Default value if no valid range is found
            breathing_rate = 15.0

        return breathing_rate

    def _estimate_with_peak_detection(self, window_data):
        """
        Estimate breathing rate using peak detection

        Parameters:
        window_data: Window data [window_size, n_subcarriers]

        Returns:
        Breathing rate (BPM)
        """
        # Combine data from all subcarriers
        combined_signal = np.mean(window_data, axis=1)

        # Detect peaks
        peaks, _ = signal.find_peaks(combined_signal, distance=20)  # Minimum distance ~0.2 seconds

        if len(peaks) < 2:
            # If too few peaks detected, return default value
            return 15.0  # Default breathing rate

        # Calculate average peak interval
        peak_intervals = np.diff(peaks)
        avg_interval_samples = np.mean(peak_intervals)

        # Convert to seconds (assuming 100Hz sampling rate)
        avg_interval_seconds = avg_interval_samples / 100

        # Calculate BPM
        breathing_rate = 60 / avg_interval_seconds

        # Ensure result is in reasonable range
        if breathing_rate < 6 or breathing_rate > 30:
            return 15.0  # Default breathing rate

        return breathing_rate

    def _smooth_results(self, breathing_rates):
        """
        Smooth breathing rate results

        Parameters:
        breathing_rates: List of breathing rates

        Returns:
        Smoothed breathing rates
        """
        window_size = self.config['smoothing']['window_size']

        if len(breathing_rates) < window_size:
            return breathing_rates

        # Use moving average for smoothing
        smoothed = np.convolve(breathing_rates,
                               np.ones(window_size) / window_size,
                               mode='valid')

        # Handle edges
        pad_size = len(breathing_rates) - len(smoothed)
        if pad_size > 0:
            pad_left = pad_size // 2
            pad_right = pad_size - pad_left
            smoothed = np.pad(smoothed, (pad_left, pad_right), 'edge')

        return smoothed.tolist()