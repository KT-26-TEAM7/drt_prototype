"""app/db/session.py의 CSV 파싱 및 백업 데이터에서 ext_id가 올바르게 전달되는지 검증."""
from __future__ import annotations

from pathlib import Path

from app.db.session import parse_stations_csv, station_rows_from_backup
from tests.conftest import backup_stations


def test_parse_stations_csv_reads_ext_id(tmp_path: Path):
    csv_path = tmp_path / "stations.csv"
    csv_path.write_text(
        "id,name,type,ext_id,latitude,longitude\n"
        "1,사당종합체육관,기존,20534,37.49284821,126.9696768\n"
        "8,사당키움센터(KCC아파트),DRT가상,,37.4818,126.9738\n",
        encoding="utf-8-sig",
    )
    rows = parse_stations_csv(csv_path)
    by_id = {row["station_id"]: row for row in rows}
    assert by_id[1]["ext_id"] == "20534"
    assert by_id[8]["ext_id"] is None


def test_station_rows_from_backup_include_ext_id():
    rows = station_rows_from_backup()
    by_id = {row["station_id"]: row for row in rows}
    assert by_id[1]["ext_id"] == "20534"
    assert by_id[8]["ext_id"] is None


def test_backup_stations_expose_ext_id():
    stations = backup_stations()
    by_id = {station.station_id: station for station in stations}
    assert by_id[1].ext_id == "20534"
    assert by_id[8].ext_id is None
