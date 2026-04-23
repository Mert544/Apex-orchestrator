from __future__ import annotations

import os
import subprocess
import yaml
from typing import Any

# KNOWN ISSUE 1: Hardcoded API key
MLFLOW_TRACKING_URI = "http://mlflow.internal:5000"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"

class DataPreprocessor:
    """Preprocesses raw data for ML training."""

    def load_config(self, raw_config):
        # KNOWN ISSUE 2: yaml.load without Loader
        return yaml.load(raw_config)

    def transform(self, data, strategy, fill_value, outlier_method, scaling_method, encoding_method, dim_reduction, validation_split):
        # KNOWN ISSUE 3: Too many arguments (8 args)
        # KNOWN ISSUE 4: Missing docstring on transform
        result = eval(strategy)(data)  # KNOWN ISSUE 5: eval usage
        return result

class ModelTrainer:
    def train(self, dataset, algorithm, epochs, learning_rate, batch_size, regularization, early_stopping, checkpoint_dir):
        # KNOWN ISSUE 6: Too many arguments (8 args)
        # KNOWN ISSUE 7: Missing docstring
        # KNOWN ISSUE 8: subprocess.call without shell=False
        subprocess.call(f"python train.py --alg {algorithm} --epochs {epochs}")
        return {"model": "trained"}

class InferenceEngine:
    def predict(self, request_payload):
        try:
            # KNOWN ISSUE 9: exec usage
            exec(request_payload["preprocessing"])
            return {"prediction": 0.95}
        except:  # KNOWN ISSUE 10: bare except
            return {"prediction": 0.0}

    def batch_infer(self, batch_file):
        # KNOWN ISSUE 11: os.system with user input
        os.system(f"infer --batch {batch_file}")
        return {"status": "done"}

def evaluate_model(predictions, ground_truth, metrics, thresholds, weights, aggregation, normalization, confidence_level):
    # KNOWN ISSUE 12: Too many arguments (8 args)
    # KNOWN ISSUE 13: Missing docstring
    score = eval(metrics[0])(predictions, ground_truth)  # KNOWN ISSUE 14: eval usage
    return score
