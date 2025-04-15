import numpy as np
import json
import os
import matplotlib.pyplot as plt
import pandas as pd


def calculate_mae(predictions, ground_truth):
    """
    Calculate Mean Absolute Error (MAE)

    Parameters:
    predictions: Predicted breathing rates
    ground_truth: Actual breathing rates

    Returns:
    MAE value
    """
    if len(predictions) != len(ground_truth):
        raise ValueError("Predictions and ground truth lengths do not match")

    absolute_errors = np.abs(np.array(predictions) - np.array(ground_truth))
    return np.mean(absolute_errors)


def evaluate_breathing_estimation(results):
    """
    Evaluate breathing rate estimation performance

    Parameters:
    results: List of results containing predictions and ground truth

    Returns:
    Dictionary of evaluation metrics
    """
    all_maes = []
    overall_predictions = []
    overall_ground_truth = []

    for result in results:
        if 'predictions' in result and 'ground_truth' in result:
            pred = result['predictions']
            gt = result['ground_truth']

            # Ensure matching lengths by truncating longer sequence
            min_len = min(len(pred), len(gt))
            pred = pred[:min_len]
            gt = gt[:min_len]

            # Calculate MAE
            if min_len > 0:
                mae = calculate_mae(pred, gt)
                all_maes.append(mae)

                # Accumulate all predictions and ground truth
                overall_predictions.extend(pred)
                overall_ground_truth.extend(gt)

                # Add MAE to result
                result['mae'] = mae

    # Calculate overall evaluation metrics
    results_summary = {}

    if all_maes:
        results_summary['mean_mae'] = np.mean(all_maes)
        results_summary['median_mae'] = np.median(all_maes)
        results_summary['max_mae'] = np.max(all_maes)
        results_summary['min_mae'] = np.min(all_maes)

    if overall_predictions and overall_ground_truth:
        results_summary['overall_mae'] = calculate_mae(overall_predictions, overall_ground_truth)
        results_summary['sample_count'] = len(overall_predictions)

    return results_summary


