import numpy as np
import json
import os
import time
import matplotlib.pyplot as plt


def evaluate_detection_performance(results):
    """
    评估运动检测性能

    参数:
    results: 包含'true_label'和'predicted'的结果列表

    返回:
    性能指标字典
    """
    # Extract true labels and predictions
    true_labels = [r['true_label'] for r in results if 'true_label' in r]
    predictions = [r['predicted'] for r in results if 'true_label' in r]

    # Return empty evaluation if no labeled data
    if not true_labels:
        return {
            'accuracy': 0,
            'precision': 0,
            'recall': 0,
            'f1_score': 0,
            'confusion_matrix': [[0, 0], [0, 0]],
            'sample_count': 0
        }

    # Calculate confusion matrix [TN, FP; FN, TP]
    cm = [[0, 0], [0, 0]]
    for true, pred in zip(true_labels, predictions):
        cm[true][int(pred)] += 1

    # Extract metrics
    tn, fp = cm[0]
    fn, tp = cm[1]

    # Calculate evaluation metrics
    total = tn + fp + fn + tp
    accuracy = (tp + tn) / total if total else 0

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    return {
        'accuracy': accuracy * 100,
        'precision': precision * 100,
        'recall': recall * 100,
        'f1_score': f1 * 100,
        'confusion_matrix': cm,
        'sample_count': total,
        'true_positive': tp,
        'false_positive': fp,
        'true_negative': tn,
        'false_negative': fn
    }


def save_results(results, file_path):
    """
    保存检测结果到文件

    参数:
    results: 结果列表
    file_path: 输出文件路径
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
            elif isinstance(obj, dict):
                return {k: convert_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_for_json(i) for i in obj]
            else:
                return obj

        serializable_results = convert_for_json(results)

        with open(file_path, 'w') as f:
            json.dump(serializable_results, f, indent=2)

        print(f"Results saved to: {file_path}")

    except Exception as e:
        print(f"Error saving results: {e}")


def visualize_results(results, metrics=None, show_features=False):
    """
    可视化检测结果

    参数:
    results: 结果列表
    metrics: 评估指标
    show_features: 是否显示特征详情
    """
    plt.figure(figsize=(12, 8))

    # Extract data
    file_names = [r.get('filename', f"Sample_{i}") for i, r in enumerate(results)]
    true_labels = [r.get('true_label', None) for r in results]
    predictions = [r.get('predicted', False) for r in results]

    # Plot results comparison
    x = np.arange(len(results))
    width = 0.35

    # Separate results for coloring
    correct_indices = []
    incorrect_indices = []
    unlabeled_indices = []

    for i, (true, pred) in enumerate(zip(true_labels, predictions)):
        if true is None:
            unlabeled_indices.append(i)
        elif true == pred:
            correct_indices.append(i)
        else:
            incorrect_indices.append(i)

    # Plot predictions
    plt.subplot(2, 1, 1)
    plt.bar(x, predictions, width, label='Prediction')

    # Show true labels if available
    labeled_indices = [i for i, label in enumerate(true_labels) if label is not None]
    if labeled_indices:
        labeled_x = [x[i] for i in labeled_indices]
        labeled_y = [true_labels[i] for i in labeled_indices]
        plt.bar([pos + width for pos in labeled_x], labeled_y, width, label='True label')

    # Mark correct and incorrect predictions
    if correct_indices:
        plt.scatter([x[i] for i in correct_indices], [predictions[i] + 0.1 for i in correct_indices],
                    color='green', marker='o', label='Correct')

    if incorrect_indices:
        plt.scatter([x[i] for i in incorrect_indices], [predictions[i] + 0.1 for i in incorrect_indices],
                    color='red', marker='x', label='Incorrect')

    plt.xlabel('Sample')
    plt.ylabel('Classification (0=Static, 1=Moving)')
    plt.title('Motion Detection Results')
    plt.xticks(x, [f"{i}" for i in range(len(results))], rotation=90)
    plt.yticks([0, 1], ['Static', 'Moving'])
    plt.legend()
    plt.grid(True, axis='y')

    # Show confusion matrix if metrics available
    if metrics:
        plt.subplot(2, 1, 2)
        cm = metrics['confusion_matrix']

        plt.imshow(cm, interpolation='nearest', cmap=plt.cm.Blues)
        plt.title(f'Confusion Matrix (Accuracy: {metrics["accuracy"]:.1f}%)')
        plt.colorbar()

        plt.xticks([0, 1], ['Predicted Static', 'Predicted Moving'])
        plt.yticks([0, 1], ['Actual Static', 'Actual Moving'])

        # Show values in each cell
        thresh = np.max(cm) / 2.0
        for i in range(2):
            for j in range(2):
                plt.text(j, i, f"{cm[i][j]}",
                         ha="center", va="center",
                         color="white" if cm[i][j] > thresh else "black")

        plt.xlabel('Predicted Label')
        plt.ylabel('True Label')

        # Add metrics text
        textstr = (f'Accuracy: {metrics["accuracy"]:.1f}%\n'
                   f'Precision: {metrics["precision"]:.1f}%\n'
                   f'Recall: {metrics["recall"]:.1f}%\n'
                   f'F1 Score: {metrics["f1_score"]:.1f}%')

        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        plt.gcf().text(0.85, 0.15, textstr, fontsize=10, bbox=props)

    # Show features if requested
    if show_features and 'features' in results[0]:
        plt.figure(figsize=(14, 6))

        # Extract features
        var_means = [r['features']['amp_variance_mean'] for r in results]
        diff_means = [r['features']['amp_diff_mean_avg'] for r in results]
        thresholds = [r.get('threshold', 0) for r in results]

        plt.plot(x, var_means, 'b-', label='Amplitude Variance')
        plt.plot(x, diff_means, 'g-', label='Amplitude Change Rate')
        plt.plot(x, thresholds, 'r--', label='Adaptive Threshold')

        # Mark predictions
        for i, pred in enumerate(predictions):
            marker = 'o' if pred else 'x'
            color = 'red' if pred else 'blue'
            plt.scatter(i, var_means[i], marker=marker, color=color)

        plt.xlabel('Sample')
        plt.ylabel('Feature Value')
        plt.title('Detection Features and Threshold')
        plt.legend()
        plt.grid(True)

    plt.tight_layout()
    plt.show()