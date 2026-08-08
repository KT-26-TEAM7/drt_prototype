from dataclasses import dataclass
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import (
    TMAP_API_URL,
    TMAP_APP_KEY,
    TMAP_TIMEOUT_SECONDS,
)
from app.utils.geo import calculate_distance_km


Coordinate = tuple[float, float]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoutePath:
    coordinates: tuple[Coordinate, ...]
    distance_m: float
    source: str
    duration_seconds: int | None = None


def get_driving_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> RoutePath:
    if TMAP_APP_KEY:
        route = _get_tmap_route(
            start_latitude,
            start_longitude,
            end_latitude,
            end_longitude,
        )
        if route is not None:
            return route

    return straight_route(
        start_latitude,
        start_longitude,
        end_latitude,
        end_longitude,
    )


def _get_tmap_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> RoutePath | None:
    if not TMAP_API_URL or not TMAP_APP_KEY:
        return None

    payload = json.dumps(
        {
            "startX": str(start_longitude),
            "startY": str(start_latitude),
            "endX": str(end_longitude),
            "endY": str(end_latitude),
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
            "startName": "현재 위치",
            "endName": "목적 정류장",
            "searchOption": "0",
            "trafficInfo": "Y",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"{TMAP_API_URL}?version=1&format=json",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "appKey": TMAP_APP_KEY,
        },
    )

    try:
        with urlopen(request, timeout=TMAP_TIMEOUT_SECONDS) as response:
            body = json.load(response)
        coordinates = _parse_tmap_coordinates(
            body,
            start_latitude,
            start_longitude,
        )
        duration_seconds = _parse_tmap_duration_seconds(body)
        return _build_route(
            coordinates,
            start_latitude,
            start_longitude,
            end_latitude,
            end_longitude,
            source="tmap",
            duration_seconds=duration_seconds,
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        logger.warning("TMAP 경로 조회 실패(%s): 직선 경로를 사용합니다.", type(error).__name__)
        return None


def _parse_tmap_coordinates(
    body: dict,
    start_latitude: float,
    start_longitude: float,
) -> tuple[Coordinate, ...]:
    features = sorted(
        body["features"],
        key=_feature_index,
    )
    coordinates: list[Coordinate] = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        segment = [
            (float(latitude), float(longitude))
            for longitude, latitude, *_ in geometry.get("coordinates", [])
        ]
        if not segment:
            continue

        previous = coordinates[-1] if coordinates else (
            start_latitude,
            start_longitude,
        )
        if _coordinate_distance(previous, segment[-1]) < _coordinate_distance(
            previous, segment[0]
        ):
            segment.reverse()

        for coordinate in segment:
            if not coordinates or coordinates[-1] != coordinate:
                coordinates.append(coordinate)
    if len(coordinates) < 2:
        raise ValueError("TMAP 경로 좌표가 부족합니다.")
    return tuple(coordinates)


def _feature_index(feature: dict) -> int:
    try:
        return int((feature.get("properties") or {}).get("index", 0))
    except (TypeError, ValueError):
        return 0


def _coordinate_distance(start: Coordinate, end: Coordinate) -> float:
    return calculate_distance_km(*start, *end)


def _parse_tmap_duration_seconds(body: dict) -> int:
    for feature in body["features"]:
        total_time = (feature.get("properties") or {}).get("totalTime")
        if total_time is not None:
            duration_seconds = int(total_time)
            if duration_seconds > 0:
                return duration_seconds
    raise ValueError("TMAP 예상 이동 시간이 없습니다.")


def _build_route(
    coordinates: tuple[Coordinate, ...],
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
    source: str,
    duration_seconds: int | None = None,
) -> RoutePath:
    exact_start = (start_latitude, start_longitude)
    exact_end = (end_latitude, end_longitude)
    complete_coordinates = (exact_start, *coordinates, exact_end)
    distance_m = calculate_route_distance_m(complete_coordinates)
    if distance_m <= 0:
        raise ValueError("경로 거리가 올바르지 않습니다.")
    return RoutePath(
        coordinates=complete_coordinates,
        distance_m=distance_m,
        source=source,
        duration_seconds=duration_seconds,
    )


def straight_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> RoutePath:
    coordinates = (
        (start_latitude, start_longitude),
        (end_latitude, end_longitude),
    )
    return RoutePath(
        coordinates=coordinates,
        distance_m=calculate_route_distance_m(coordinates),
        source="straight_fallback",
    )


def calculate_route_distance_m(coordinates: tuple[Coordinate, ...]) -> float:
    return sum(
        calculate_distance_km(*start, *end) * 1000
        for start, end in zip(coordinates, coordinates[1:])
    )


def serialize_route(route: RoutePath) -> str:
    return json.dumps(route.coordinates, ensure_ascii=False, separators=(",", ":"))


def deserialize_route(serialized_coordinates: str | None) -> tuple[Coordinate, ...]:
    if not serialized_coordinates:
        return ()
    try:
        raw_coordinates = json.loads(serialized_coordinates)
        coordinates = tuple(
            (float(coordinate[0]), float(coordinate[1]))
            for coordinate in raw_coordinates
        )
    except (json.JSONDecodeError, TypeError, ValueError, IndexError):
        return ()
    return coordinates if len(coordinates) >= 2 else ()
