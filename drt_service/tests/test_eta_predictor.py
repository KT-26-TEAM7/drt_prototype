"""app/travel_time/estimate_duration.py가 학습된 모델(app/travel_time/models)을 로드해
예측하는지, 모델이 없을 때 공식/규칙 폴백으로 안전하게 동작하는지 검증한다."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.travel_time.estimate_duration import ETAPredictor, StationIndex

ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "app" / "travel_time" / "models"


@pytest.fixture
def station_index(stations) -> StationIndex:
    return StationIndex(stations)


def test_predictor_loads_trained_artifacts(station_index: StationIndex):
    predictor = ETAPredictor(station_index, artifacts_dir=ARTIFACTS_DIR)
    assert predictor.model_ready is True
    assert predictor.load_error is None
    assert predictor.dataset_label == "synthetic_demo_full_59939"


def test_predictor_estimate_uses_regressor(station_index: StationIndex):
    predictor = ETAPredictor(station_index, artifacts_dir=ARTIFACTS_DIR)
    estimate = predictor.estimate(
        origin_station="1", destination_station="3",
        weather="맑음", weekday="월요일", hour=9,
    )
    assert estimate.prediction_source == "catboost_regressor"
    assert estimate.travel_time_sec > 0
    assert estimate.lower_bound_sec <= estimate.travel_time_sec <= estimate.upper_bound_sec


def test_predictor_same_station_returns_zero(station_index: StationIndex):
    predictor = ETAPredictor(station_index, artifacts_dir=ARTIFACTS_DIR)
    estimate = predictor.estimate(
        origin_station="1", destination_station="1",
        weather="맑음", weekday="월요일", hour=9,
    )
    assert estimate.prediction_source == "same_station"
    assert estimate.travel_time_sec == 0.0


def test_predictor_unknown_station_raises(station_index: StationIndex):
    predictor = ETAPredictor(station_index, artifacts_dir=ARTIFACTS_DIR)
    with pytest.raises(ValueError):
        predictor.estimate(
            origin_station="존재하지않는정류장", destination_station="3",
            weather="맑음", weekday="월요일", hour=9,
        )


def test_predictor_without_artifacts_falls_back_to_formula(station_index: StationIndex):
    """artifacts_dir이 없으면(모델 미로드) 거리 기반 공식으로 폴백해야 한다."""
    predictor = ETAPredictor(station_index, artifacts_dir=None)
    assert predictor.model_ready is False
    estimate = predictor.estimate(
        origin_station="1", destination_station="3",
        weather="맑음", weekday="월요일", hour=9,
    )
    assert estimate.prediction_source == "distance_formula_fallback"
    assert estimate.travel_time_sec > 0
