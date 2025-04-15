import os
import json
import argparse
import glob
import time
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

from data_loader import CSIDataLoader
from breathing_estimator import BreathingEstimator
from evaluation import (evaluate_breathing_estimation, save_results,
                        visualize_results, visualize_all_results)


def ensure_dirs():
    """Ensure all necessary directories exist"""
    os.makedirs('results', exist_ok=True)
    os.makedirs('results/figures', exist_ok=True)


def load_config(config_path='config.json'):
    """Load configuration file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config file: {e}")
        return {}


def align_predictions_with_ground_truth(predictions, pred_times, gt_values, gt_times):
    """
    Align predictions with ground truth

    Returns:
    aligned_predictions, aligned_ground_truth, aligned_gt_times
    """
    # Ensure inputs are valid - use proper array checking
    if (predictions is None or len(predictions) == 0 or
            pred_times is None or len(pred_times) == 0 or
            gt_values is None or len(gt_values) == 0 or
            gt_times is None or len(gt_times) == 0):
        return [], [], []

    # Convert to pandas Series for easier operations
    try:
        pred_series = pd.Series(predictions, index=pd.to_datetime(pred_times))
        gt_series = pd.Series(gt_values, index=pd.to_datetime(gt_times))
    except Exception as e:
        print(f"Time conversion error: {e}")
        # If time conversion fails, try using indices as times
        pred_series = pd.Series(predictions)
        gt_series = pd.Series(gt_values)
        return predictions[:min(len(predictions), len(gt_values))], gt_values[
                                                                    :min(len(predictions), len(gt_values))], []

    # Find common time range
    start_time = max(pred_series.index.min(), gt_series.index.min())
    end_time = min(pred_series.index.max(), gt_series.index.max())

    # If no overlap, return empty lists
    if start_time > end_time:
        return [], [], []

    # Align to same time points (using ground truth time points)
    gt_in_range = gt_series[(gt_series.index >= start_time) & (gt_series.index <= end_time)]

    # Resample predictions to match ground truth time points
    aligned_predictions = []
    aligned_gt_times = []

    for time_idx in gt_in_range.index:
        # Find closest prediction time point
        closest_pred_idx = np.argmin(np.abs([(t - time_idx).total_seconds()
                                             if hasattr(t, 'total_seconds') else 0
                                             for t in pred_series.index]))
        aligned_predictions.append(pred_series.iloc[closest_pred_idx])
        aligned_gt_times.append(time_idx)

    return aligned_predictions, gt_in_range.values.tolist(), aligned_gt_times


def main():
    """Main function"""
    # Ensure directories exist
    ensure_dirs()

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='CSI Breathing Rate Estimation System')
    parser.add_argument('--config', type=str, default='config.json', help='Path to config file')
    parser.add_argument('--mode', choices=['predict', 'evaluate', 'visualize'], default='evaluate',
                        help='Run mode: predict=prediction, evaluate=evaluation, visualize=visualization')
    parser.add_argument('--input', type=str, help='Input file or directory')
    parser.add_argument('--visualize', action='store_true', help='Show result visualization')
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Create data loader
    data_loader = CSIDataLoader()

    # Create breathing rate estimator
    estimator = BreathingEstimator(config.get('breathing_estimator', {}))

    # Prediction mode - process single file
    if args.mode == 'predict':
        print("=== Prediction Mode ===")

        if not args.input:
            print("Error: Prediction mode requires input file (--input)")
            return

        # Load and process file
        data = data_loader.load_file(args.input)
        if not data:
            print(f"Failed to load file: {args.input}")
            return

        # Estimate breathing rate
        start_time = time.time()
        result = estimator.estimate_breathing_rate(data['csi_data'], data.get('timestamps'))
        processing_time = time.time() - start_time

        # Print results
        print(f"File: {data['filename']}")
        print(f"Processing time: {processing_time * 1000:.2f}ms")
        print(f"Estimated breathing rate: {np.mean(result['breathing_rates']):.1f} BPM (average)")
        print(f"Breathing rate range: {min(result['breathing_rates']):.1f} - {max(result['breathing_rates']):.1f} BPM")

        # Prepare result data
        result_data = {
            'filename': data['filename'],
            'predictions': result['breathing_rates'],
            'pred_timestamps': result['timestamps'],
            'window_size': result['window_size'],
            'step_size': result['step_size'],
            'processing_time': processing_time
        }

        # If ground truth is available, calculate MAE
        if 'gt_breathing_rates' in data:
            gt_bpm = data['gt_breathing_rates']['bpm']
            gt_timestamps = data['gt_breathing_rates']['timestamp']

            # Add diagnostic logging here
            print(f"  Found {len(result['breathing_rates'])} estimated breathing rates")
            print(f"  Found {len(gt_bpm)} ground truth values")

            # Align predictions and ground truth
            aligned_pred, aligned_gt, aligned_times = align_predictions_with_ground_truth(
                result['breathing_rates'], result['timestamps'],
                gt_bpm, gt_timestamps
            )

            # Check if gt data exists
            if gt_bpm is not None and len(gt_bpm) > 0:
                # Align predictions and ground truth
                aligned_pred, aligned_gt, aligned_times = align_predictions_with_ground_truth(
                    result['breathing_rates'], result['timestamps'],
                    gt_bpm, gt_timestamps
                )

                if aligned_pred and aligned_gt:
                    mae = np.mean(np.abs(np.array(aligned_pred) - np.array(aligned_gt)))
                    print(f"Mean Absolute Error (MAE): {mae:.2f} BPM")

                    # Add ground truth to result
                    result_data.update({
                        'ground_truth': aligned_gt,
                        'gt_timestamps': aligned_times,
                        'mae': mae
                    })
                else:
                    print("Warning: Could not align predictions with ground truth - no overlapping time period")
            else:
                print("Warning: Ground truth data is empty")

        # Save result
        results_dir = config['data_paths'].get('results_dir', 'results')
        os.makedirs(results_dir, exist_ok=True)
        save_results([result_data], os.path.join(results_dir, 'prediction_result.json'))

        # Visualize result
        if args.visualize:
            # Add processed signal data for visualization
            preprocessed = estimator.preprocess(data['csi_data'])
            result_data['filtered_signal'] = preprocessed['filtered_amplitude'].mean(axis=1)

            visualize_results(result_data, show_raw_signal=True)

    # Evaluation mode - process evaluation dataset
    elif args.mode == 'evaluate':
        print("=== Evaluation Mode ===")

        # Load evaluation data
        eval_dir = args.input if args.input else config['data_paths']['evaluation_dir']
        print(f"Loading evaluation data: {eval_dir}")

        # Load all CSV files
        all_data = data_loader.load_directory(eval_dir)

        if not all_data:
            print(f"No valid CSV files found in {eval_dir}")
            return

        # Process each file
        all_results = []
        processing_times = []

        for data in all_data:
            print(f"Processing file: {data['filename']}")

            # Estimate breathing rate
            start_time = time.time()
            result = estimator.estimate_breathing_rate(data['csi_data'], data.get('timestamps'))
            processing_time = time.time() - start_time
            processing_times.append(processing_time)

            # Prepare result data
            result_data = {
                'filename': data['filename'],
                'predictions': result['breathing_rates'],
                'pred_timestamps': result['timestamps'],
                'window_size': result['window_size'],
                'step_size': result['step_size'],
                'processing_time': processing_time
            }

            # If ground truth is available, calculate MAE
            if 'gt_breathing_rates' in data:
                gt_bpm = data['gt_breathing_rates']['bpm']
                gt_timestamps = data['gt_breathing_rates']['timestamp']

                # Add diagnostic logging here
                print(f"  Found {len(result['breathing_rates'])} estimated breathing rates")
                print(f"  Found {len(gt_bpm)} ground truth values")


                # Align predictions and ground truth
                aligned_pred, aligned_gt, aligned_times = align_predictions_with_ground_truth(
                    result['breathing_rates'], result['timestamps'],
                    gt_bpm, gt_timestamps
                )

                if aligned_pred and aligned_gt:
                    result_data.update({
                        'ground_truth': aligned_gt,
                        'gt_timestamps': aligned_times
                    })

            # Add processed signal data for visualization
            preprocessed = estimator.preprocess(data['csi_data'])
            result_data['filtered_signal'] = preprocessed['filtered_amplitude'].mean(axis=1)

            all_results.append(result_data)

            # Print progress
            avg_br = np.mean(result['breathing_rates'])
            print(f"  Average breathing rate: {avg_br:.1f} BPM")
            print(f"  Processing time: {processing_time * 1000:.2f}ms")

        # Calculate processing time statistics
        avg_time = np.mean(processing_times) * 1000  # Convert to milliseconds
        print(f"\nProcessing complete, {len(all_results)} files processed")
        print(f"Average processing time: {avg_time:.2f}ms")

        # Evaluate performance
        metrics = evaluate_breathing_estimation(all_results)

        if metrics:
            print("\nEvaluation Results:")
            print(f"Overall MAE: {metrics.get('overall_mae', 'N/A'):.2f} BPM")
            print(f"Median MAE: {metrics.get('median_mae', 'N/A'):.2f} BPM")
            print(f"Sample count: {metrics.get('sample_count', 'N/A')}")

        # Save results
        results_dir = config['data_paths'].get('results_dir', 'results')
        os.makedirs(results_dir, exist_ok=True)
        save_results(all_results, os.path.join(results_dir, 'test_results.json'))

        # Save evaluation metrics
        with open(os.path.join(results_dir, 'evaluation_metrics.json'), 'w') as f:
            json.dump(metrics, f, indent=2)

        # Visualize results
        if args.visualize:
            for result in all_results:
                visualize_results(result, show_raw_signal=False)

            # Visualize overall results
            visualize_all_results(all_results, metrics)

    # Visualization mode - load and display existing results
    elif args.mode == 'visualize':
        print("=== Visualization Mode ===")

        # Load specified input file
        if args.input and os.path.isfile(args.input):
            try:
                with open(args.input, 'r') as f:
                    results = json.load(f)

                # Load evaluation metrics
                metrics_file = os.path.join(os.path.dirname(args.input), 'evaluation_metrics.json')
                metrics = None
                if os.path.exists(metrics_file):
                    with open(metrics_file, 'r') as f:
                        metrics = json.load(f)

                print(f"Loaded {len(results)} result records")

                # Show results for each file
                for result in results:
                    visualize_results(result, show_raw_signal=False)

                # Show overall results
                visualize_all_results(results, metrics)

            except Exception as e:
                print(f"Failed to load results file: {e}")
        else:
            print("Error: Visualization mode requires input results file (--input)")

    else:
        print(f"Error: Unknown mode {args.mode}")


if __name__ == "__main__":
    main()