import os
import json
import argparse
import glob
import time
import numpy as np
import matplotlib.pyplot as plt

from data_loader import CSIDataLoader
from motion_detector import MotionDetector
from evaluation import evaluate_detection_performance, save_results, visualize_results


def load_config(config_path='config.json'):
    """Load configuration file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config file: {e}")
        return {}


def main():
    """Main function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='CSI Motion Detection System')
    parser.add_argument('--config', type=str, default='config.json', help='Path to config file')
    parser.add_argument('--mode', choices=['train', 'test', 'evaluate', 'visualize'], default='evaluate',
                        help='Run mode: train=training, test=testing, evaluate=evaluation, visualize=visualization')
    parser.add_argument('--input', type=str, help='Input file or directory')
    parser.add_argument('--visualize', action='store_true', help='Show visualization of results')
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Create data loader
    data_loader = CSIDataLoader()

    # Create motion detector
    detector = MotionDetector(config.get('motion_detector', {}))

    # Training mode - calibrate detector
    if args.mode == 'train':
        print("=== Training Mode ===")

        # Load training data
        motion_dir = config['data_paths']['motion_dir']
        static_dir = config['data_paths']['static_dir']

        print(f"Loading static data: {static_dir}")
        static_data = data_loader.load_directory(static_dir, label=0)

        print(f"Loading motion data: {motion_dir}")
        motion_data = data_loader.load_directory(motion_dir, label=1)

        # Calibrate detector
        detector.calibrate(static_data, motion_data)

        # Evaluate training performance
        all_results = []

        # Process static data
        for data in static_data:
            result = detector.detect(data['csi_data'])
            all_results.append({
                'filename': data['filename'],
                'true_label': 0,
                'predicted': result['motion_detected'],
                'features': result['features'],
                'threshold': result['threshold']
            })

        # Process motion data
        for data in motion_data:
            result = detector.detect(data['csi_data'])
            all_results.append({
                'filename': data['filename'],
                'true_label': 1,
                'predicted': result['motion_detected'],
                'features': result['features'],
                'threshold': result['threshold']
            })

        # Evaluate performance
        metrics = evaluate_detection_performance(all_results)

        # Print performance metrics
        print("\nTraining Evaluation Results:")
        print(f"Accuracy: {metrics['accuracy']:.2f}%")
        print(f"Precision: {metrics['precision']:.2f}%")
        print(f"Recall: {metrics['recall']:.2f}%")
        print(f"F1 Score: {metrics['f1_score']:.2f}%")
        print(f"Confusion Matrix: {metrics['confusion_matrix']}")

        # Show visualization if requested
        if args.visualize:
            visualize_results(all_results, metrics, show_features=True)

        # Save results
        results_dir = config['data_paths'].get('results_dir', 'results')
        os.makedirs(results_dir, exist_ok=True)
        save_results(all_results, os.path.join(results_dir, 'training_results.json'))

    # Test mode - process single file
    elif args.mode == 'test':
        print("=== Testing Mode ===")

        if not args.input:
            print("Error: Testing mode requires input file (--input)")
            return

        # Load and process file
        data = data_loader.load_file(args.input)
        if not data:
            print(f"Failed to load file: {args.input}")
            return

        # Detect motion
        start_time = time.time()
        result = detector.detect(data['csi_data'])
        processing_time = time.time() - start_time

        # Print results
        motion_status = "Motion detected" if result['motion_detected'] else "No motion detected"
        print(f"Result: {motion_status}")
        print(f"File: {data['filename']}")
        print(f"Processing time: {processing_time * 1000:.2f}ms")
        print(f"Amplitude variance: {result['features']['amp_variance_mean']:.6f}")
        print(f"Threshold: {result['threshold']:.6f}")
        print(f"Noise level: {result['noise_level']:.6f}")

        # Compare with label if available
        if data.get('label') is not None:
            true_label = "Motion" if data['label'] == 1 else "Static"
            is_correct = result['motion_detected'] == data['label']
            print(f"True label: {true_label}")
            print(f"Prediction {'correct' if is_correct else 'incorrect'}")

        # Show visualization if requested
        if args.visualize:
            # Prepare single result for visualization
            result_data = [{
                'filename': data['filename'],
                'true_label': data.get('label'),
                'predicted': result['motion_detected'],
                'features': result['features'],
                'threshold': result['threshold']
            }]

            # Prepare metrics if label available
            metrics = None
            if data.get('label') is not None:
                is_correct = result['motion_detected'] == data['label']
                if data['label'] == 1:  # True motion
                    cm = [[0, 0], [0, 1]] if is_correct else [[0, 0], [1, 0]]
                else:  # True static
                    cm = [[1, 0], [0, 0]] if is_correct else [[0, 1], [0, 0]]

                metrics = {
                    'accuracy': 100 if is_correct else 0,
                    'precision': 100 if result['motion_detected'] and is_correct else 0,
                    'recall': 100 if data['label'] == 1 and is_correct else 0,
                    'f1_score': 100 if data['label'] == 1 and is_correct else 0,
                    'confusion_matrix': cm,
                    'sample_count': 1
                }

            # Show results
            visualize_results(result_data, metrics, show_features=True)

            # Visualize raw CSI data
            plt.figure(figsize=(12, 6))

            # Extract amplitude
            real = data['csi_data'][:, :, 0]
            imag = data['csi_data'][:, :, 1]
            amplitude = np.sqrt(real ** 2 + imag ** 2)

            # Select most varying subcarriers
            var_per_subcarrier = np.var(amplitude, axis=0)
            top_subcarriers = np.argsort(var_per_subcarrier)[-5:]

            # Plot amplitude data
            for sc in top_subcarriers:
                plt.plot(amplitude[:, sc], label=f"Subcarrier {sc}")

            plt.title(f"CSI Amplitude Data - {motion_status}")
            plt.xlabel("Sample Index")
            plt.ylabel("Amplitude")
            plt.legend()
            plt.grid(True)
            plt.show()

    # Evaluation mode - process test set
    elif args.mode == 'evaluate':
        print("=== Evaluation Mode ===")

        # Load test data
        test_dir = args.input if args.input else config['data_paths']['test_dir']
        print(f"Loading test data: {test_dir}")

        # Load all test files
        test_files = glob.glob(os.path.join(test_dir, "*.csv"))

        if not test_files:
            print(f"No CSV files found in {test_dir}")
            return

        # Process each test file
        all_results = []
        processing_times = []

        for file_path in test_files:
            # Load file
            data = data_loader.load_file(file_path)
            if not data:
                continue

            # Detect motion
            start_time = time.time()
            result = detector.detect(data['csi_data'])
            processing_time = time.time() - start_time
            processing_times.append(processing_time)

            # Record result
            all_results.append({
                'filename': data['filename'],
                'true_label': data.get('label'),
                'predicted': result['motion_detected'],
                'features': result['features'],
                'threshold': result['threshold'],
                'processing_time': processing_time
            })

            # Print progress
            motion_status = "Motion" if result['motion_detected'] else "Static"
            print(f"File {data['filename']} - Predicted: {motion_status} - Time: {processing_time * 1000:.2f}ms")

        # Calculate processing time stats
        avg_time = np.mean(processing_times) * 1000  # Convert to ms
        max_time = np.max(processing_times) * 1000
        min_time = np.min(processing_times) * 1000

        print(f"\nProcessing complete, {len(all_results)} files processed")
        print(f"Average processing time: {avg_time:.2f}ms")
        print(f"Max processing time: {max_time:.2f}ms")
        print(f"Min processing time: {min_time:.2f}ms")

        # Calculate metrics if test data has labels
        labeled_results = [r for r in all_results if r.get('true_label') is not None]
        if labeled_results:
            metrics = evaluate_detection_performance(labeled_results)

            print("\nEvaluation Results:")
            print(f"Accuracy: {metrics['accuracy']:.2f}%")
            print(f"Precision: {metrics['precision']:.2f}%")
            print(f"Recall: {metrics['recall']:.2f}%")
            print(f"F1 Score: {metrics['f1_score']:.2f}%")
            print(f"Confusion Matrix: {metrics['confusion_matrix']}")
        else:
            metrics = None
            print("\nTest data has no labels, cannot calculate metrics")

        # Save results
        results_dir = config['data_paths'].get('results_dir', 'results')
        os.makedirs(results_dir, exist_ok=True)
        save_results(all_results, os.path.join(results_dir, 'test_results.json'))

        # Show visualization if requested
        if args.visualize:
            visualize_results(all_results, metrics, show_features=True)

    # Visualization mode - load and display existing results
    elif args.mode == 'visualize':
        print("=== Visualization Mode ===")

        # Load specified input file
        if args.input and os.path.isfile(args.input):
            try:
                with open(args.input, 'r') as f:
                    results = json.load(f)
                print(f"Loaded {len(results)} result records")

                # Calculate metrics
                metrics = evaluate_detection_performance(results)

                # Show results
                visualize_results(results, metrics, show_features=True)
            except Exception as e:
                print(f"Failed to load results file: {e}")
        else:
            print("Error: Visualization mode requires input results file (--input)")

    else:
        print(f"Error: Unknown mode {args.mode}")


if __name__ == "__main__":
    main()