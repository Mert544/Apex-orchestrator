from __future__ import annotations

from app.pipeline import DataPreprocessor, ModelTrainer

app_name = "ml-pipeline"


def main() -> dict[str, Any]:
    preprocessor = DataPreprocessor()
    trainer = ModelTrainer()

    config = preprocessor.load_config("epochs: 10\nlearning_rate: 0.01")
    model = trainer.train(
        dataset="dataset_v1.csv",
        algorithm="xgboost",
        epochs=config["epochs"],
        learning_rate=config["learning_rate"],
        batch_size=32,
        regularization=0.01,
        early_stopping=True,
        checkpoint_dir="/tmp/checkpoints",
    )
    return {"model": model}
