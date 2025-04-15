# CSI Breathing Rate Estimation Project

A system for breathing rate estimation using WiFi CSI signals.

## Project Structure


csi_breathing_estimation/
├── data/ # Data directory
│ └── breathing_rate/ # Breathing rate dataset
│ ├── evaluation/ # Evaluation data
│ └── test/ # Test data
├── results/ # Results directory
├── config.json # Configuration file
├── data_loader.py # Data loading module
├── breathing_estimator.py # Breathing rate estimation algorithm
├── evaluation.py # Evaluation functions
├── main.py # Main program
├── mqtt_receiver.py # MQTT receiver module
└── README.md # Project documentation


## Features

- Estimate human breathing rate from CSI data
- Support file-based batch processing and evaluation
- Support real-time CSI data reception and processing via MQTT
- Result visualization and performance evaluation

## Usage

### Install Dependencies

```bash
pip install -r requirements.txt



Evaluation Mode
Evaluate performance on predefined datasets:


python main.py --mode evaluate --config config.json --visualize
Prediction Mode
Process a single CSI file:


python main.py --mode predict --input ./data/breathing_rate/test/CSI20250227_191018.csv --visualize
Real-time Processing Mode
Receive and process real-time CSI data via MQTT:


python mqtt_receiver.py --config config.json
Algorithm Principles
The system estimates breathing rate using the following steps:

Preprocess CSI data
Extract amplitude and phase information
Select most sensitive subcarriers
Apply bandpass filter (0.1-0.6Hz) to retain breathing-related signals
Breathing Rate Estimation
Use sliding window (15 seconds) to process data
Apply FFT analysis to obtain dominant frequency
Convert frequency to BPM (breaths per minute)
Result Optimization
Smooth estimation results
Round to integer BPM
Performance Evaluation
The system uses MAE (Mean Absolute Error) for performance evaluation. The target is to achieve a median MAE of 0.94 BPM.

Configuration Parameters
Key configuration parameters:

window_size: Processing window size (in samples)
overlap: Window overlap ratio
bandpass_filter: Bandpass filter parameters
fft_method: FFT analysis parameters
subcarrier_selection: Subcarrier selection method



# 测试第一个文件
python main.py --mode predict --input data/breathing_rate/test/CSI20250227_193342.csv --visualize

# 测试第二个文件
python main.py --mode predict --input data/breathing_rate/test/CSI20250227_200223.csv --visualize

# 测试第三个文件
python main.py --mode predict --input data/breathing_rate/test/CSI20250227_201424.csv --visualize