def save_results(results, file_path):
    """
    Save estimation results to file

    Parameters:
    results: Results list
    file_path: Output file path
    """
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Convert numpy types for JSON serialization
        def convert_for_json(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (np.int_, np.intc, np.intp, np.int8, np.int16, np.int32, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
                return float(obj)
            elif isinstance(obj, (np.datetime64, pd._libs.tslibs.timestamps.Timestamp)):
                return str(obj)  # Convert datetime to string
            elif isinstance(obj, dict):
                return {k: convert_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_for_json(i) for i in obj]
            elif hasattr(obj, 'isoformat'):  # Handle datetime objects
                return obj.isoformat()
            else:
                return obj

        serializable_results = convert_for_json(results)

        with open(file_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)

        print(f"Results saved to: {file_path}")

    except Exception as e:
        print(f"Error saving results: {e}")


def visualize_results(result, show_raw_signal=False):
    """
    Visualize breathing rate estimation results

    Parameters:
    result: Result dictionary for a single file
    show_raw_signal: Whether to show raw signal
    """
    plt.figure(figsize=(12, 8))

    # Extract data
    filename = result.get('filename', 'Unknown')
    predictions = result.get('predictions', [])
    pred_times = result.get('pred_timestamps', [])
    gt_values = result.get('ground_truth', [])
    gt_times = result.get('gt_timestamps', [])
    mae = result.get('mae', None)

    # Convert timestamps to datetime objects (if they are strings)
    if pred_times and isinstance(pred_times[0], str):
        pred_times = [pd.to_datetime(t) for t in pred_times]
    if gt_times and isinstance(gt_times[0], str):
        gt_times = [pd.to_datetime(t) for t in gt_times]

    # Ensure ground truth times and values have matching lengths
    if gt_times and gt_values and len(gt_times) != len(gt_values):
        # Truncate to same length
        min_len = min(len(gt_times), len(gt_values))
        gt_times = gt_times[:min_len]
        gt_values = gt_values[:min_len]
        print(f"Warning: Ground truth times and values length mismatch, truncated to {min_len} entries")

    # Plot main figure - breathing rate
    plt.subplot(2, 1, 1)

    # Plot predictions
    if predictions and pred_times:
        plt.plot(pred_times, predictions, 'b-', marker='o', markersize=4, label='Estimated BPM')

    # Plot ground truth (if available and lengths match)
    if gt_values and gt_times and len(gt_values) == len(gt_times) and len(gt_values) > 0:
        plt.plot(gt_times, gt_values, 'r-', label='Ground Truth BPM')
    elif gt_values and len(gt_values) > 0:
        # If no matching timestamps, use indices for x-axis
        plt.plot(range(len(gt_values)), gt_values, 'r-', label='Ground Truth BPM')

    plt.title(f'Breathing Rate Estimation - {filename}')
    plt.ylabel('Breathing Rate (BPM)')

    if mae is not None:
        plt.text(0.02, 0.95, f'MAE: {mae:.2f} BPM', transform=plt.gca().transAxes,
                 bbox=dict(facecolor='white', alpha=0.5))

    plt.grid(True)
    plt.legend()

    # Plot raw signal (if requested)
    if show_raw_signal and 'filtered_signal' in result:
        plt.subplot(2, 1, 2)
        signal_data = result['filtered_signal']
        time_points = np.arange(len(signal_data)) / 100  # Assume 100Hz
        plt.plot(time_points, signal_data, 'g-')
        plt.title('Filtered CSI Signal')
        plt.xlabel('Time (s)')
        plt.ylabel('Amplitude')
        plt.grid(True)

    plt.tight_layout()

    # Save image
    if 'filename' in result:
        output_dir = 'results/figures'
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"breathing_rate_{result['filename'].replace('.csv', '')}.png")
        plt.savefig(output_file)
        print(f"Image saved to: {output_file}")

    plt.show()


def visualize_all_results(results, metrics=None):
    """
    Visualize evaluation results for all files

    Parameters:
    results: Results list
    metrics: Evaluation metrics
    """
    # Plot MAE comparison chart
    if len(results) > 1:
        plt.figure(figsize=(10, 6))

        filenames = [r.get('filename', f'File {i}') for i, r in enumerate(results)]
        maes = [r.get('mae', 0) for r in results]

        plt.bar(range(len(filenames)), maes)
        plt.xticks(range(len(filenames)), [os.path.basename(f).replace('.csv', '') for f in filenames], rotation=45)
        plt.xlabel('File')
        plt.ylabel('MAE (BPM)')
        plt.title('Breathing Rate Estimation Error by File')
        plt.grid(True, axis='y')

        # Add average MAE line
        if metrics and 'median_mae' in metrics:
            plt.axhline(y=metrics['median_mae'], color='r', linestyle='--',
                        label=f'Median MAE: {metrics["median_mae"]:.2f}')
            plt.legend()

        plt.tight_layout()

        # Save image
        output_dir = 'results/figures'
        os.makedirs(output_dir, exist_ok=True)
        plt.savefig(os.path.join(output_dir, 'mae_comparison.png'))

        plt.show()

    # Display overall metrics
    if metrics:
        plt.figure(figsize=(6, 4))
        plt.axis('off')

        info_text = (
            f"Breathing Rate Estimation Performance\n"
            f"----------------------------------\n"
            f"Number of samples: {metrics.get('sample_count', 'N/A')}\n"
            f"Overall MAE: {metrics.get('overall_mae', 'N/A'):.2f} BPM\n"
            f"Mean MAE: {metrics.get('mean_mae', 'N/A'):.2f} BPM\n"
            f"Median MAE: {metrics.get('median_mae', 'N/A'):.2f} BPM\n"
            f"Min MAE: {metrics.get('min_mae', 'N/A'):.2f} BPM\n"
            f"Max MAE: {metrics.get('max_mae', 'N/A'):.2f} BPM\n"
        )

        plt.text(0.1, 0.5, info_text, fontsize=12, family='monospace')
        plt.tight_layout()

        # Save image
        output_dir = 'results/figures'
        os.makedirs(output_dir, exist_ok=True)
        plt.savefig(os.path.join(output_dir, 'performance_summary.png'))

        plt.show()