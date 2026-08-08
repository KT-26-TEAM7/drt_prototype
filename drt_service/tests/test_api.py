from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import make_client


def test_health_and_openapi(tmp_path: Path):
    with make_client(tmp_path) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["active_stations"] == 20
        schema = client.get("/openapi.json").json()
        assert "/api/plan" in schema["paths"]


def test_location_roundtrip_uses_sqlite(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/location", json={
            "latitude": 37.48, "longitude": 126.97, "accuracy": 5.0,
        })
        assert response.status_code == 200
        latest = client.get("/api/location")
        assert latest.json()["ok"] is True
        assert latest.json()["location"]["latitude"] == 37.48


def test_category_plan_in_mock_mode(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/plan", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "accuracy": 12.5,
            "query": "정형외과",
            "is_specific": False,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["plan"]["recommended_mode"] in {"walk", "drt"}
        assert body["plan"]["origin_address"]["status"] == "MOCK"
        assert body["plan"]["candidate_audit"]
        # 3개 후보 목록(candidate_audit)이 최종 확정 결과(destination)보다 먼저 나와야
        # "후보 제시 -> 최종 선택" 순서로 읽힌다.
        keys = list(body["plan"].keys())
        assert keys.index("candidate_audit") < keys.index("destination")


def test_specific_plan_and_walk_limit(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/plan", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "남현서울정형외과",
            "is_specific": True,
            "max_walk_m": 500,
        })
        assert response.status_code == 200
        plan = response.json()["plan"]
        assert plan["destination"]["name"] == "남현서울정형외과"
        assert plan["recommended_mode"] == "drt"
        assert plan["applied_max_walk_m"] == 500
        # total_travel_time_s는 반올림 전 원시 초 단위 값이라, 이미 반올림된
        # boarding/vehicle/alighting 개별 duration_s 합과는 최대 몇 초 오차가
        # 날 수 있다. 정확한(반올림 없는) 검증은 tests/test_planner.py에서 한다.
        assert plan["total_travel_time_s"] == pytest.approx(
            plan["boarding"]["walk_duration_s"]
            + plan["vehicle"]["duration_s"]
            + plan["alighting"]["walk_duration_s"],
            abs=2,
        )
        assert plan["total_travel_time_min"] == round(plan["total_travel_time_s"] / 60, 1)

        strict = client.post("/api/plan", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "남현서울정형외과",
            "is_specific": True,
            "max_walk_m": 5,
        }).json()["plan"]
        assert strict["status"] == "no_accessible_boarding_station"


def test_walk_recommended_total_travel_time_matches_direct_walk(tmp_path: Path):
    with make_client(tmp_path) as client:
        plan = client.post("/api/plan", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "사당정형외과의원",
            "is_specific": True,
        }).json()["plan"]
        assert plan["recommended_mode"] == "walk"
        assert plan["total_travel_time_s"] == pytest.approx(plan["direct_walk"]["duration_s"], abs=1)


def test_plan_without_weather_speed_level_still_succeeds(tmp_path: Path):
    """weather/speed_level을 생략해도(자동 계산) 정상 동작해야 한다."""
    with make_client(tmp_path) as client:
        response = client.post("/api/plan", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "남현서울정형외과",
            "is_specific": True,
        })
        assert response.status_code == 200
        plan = response.json()["plan"]
        assert plan["recommended_mode"] == "drt"
        assert plan["vehicle"]["source"] not in {None, ""}


def test_plan_with_weather_speed_level_uses_eta_model(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/plan", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "남현서울정형외과",
            "is_specific": True,
            "weather": "비",
            "speed_level": "하",
        })
        assert response.status_code == 200
        plan = response.json()["plan"]
        assert plan["recommended_mode"] == "drt"
        # ML 회귀 모델(catboost_regressor) 또는 그 폴백(공식/규칙) 출처 중 하나여야 하며,
        # mock 클라이언트의 기존 직선거리 추정치(mock_car)를 타면 ETA 모델이 적용되지 않은 것이다.
        assert plan["vehicle"]["source"] != "mock_car"


def test_location_quality_validation(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/location", json={
            "latitude": 37.48, "longitude": 126.97, "accuracy": 101,
        })
        assert response.status_code == 422
        assert "위치 정확도가 낮습니다" in response.json()["detail"]


def test_list_stations_exposes_ext_id(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.get("/api/stations")
        assert response.status_code == 200
        stations = {s["station_id"]: s for s in response.json()["stations"]}
        assert stations[1]["ext_id"] == "20534"
        assert stations[8]["ext_id"] is None


def test_outside_service_area(tmp_path: Path):
    with make_client(tmp_path) as client:
        plan = client.post("/api/plan", json={
            "latitude": 37.2861138,
            "longitude": 127.0458013,
            "query": "정형외과",
        }).json()["plan"]
        assert plan["status"] == "outside_service_area"
        assert plan["recommended_mode"] == "other_transit"
