"""여러 담당자 모듈(stations/destination/travel_time)이 공유하는 거리 계산·검색타입 상수.

목표 폴더 구조에는 명시돼 있지 않지만, SQLAlchemy `Station`(lat/lon 컬럼)과 TMAP
`Coordinate`(lat/lon 필드) 양쪽에서 좌표 타입에 결합되지 않고 재사용할 수 있도록
순수 float 인자를 받는 형태로 둔다.
"""
from __future__ import annotations

import math
from enum import Enum

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 WGS84 좌표 사이의 대권(직선) 거리(m)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class SearchKeywordType(str, Enum):
    """TMAP POI 검색어 성격. EXACT(특정 장소명) vs CATEGORY(업종/대분류)."""

    EXACT = "exact"
    CATEGORY = "category"
