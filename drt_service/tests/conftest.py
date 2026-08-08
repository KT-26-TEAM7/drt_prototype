"""테스트 전역에서 공유하는 정류장 픽스처와 TestClient 헬퍼.

`app.db.session.station_rows_from_backup()`(CSV 없이도 쓸 수 있는 백업 정류장 데이터)를
SQLAlchemy `Station` 인스턴스로 변환해 DB 없이도 정류장 관련 알고리즘을 테스트할 수 있게 한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.db.models import Station
from app.db.session import station_rows_from_backup
from app.main import create_app


def backup_stations() -> list[Station]:
    return [
        Station(
            station_id=row["station_id"],
            name=row["name"],
            station_type=row["station_type"],
            lat=row["lat"],
            lon=row["lon"],
            coverage_radius_m=row["coverage_radius_m"],
            walk_limit_m=row["walk_limit_m"],
            ext_id=row.get("ext_id"),
        )
        for row in station_rows_from_backup()
    ]


@pytest.fixture
def stations() -> list[Station]:
    return backup_stations()


def make_client(tmp_path: Path, **overrides) -> TestClient:
    config = Settings(
        database_path=tmp_path / "test.sqlite3",
        stations_csv_path=tmp_path / "missing.csv",
        web_dir=BASE_DIR / "web",
        tmap_app_key="",
        relay_api_token="",
        debug=True,  # 인증 없이 테스트하므로 개발 모드로 고정
        max_location_accuracy_m=100.0,  # 개발자 로컬 .env 완화값이 새어들지 않도록 고정
        # 배차는 항상 MockDrtClient로 고정한다. .env에 DRT_SERVER_BASE_URL이 있으면
        # 테스트가 실제 배차 서버가 떠 있어야만 통과하게 되기 때문이다.
        drt_server_base_url="",
        **overrides,
    )
    return TestClient(create_app(config))
