"""POST /api/destinations/category-search, /api/destinations/name-search 검증.

내부 함수(search_by_category/search_by_name)가 이미 tests/test_search_by_category.py,
tests/test_planner.py에서 검증돼 있으므로, 여기서는 엔드포인트 계층(정류장 조회,
직렬화, 오류 매핑)만 검증한다.
"""
from __future__ import annotations

from pathlib import Path

from tests.conftest import make_client

BOARDING_STATION_ID = 3  # 남성역 — 기존 테스트들과 동일한 기준점


def test_category_search_returns_candidates(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/category-search", json={
            "query": "정형외과", "boarding_station_id": BOARDING_STATION_ID,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert 0 < len(body["candidates"]) <= 3
        assert all("latitude" in c and "longitude" in c for c in body["candidates"])


def test_category_search_reports_no_candidates(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/category-search", json={
            "query": "우주정거장", "boarding_station_id": BOARDING_STATION_ID,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "no_candidates_found"
        assert body["candidates"] == []
        assert body["reason"]


def test_category_search_unknown_station_returns_404(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/category-search", json={
            "query": "정형외과", "boarding_station_id": 9999,
        })
        assert response.status_code == 404


def test_name_search_returns_candidates(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/name-search", json={
            "query": "남현서울정형외과", "boarding_station_id": BOARDING_STATION_ID,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert any(c["name"] == "남현서울정형외과" for c in body["candidates"])


def test_name_search_reports_no_candidates(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/name-search", json={
            "query": "이세상에없는가게이름절대매치불가", "boarding_station_id": BOARDING_STATION_ID,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "no_candidates_found"
        assert body["candidates"] == []


def test_name_search_unknown_station_returns_404(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/name-search", json={
            "query": "남현서울정형외과", "boarding_station_id": 9999,
        })
        assert response.status_code == 404
