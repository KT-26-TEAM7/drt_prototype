"""한태희 담당: CatBoost/LightGBM ETA 회귀·속도 분류 모델 학습.

REG_FEATURES/CLASS_FEATURES는 app/travel_time/estimate_duration.py::ETAPredictor가
예측 시 쓰는 피처 목록과 반드시 같아야 한다.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

REG_CATEGORICAL = [
    "origin_station", "destination_station", "weather", "weekday", "hour_band", "speed_level",
]
REG_NUMERIC = ["hour", "route_distance_m"]
REG_FEATURES = REG_CATEGORICAL + REG_NUMERIC

CLASS_CATEGORICAL = ["weather", "weekday", "hour_band"]
CLASS_NUMERIC = ["hour"]
CLASS_FEATURES = CLASS_CATEGORICAL + CLASS_NUMERIC

SPEED_LABELS = ["low", "medium", "high"]
SPEED_LABELS_KO = {"low": "하", "medium": "중", "high": "상"}


@dataclass(slots=True)
class RegressionMetrics:
    """eta_sec(정류장 간 DRT 차량시간) 회귀 평가 지표."""

    mae_s: float
    rmse_s: float
    r2: float


@dataclass(slots=True)
class ClassificationMetrics:
    """speed_level(하/중/상) 분류 평가 지표."""

    accuracy: float
    macro_f1: float
    weighted_f1: float
    labels: list[str]
    labels_ko: list[str]
    confusion_matrix: list[list[int]]
    per_class: dict[str, dict[str, float | int]]


def _regression_metrics(y_true: pd.Series, prediction: np.ndarray) -> RegressionMetrics:
    y = np.asarray(y_true, dtype=float)
    pred = np.asarray(prediction, dtype=float)
    return RegressionMetrics(
        mae_s=float(mean_absolute_error(y, pred)),
        rmse_s=float(math.sqrt(mean_squared_error(y, pred))),
        r2=float(r2_score(y, pred)),
    )


def _classification_metrics(y_true: pd.Series, prediction: np.ndarray) -> ClassificationMetrics:
    y = np.asarray(y_true, dtype=str)
    pred = np.asarray(prediction, dtype=str)
    report = classification_report(y, pred, labels=SPEED_LABELS, output_dict=True, zero_division=0)
    matrix = confusion_matrix(y, pred, labels=SPEED_LABELS)
    per_class: dict[str, dict[str, float | int]] = {}
    for label in SPEED_LABELS:
        row = report.get(label, {})
        per_class[label] = {
            "label_ko": SPEED_LABELS_KO[label],
            "precision": float(row.get("precision", 0.0)),
            "recall": float(row.get("recall", 0.0)),
            "f1_score": float(row.get("f1-score", 0.0)),
            "support": int(row.get("support", 0)),
        }
    return ClassificationMetrics(
        accuracy=float(accuracy_score(y, pred)),
        macro_f1=float(f1_score(y, pred, labels=SPEED_LABELS, average="macro", zero_division=0)),
        weighted_f1=float(f1_score(y, pred, labels=SPEED_LABELS, average="weighted", zero_division=0)),
        labels=list(SPEED_LABELS), labels_ko=[SPEED_LABELS_KO[label] for label in SPEED_LABELS],
        confusion_matrix=matrix.astype(int).tolist(), per_class=per_class,
    )


def _make_lightgbm_pipeline(*, task: str, random_seed: int) -> Pipeline:
    try:
        from lightgbm import LGBMClassifier, LGBMRegressor
    except ImportError as exc:  # pragma: no cover - 설치 가이드용
        raise RuntimeError("LightGBM이 설치되어 있지 않습니다. requirements.txt를 설치하세요.") from exc

    if task == "regression":
        categorical, numeric = REG_CATEGORICAL, REG_NUMERIC
        estimator = LGBMRegressor(
            objective="regression_l1", n_estimators=180, learning_rate=0.045, num_leaves=31,
            max_depth=-1, min_child_samples=30, subsample=0.9, colsample_bytree=0.9,
            reg_lambda=0.2, random_state=random_seed, n_jobs=4, verbosity=-1,
        )
    elif task == "classification":
        categorical, numeric = CLASS_CATEGORICAL, CLASS_NUMERIC
        estimator = LGBMClassifier(
            objective="multiclass", n_estimators=160, learning_rate=0.05, num_leaves=24,
            min_child_samples=30, subsample=0.9, colsample_bytree=0.9,
            reg_lambda=0.2, random_state=random_seed, n_jobs=4, verbosity=-1,
        )
    else:
        raise ValueError(task)

    transformer = ColumnTransformer(
        transformers=[
            ("categorical", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), categorical),
            ("numeric", "passthrough", numeric),
        ],
        remainder="drop", verbose_feature_names_out=False,
    )
    return Pipeline([("features", transformer), ("model", estimator)])


def _make_catboost(*, task: str, random_seed: int):
    try:
        from catboost import CatBoostClassifier, CatBoostRegressor
    except ImportError as exc:  # pragma: no cover - 설치 가이드용
        raise RuntimeError("CatBoost가 설치되어 있지 않습니다. requirements.txt를 설치하세요.") from exc

    if task == "regression":
        return CatBoostRegressor(
            iterations=160, depth=7, learning_rate=0.055, loss_function="MAE", eval_metric="MAE",
            random_seed=random_seed, verbose=False, allow_writing_files=False, thread_count=4,
        )
    if task == "classification":
        return CatBoostClassifier(
            iterations=140, depth=7, learning_rate=0.06, loss_function="MultiClass", eval_metric="TotalF1",
            random_seed=random_seed, verbose=False, allow_writing_files=False, thread_count=4,
        )
    raise ValueError(task)


def _clean_model_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = set(REG_FEATURES + ["travel_time_sec"])
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"학습용 전처리 데이터에 컬럼이 없습니다: {missing}")
    clean = frame.dropna(subset=list(required)).copy()
    for column in set(REG_CATEGORICAL + CLASS_CATEGORICAL + ["speed_level"]):
        clean[column] = clean[column].astype(str)
    clean["hour"] = pd.to_numeric(clean["hour"], errors="coerce")
    clean["route_distance_m"] = pd.to_numeric(clean["route_distance_m"], errors="coerce")
    clean["travel_time_sec"] = pd.to_numeric(clean["travel_time_sec"], errors="coerce")
    clean = clean.dropna(subset=["hour", "route_distance_m", "travel_time_sec"])
    clean = clean[clean["speed_level"].isin(SPEED_LABELS)]
    return clean


def _sample_frame(frame: pd.DataFrame, max_rows: int | None, random_seed: int) -> pd.DataFrame:
    if max_rows and len(frame) > max_rows:
        return frame.sample(n=max_rows, random_state=random_seed).reset_index(drop=True)
    return frame.reset_index(drop=True)


def _write_confusion_matrix_csv(target_dir: Path, model_name: str, metrics: ClassificationMetrics) -> None:
    table = pd.DataFrame(
        metrics.confusion_matrix,
        index=[f"actual_{SPEED_LABELS_KO[label]}" for label in metrics.labels],
        columns=[f"pred_{SPEED_LABELS_KO[label]}" for label in metrics.labels],
    )
    table.index.name = "actual\\predicted"
    table.to_csv(target_dir / f"confusion_matrix_{model_name}.csv", encoding="utf-8-sig")


def train_eta_models(
    processed_csv: str | Path,
    artifacts_dir: str | Path,
    *,
    dataset_label: str = "user_dataset",
    max_rows: int | None = 300_000,
    random_seed: int = 42,
    candidate_models: Iterable[str] = ("catboost", "lightgbm"),
) -> dict[str, Any]:
    """CatBoost와 LightGBM만 사용해 ETA 회귀·속도 분류 모델을 비교한다."""
    source = Path(processed_csv)
    target_dir = Path(artifacts_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    frame = _clean_model_frame(pd.read_csv(source, low_memory=False))
    frame = _sample_frame(frame, max_rows, random_seed)
    if len(frame) < 200:
        raise ValueError(f"학습 데이터가 너무 적습니다: {len(frame)}행")

    train_frame, test_frame = train_test_split(
        frame, test_size=0.2, random_state=random_seed,
        stratify=frame["speed_level"] if frame["speed_level"].value_counts().min() >= 2 else None,
    )

    speed_distribution = {label: int((frame["speed_level"] == label).sum()) for label in SPEED_LABELS}
    metrics: dict[str, Any] = {
        "dataset_label": dataset_label,
        "target_definition": {
            "regression_target": "eta_sec", "internal_column": "travel_time_sec",
            "meaning": "출발 DRT 정류장에서 도착 DRT 정류장까지의 차량 이동시간(초)",
            "classification_target": "speed_level",
        },
        "rows_used": len(frame), "train_rows": len(train_frame), "test_rows": len(test_frame),
        "split": {
            "method": "train_test_split", "train_ratio": 0.8, "test_ratio": 0.2,
            "random_seed": random_seed, "stratified_by": "speed_level",
        },
        "classification_criteria": {
            "speed_low": "speed_kmh < 15", "speed_medium": "15 <= speed_kmh < 25",
            "speed_high": "speed_kmh >= 25", "class_order": SPEED_LABELS,
            "class_order_ko": [SPEED_LABELS_KO[label] for label in SPEED_LABELS],
            "class_distribution": speed_distribution,
        },
        "regression": {}, "classification": {},
    }

    reg_artifacts: dict[str, str] = {}
    clf_artifacts: dict[str, str] = {}

    candidates = tuple(dict.fromkeys(name.strip().lower() for name in candidate_models))
    allowed = {"catboost", "lightgbm"}
    invalid = sorted(set(candidates).difference(allowed))
    if invalid:
        raise ValueError(f"지원하지 않는 모델 후보: {invalid}. CatBoost와 LightGBM만 사용합니다.")

    for name in candidates:
        if name == "catboost":
            regressor = _make_catboost(task="regression", random_seed=random_seed)
            regressor.fit(
                train_frame[REG_FEATURES], train_frame["travel_time_sec"],
                cat_features=REG_CATEGORICAL,
                eval_set=(test_frame[REG_FEATURES], test_frame["travel_time_sec"]),
                early_stopping_rounds=25, verbose=False,
            )
            reg_pred = regressor.predict(test_frame[REG_FEATURES])
            reg_metrics = _regression_metrics(test_frame["travel_time_sec"], reg_pred)
            metrics["regression"]["catboost"] = asdict(reg_metrics)
            joblib.dump(
                {"kind": "catboost", "model": regressor, "features": REG_FEATURES},
                target_dir / "regression_catboost.joblib",
            )
            reg_artifacts["catboost"] = "regression_catboost.joblib"

            classifier = _make_catboost(task="classification", random_seed=random_seed)
            classifier.fit(
                train_frame[CLASS_FEATURES], train_frame["speed_level"],
                cat_features=CLASS_CATEGORICAL,
                eval_set=(test_frame[CLASS_FEATURES], test_frame["speed_level"]),
                early_stopping_rounds=25, verbose=False,
            )
            clf_pred = classifier.predict(test_frame[CLASS_FEATURES]).reshape(-1)
            clf_metrics = _classification_metrics(test_frame["speed_level"], clf_pred)
            metrics["classification"]["catboost"] = asdict(clf_metrics)
            _write_confusion_matrix_csv(target_dir, "catboost", clf_metrics)
            joblib.dump(
                {"kind": "catboost", "model": classifier, "features": CLASS_FEATURES},
                target_dir / "classifier_catboost.joblib",
            )
            clf_artifacts["catboost"] = "classifier_catboost.joblib"

        elif name == "lightgbm":
            regressor = _make_lightgbm_pipeline(task="regression", random_seed=random_seed)
            regressor.fit(train_frame[REG_FEATURES], train_frame["travel_time_sec"])
            reg_pred = regressor.predict(test_frame[REG_FEATURES])
            reg_metrics = _regression_metrics(test_frame["travel_time_sec"], reg_pred)
            metrics["regression"]["lightgbm"] = asdict(reg_metrics)
            joblib.dump(
                {"kind": "lightgbm", "model": regressor, "features": REG_FEATURES},
                target_dir / "regression_lightgbm.joblib",
            )
            reg_artifacts["lightgbm"] = "regression_lightgbm.joblib"

            classifier = _make_lightgbm_pipeline(task="classification", random_seed=random_seed)
            classifier.fit(train_frame[CLASS_FEATURES], train_frame["speed_level"])
            clf_pred = classifier.predict(test_frame[CLASS_FEATURES])
            clf_metrics = _classification_metrics(test_frame["speed_level"], clf_pred)
            metrics["classification"]["lightgbm"] = asdict(clf_metrics)
            _write_confusion_matrix_csv(target_dir, "lightgbm", clf_metrics)
            joblib.dump(
                {"kind": "lightgbm", "model": classifier, "features": CLASS_FEATURES},
                target_dir / "classifier_lightgbm.joblib",
            )
            clf_artifacts["lightgbm"] = "classifier_lightgbm.joblib"

    selected_regressor = min(
        metrics["regression"],
        key=lambda model_name: (
            metrics["regression"][model_name]["mae_s"],
            metrics["regression"][model_name]["rmse_s"],
            -metrics["regression"][model_name]["r2"],
        ),
    )
    if not metrics["classification"]:
        raise ValueError("속도 분류 모델 후보가 없습니다.")
    selected_classifier = max(
        metrics["classification"],
        key=lambda model_name: (
            metrics["classification"][model_name]["macro_f1"],
            metrics["classification"][model_name]["accuracy"],
        ),
    )

    manifest = {
        "version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_label": dataset_label,
        "processed_csv": source.name,
        "rows_used": len(frame),
        "selected_regressor": {
            "name": selected_regressor, "path": reg_artifacts[selected_regressor],
            "selection_metric": "MAE (동률 시 RMSE, R2)",
            "metrics": metrics["regression"][selected_regressor],
        },
        "selected_classifier": {
            "name": selected_classifier, "path": clf_artifacts[selected_classifier],
            "selection_metric": "macro F1-score (동률 시 accuracy)",
            "metrics": metrics["classification"][selected_classifier],
        },
        "regression_features": REG_FEATURES, "classification_features": CLASS_FEATURES,
        "speed_levels": SPEED_LABELS,
        "speed_level_thresholds_kmh": {"low_lt": 15.0, "medium_lt": 25.0, "high_gte": 25.0},
        "note": (
            "synthetic_demo이면 실행 검증용 합성 데이터 학습 결과이며 실제 운영 성능을 의미하지 않습니다. "
            "실제 데이터셋으로 scripts/train_eta_models.py를 다시 실행해야 합니다."
        ),
    }
    (target_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (target_dir / "model_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest": manifest, "metrics": metrics}
