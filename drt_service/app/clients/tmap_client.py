"""TMAP 장소 검색·보행자/자동차 경로 API 호출 및 키 없는 개발용 MockTmapClient.

`TmapClient`와 `MockTmapClient`는 동일한 메서드 시그니처(search_pois/pedestrian_route/
car_route/reverse_geocode/close)를 가진다 — 어떤 걸 쓸지 고르는 로직은 `app/main.py`에 있다.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx

from app.geo import SearchKeywordType, haversine_m

# 목적지 후보가 주차장으로 잡히는 걸 막는다. TmapClient(실제 API)와
# MockTmapClient 양쪽에서 같은 기준으로 걸러야 하므로 여기 하나만 둔다.
EXCLUDED_POI_KEYWORDS = ("주차장", "주차시설", "주차타워")


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    distance_m: float
    duration_s: float
    source: str


@dataclass
class POI:
    poi_id: str
    name: str
    coord: Coordinate
    address: str = ""
    straight_distance_m: float = 0.0
    source: str = "tmap_api"
    phone: str | None = None
    district: str | None = None
    neighborhood: str | None = None
    category: str | None = None
    detail_category: str | None = None


def poi_to_dict(poi: POI) -> dict[str, Any]:
    """POI를 API 응답용 dict로 직렬화한다.

    확정된 단일 목적지(plan.destination)와 동명이인 후보 목록
    (needs_destination_confirmation.candidates, /api/destinations/*-search) 양쪽에서
    같은 필드 구성을 쓰도록 여기 하나로 모은다 — 후보로 받든 최종 확정으로 받든
    프론트가 같은 정보를 볼 수 있어야 하기 때문이다.
    """
    return {
        "name": poi.name,
        "address": poi.address,
        "latitude": poi.coord.lat,
        "longitude": poi.coord.lon,
        "straight_distance_m": round(poi.straight_distance_m),
        "source": poi.source,
        "phone": poi.phone,
        "district": poi.district,
        "neighborhood": poi.neighborhood,
        "category": poi.category,
        "detail_category": poi.detail_category,
    }


class TmapError(RuntimeError):
    """TMAP request or response failure."""


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_road_address(raw: dict) -> str | None:
    """도로명주소. newAddressList.newAddress[].fullAddressRoad에서 첫 값을 취한다."""
    new_address_list = raw.get("newAddressList") or {}
    if not isinstance(new_address_list, dict):
        return None
    new_addresses = new_address_list.get("newAddress") or []
    if isinstance(new_addresses, dict):
        new_addresses = [new_addresses]
    if not isinstance(new_addresses, list):
        return None
    for new_address in new_addresses:
        if not isinstance(new_address, dict):
            continue
        full_address = _normalize_text(new_address.get("fullAddressRoad"))
        if full_address:
            return full_address
    return None


def _extract_lot_address(raw: dict) -> str | None:
    """지번주소. 도로명주소가 없을 때의 폴백."""
    address_parts = [
        _normalize_text(raw.get("upperAddrName")),
        _normalize_text(raw.get("middleAddrName")),
        _normalize_text(raw.get("lowerAddrName")),
    ]
    address_parts = [part for part in address_parts if part]

    first_number = _normalize_text(raw.get("firstNo"))
    second_number = _normalize_text(raw.get("secondNo"))
    if first_number:
        lot_number = first_number
        if second_number and second_number != "0":
            lot_number += f"-{second_number}"
        address_parts.append(lot_number)

    detail_address = _normalize_text(raw.get("detailAddrName"))
    if detail_address:
        address_parts.append(detail_address)

    return " ".join(address_parts) or None


class TmapClient:
    def __init__(
        self,
        app_key: str,
        base_url: str = "https://apis.openapi.sk.com",
        timeout_s: float = 8,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ):
        self.app_key = app_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._walk_cache: OrderedDict[tuple, Route] = OrderedDict()
        self._reverse_cache: OrderedDict[tuple[float, float], tuple[float, dict]] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        if not self.app_key:
            raise TmapError("TMAP_APP_KEY가 설정되지 않았습니다.")
        headers = {"appKey": self.app_key, "Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code in {408, 425, 429} or exc.response.status_code >= 500
                )
                if not retryable or attempt >= self.max_retries:
                    break
                await asyncio.sleep(0.3 * (attempt + 1))
        raise TmapError(f"TMAP 호출 실패({url}): {last_error}") from last_error

    @staticmethod
    def _json(response: httpx.Response, operation: str) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise TmapError(f"TMAP {operation} 응답이 올바른 JSON이 아닙니다.") from exc
        if not isinstance(body, dict):
            raise TmapError(f"TMAP {operation} 응답 최상위 형식이 객체가 아닙니다.")
        return body

    async def search_pois(
        self,
        keyword: str,
        center: Coordinate,
        radius_m: int,
        count: int = 5,
        keyword_type: SearchKeywordType = SearchKeywordType.CATEGORY,
    ) -> list[POI]:
        radius_km = min(33, max(1, math.ceil(radius_m / 1000)))
        response = await self._request(
            "GET",
            f"{self.base_url}/tmap/pois",
            headers=self._headers(),
            params={
                "version": "1", "format": "json", "searchKeyword": keyword,
                "searchType": "all",
                "searchtypCd": "A" if keyword_type is SearchKeywordType.EXACT else "R",
                "centerLon": f"{center.lon:.7f}", "centerLat": f"{center.lat:.7f}",
                "radius": radius_km, "reqCoordType": "WGS84GEO",
                "resCoordType": "WGS84GEO", "count": min(200, max(1, count)),
                "page": 1, "multiPoint": "N", "poiGroupYn": "N",
            },
        )
        if response.status_code == 204:
            return []
        return self._parse_pois(self._json(response, "POI 검색"), center, radius_m, count)

    @staticmethod
    def _parse_pois(body: dict, center: Coordinate, radius_m: int, count: int) -> list[POI]:
        raw_pois = (((body.get("searchPoiInfo") or {}).get("pois") or {}).get("poi") or [])
        if isinstance(raw_pois, dict):
            raw_pois = [raw_pois]
        if not isinstance(raw_pois, list):
            raise TmapError("TMAP POI 목록 형식이 올바르지 않습니다.")
        results: list[POI] = []
        for index, raw in enumerate(raw_pois):
            if not isinstance(raw, dict):
                continue
            coord = None
            for lat_key, lon_key in (
                ("pnsLat", "pnsLon"), ("frontLat", "frontLon"), ("noorLat", "noorLon"),
            ):
                try:
                    coord = Coordinate(float(raw[lat_key]), float(raw[lon_key]))
                    break
                except (KeyError, TypeError, ValueError):
                    continue
            name = str(raw.get("name") or "").strip()
            if not name or coord is None:
                continue
            if any(keyword in name for keyword in EXCLUDED_POI_KEYWORDS):
                continue
            distance = haversine_m(center.lat, center.lon, coord.lat, coord.lon)
            if distance > radius_m:
                continue
            address = _extract_road_address(raw) or _extract_lot_address(raw) or ""
            results.append(POI(
                str(raw.get("id") or raw.get("pkey") or f"tmap-{index}"),
                name, coord, address, distance, "tmap_api",
                phone=_normalize_text(raw.get("telNo")),
                district=_normalize_text(raw.get("middleAddrName")),
                neighborhood=_normalize_text(raw.get("lowerAddrName")),
                category=_normalize_text(raw.get("lowerBizName")),
                detail_category=_normalize_text(raw.get("detailBizName")),
            ))
        return sorted(results, key=lambda poi: (poi.straight_distance_m, poi.name))[:count]

    async def pedestrian_route(
        self, start: Coordinate, end: Coordinate, start_name: str, end_name: str
    ) -> Route:
        key = (round(start.lat, 7), round(start.lon, 7), round(end.lat, 7), round(end.lon, 7))
        async with self._cache_lock:
            cached = self._walk_cache.get(key)
            if cached is not None:
                self._walk_cache.move_to_end(key)
                return cached
        response = await self._request(
            "POST", f"{self.base_url}/tmap/routes/pedestrian",
            headers=self._headers(json_body=True), params={"version": "1"},
            json={
                "startX": start.lon, "startY": start.lat,
                "endX": end.lon, "endY": end.lat,
                "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
                "startName": start_name or "출발", "endName": end_name or "도착",
                "searchOption": "30", "sort": "index",
            },
        )
        route = self._parse_route(self._json(response, "보행 경로"), "tmap_pedestrian_api")
        async with self._cache_lock:
            self._walk_cache[key] = route
            self._walk_cache.move_to_end(key)
            while len(self._walk_cache) > 2048:
                self._walk_cache.popitem(last=False)
        return route

    async def car_route(
        self, start: Coordinate, end: Coordinate, start_name: str, end_name: str
    ) -> Route:
        # TMAP 실제 차량 경로. 정류장 간 DRT 구간 소요시간의 임시 추정치이며,
        # 기본적으로는 app/travel_time/estimate_duration.py의 ETA 예측 모델로 대체된다.
        response = await self._request(
            "POST", f"{self.base_url}/tmap/routes",
            headers=self._headers(json_body=True), params={"version": "1"},
            json={
                "startX": start.lon, "startY": start.lat,
                "endX": end.lon, "endY": end.lat,
                "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
                "startName": start_name or "출발", "endName": end_name or "도착",
                "searchOption": "0", "trafficInfo": "Y", "totalValue": 1, "sort": "index",
            },
        )
        return self._parse_route(self._json(response, "자동차 경로"), "tmap_car_api")

    @staticmethod
    def _parse_route(body: dict, source: str) -> Route:
        features = body.get("features") or []
        if isinstance(features, dict):
            features = [features]
        for feature in features:
            props = feature.get("properties") or {}
            if "totalDistance" in props and "totalTime" in props:
                return Route(float(props["totalDistance"]), float(props["totalTime"]), source)
        raise TmapError("TMAP 경로 응답에 totalDistance/totalTime이 없습니다.")

    async def reverse_geocode(self, lat: float, lon: float) -> dict:
        key = (round(lat, 5), round(lon, 5))
        async with self._cache_lock:
            cached = self._reverse_cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
        response = await self._request(
            "GET", f"{self.base_url}/tmap/geo/reversegeocoding",
            headers=self._headers(),
            params={
                "version": "1", "lat": f"{lat:.7f}", "lon": f"{lon:.7f}",
                "coordType": "WGS84GEO", "addressType": "A10", "newAddressExtend": "Y",
            },
        )
        if response.status_code == 204:
            return {"ok": False, "status": "NO_CONTENT", "address": None}
        result = self._parse_reverse(self._json(response, "역지오코딩"))
        async with self._cache_lock:
            self._reverse_cache[key] = (time.monotonic() + 3600, result)
            while len(self._reverse_cache) > 2048:
                self._reverse_cache.popitem(last=False)
        return result

    @staticmethod
    def _parse_reverse(body: dict) -> dict:
        info = body.get("addressInfo") or {}
        if not info.get("fullAddress"):
            return {"ok": False, "status": "NO_RESULT", "address": None}
        return {
            "ok": True, "status": "OK", "address": info.get("fullAddress"),
            "city_do": info.get("city_do"), "gu_gun": info.get("gu_gun"),
            "admin_dong": info.get("adminDong"), "legal_dong": info.get("legalDong"),
            "road_name": info.get("roadName"),
        }


_MOCK_POIS = [
    POI("m1", "사당정형외과의원", Coordinate(37.4849, 126.9711), "서울 동작구 사당동", source="mock"),
    POI("m2", "남현서울정형외과", Coordinate(37.4826, 126.9654), "서울 동작구 사당동", source="mock"),
    POI("m3", "이수바른정형외과", Coordinate(37.4855, 126.9820), "서울 동작구 사당동", source="mock"),
    POI("m4", "방배굿본정형외과", Coordinate(37.4890, 126.9930), "서울 서초구 방배동", source="mock"),
    POI("m5", "서울대효병원", Coordinate(37.4660, 126.9500), "서울 관악구", source="mock"),
]


class MockTmapClient:
    """API 키 없이 전체 흐름을 확인하는 결정적(deterministic) 클라이언트."""

    async def search_pois(
        self,
        keyword: str,
        center: Coordinate,
        radius_m: int,
        count: int = 5,
        keyword_type: SearchKeywordType = SearchKeywordType.CATEGORY,
    ) -> list[POI]:
        normalized = keyword.replace(" ", "").lower()
        results = []
        for source in _MOCK_POIS:
            if normalized not in source.name.replace(" ", "").lower() and normalized not in "정형외과병원":
                continue
            if any(kw in source.name for kw in EXCLUDED_POI_KEYWORDS):
                continue
            distance = haversine_m(center.lat, center.lon, source.coord.lat, source.coord.lon)
            if distance <= radius_m:
                results.append(POI(
                    source.poi_id, source.name, source.coord, source.address,
                    distance, "mock",
                ))
        return sorted(results, key=lambda poi: poi.straight_distance_m)[:count]

    async def pedestrian_route(self, start: Coordinate, end: Coordinate, start_name: str = "", end_name: str = "") -> Route:
        distance = haversine_m(start.lat, start.lon, end.lat, end.lon) * 1.18
        return Route(distance, distance / 1.0, "mock_pedestrian")

    async def car_route(self, start: Coordinate, end: Coordinate, start_name: str = "", end_name: str = "") -> Route:
        distance = haversine_m(start.lat, start.lon, end.lat, end.lon) * 1.30
        return Route(distance, max(90, distance / 6.0), "mock_car")

    async def reverse_geocode(self, lat: float, lon: float) -> dict:
        return {
            "ok": True, "status": "MOCK",
            "address": f"[MOCK] 위도 {lat:.5f}, 경도 {lon:.5f} 인근 (서울 동작구 사당동 일대로 가정)",
            "city_do": "서울특별시", "gu_gun": "동작구",
            "admin_dong": "사당동", "legal_dong": "사당동", "road_name": None,
        }

    async def close(self) -> None:
        return None
