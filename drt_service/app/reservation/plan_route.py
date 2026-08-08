"""이형주 담당(통합): 정류장 선택부터 목적지 평가까지 전체 이동 계획을 계산.

대분류 검색은 `app/destination/search_by_category.py`, 정확한 이름 검색은
`app/destination/search_by_name.py`가 후보 산출까지만 담당하고, 이 파일이 승·하차 정류장
결정(`app/stations/find_departure_station.py`)과 소요시간 예측
(`app/travel_time/estimate_duration.py`)을 엮어 도보 vs DRT 가중치 비교까지 통합 계산한다.
"""
from __future__ import annotations

import asyncio

from app.clients.tmap_client import Coordinate, MockTmapClient, POI, Route, TmapClient, poi_to_dict
from app.db.models import Station
from app.destination.search_by_category import category_poi_candidates
from app.destination.search_by_name import search_by_name
from app.stations.find_departure_station import (
    DEFAULT_WALK_LIMIT_M,
    best_station_access,
    is_inside_service_area,
)
from app.travel_time.estimate_duration import ETAContext, ETAService

DIRECT_WALK_THRESHOLD_M = 350
WALKING_WEIGHT = 1.5
WAITING_WEIGHT = 1.0
LONG_WALK_THRESHOLD_M = 300
LONG_WALK_PENALTY_PER_M_S = 1.0
ROUTE_UNCERTAINTY_PENALTY_S = 60


async def vehicle_route(
    boarding_station: Station,
    alighting_station: Station,
    client: TmapClient | MockTmapClient,
    eta_service: ETAService,
    eta_context: ETAContext,
) -> Route:
    """정류장 간 DRT 차량 구간 소요시간. ETA 예측 모델을 우선 쓰고, 정류장이 학습
    데이터/CSV에 없어 예측할 수 없으면(ValueError/KeyError) TMAP 실제 차량경로로 폴백한다.
    """
    try:
        estimate = await asyncio.to_thread(
            eta_service.estimate_drt,
            origin_station=str(boarding_station.station_id),
            destination_station=str(alighting_station.station_id),
            weather=eta_context.weather,
            weekday=eta_context.weekday,
            speed_level=eta_context.speed_level,
            hour=eta_context.hour,
        )
        return Route(estimate.route_distance_m, estimate.travel_time_sec, estimate.prediction_source)
    except (ValueError, KeyError):
        return await client.car_route(
            Coordinate(boarding_station.lat, boarding_station.lon),
            Coordinate(alighting_station.lat, alighting_station.lon),
            boarding_station.name,
            alighting_station.name,
        )


def _long_walk_penalty_s(*routes: Route) -> float:
    excess = sum(max(0.0, route.distance_m - LONG_WALK_THRESHOLD_M) for route in routes)
    return excess * LONG_WALK_PENALTY_PER_M_S


def _drt_burden(boarding: dict, alighting: dict, vehicle: Route, expected_wait_s: float) -> tuple[float, dict]:
    walk_s = boarding["walk"].duration_s + alighting["walk"].duration_s
    components = {
        "weighted_walking_s": WALKING_WEIGHT * walk_s,
        "weighted_waiting_s": WAITING_WEIGHT * expected_wait_s,
        "vehicle_s": vehicle.duration_s,
        "long_walk_penalty_s": _long_walk_penalty_s(boarding["walk"], alighting["walk"]),
        "transfer_penalty_s": 0.0,
        "route_uncertainty_penalty_s": ROUTE_UNCERTAINTY_PENALTY_S,
    }
    return sum(components.values()), components


def _direct_walk_burden(route: Route) -> tuple[float, dict]:
    components = {
        "weighted_walking_s": WALKING_WEIGHT * route.duration_s,
        "long_walk_penalty_s": _long_walk_penalty_s(route),
    }
    return sum(components.values()), components


async def evaluate_poi(
    origin: Coordinate,
    boarding: dict,
    poi: POI,
    mode: str,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    eta_service: ETAService,
    eta_context: ETAContext,
    user_walk_limit_m: float,
    expected_wait_s: float,
) -> dict:
    direct = await client.pedestrian_route(origin, poi.coord, "현재 위치", poi.name)
    direct_score, direct_components = _direct_walk_burden(direct)
    if direct.distance_m <= DIRECT_WALK_THRESHOLD_M:
        return {
            "status": "walk_recommended", "mode": mode, "recommended_mode": "walk",
            "destination": poi, "direct_walk": direct, "score_s": direct_score,
            "score_components": direct_components,
            "total_travel_time_s": direct.duration_s,
            "reason": "목적지가 가까워 DRT보다 직접 도보가 적합",
        }

    alighting = await best_station_access(poi.coord, poi.name, stations, client, user_walk_limit_m)
    if alighting is None:
        return {
            "status": "rejected", "mode": mode, "recommended_mode": "none",
            "destination": poi,
            "reason": "목적지 주변에서 허용 도보거리 안의 DRT 정류장을 찾지 못함",
        }
    if boarding["station"].station_id == alighting["station"].station_id:
        if direct.distance_m <= user_walk_limit_m:
            return {
                "status": "walk_recommended", "mode": mode, "recommended_mode": "walk",
                "destination": poi, "direct_walk": direct, "score_s": direct_score,
                "score_components": direct_components,
                "total_travel_time_s": direct.duration_s,
                "reason": "승·하차 정류장이 같아 DRT 이동구간이 없으나 직접 도보가 보행 한도 이내",
            }
        return {
            "status": "rejected", "mode": mode, "recommended_mode": "none",
            "destination": poi, "direct_walk": direct,
            "reason": "승·하차 정류장이 같아 DRT 이동구간이 없고, 직접 도보 거리가 보행 한도를 초과함",
        }

    vehicle = await vehicle_route(
        boarding["station"], alighting["station"], client, eta_service, eta_context,
    )
    total_travel_time_s = boarding["walk"].duration_s + vehicle.duration_s + alighting["walk"].duration_s
    score, components = _drt_burden(boarding, alighting, vehicle, expected_wait_s)
    if direct_score <= score:
        return {
            "status": "walk_recommended", "mode": mode, "recommended_mode": "walk",
            "destination": poi, "direct_walk": direct, "score_s": direct_score,
            "score_components": direct_components, "drt_alternative_score_s": score,
            "total_travel_time_s": direct.duration_s,
            "reason": "직접 도보의 총 부담이 DRT보다 작거나 같음",
        }
    return {
        "status": "ready_for_confirmation", "mode": mode, "recommended_mode": "drt",
        "destination": poi, "boarding": boarding, "alighting": alighting,
        "vehicle": vehicle, "direct_walk": direct,
        "expected_wait_s": expected_wait_s, "score_s": score,
        "score_components": components, "direct_walk_score_s": direct_score,
        "total_travel_time_s": total_travel_time_s,
        "reason": "가중 보행·대기·차량시간과 장거리 보행·경로 불확실성 페널티를 합산해 평가",
    }


async def plan_category(
    query: str,
    origin: Coordinate,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    eta_service: ETAService,
    eta_context: ETAContext,
    user_walk_limit_m: float = DEFAULT_WALK_LIMIT_M,
    expected_wait_s: float = 300,
) -> dict:
    if not is_inside_service_area(origin, stations):
        return {
            "status": "outside_service_area", "mode": "category",
            "recommended_mode": "other_transit", "reason": "현재 위치가 DRT 서비스 범위 밖입니다.",
        }
    boarding = await best_station_access(origin, "현재 위치", stations, client, user_walk_limit_m)
    if boarding is None:
        return {
            "status": "no_accessible_boarding_station", "mode": "category",
            "recommended_mode": "other_transit",
            "reason": "서비스 지역 안이지만 보행 한도 내 승차 정류장이 없습니다.",
        }

    boarding_station = boarding["station"]
    pois, used_radius_m, radius_expanded, search_failures = await category_poi_candidates(
        client, query, Coordinate(boarding_station.lat, boarding_station.lon),
    )

    audits: list[dict] = list(search_failures)
    valid = []
    for poi in pois:
        try:
            result = await evaluate_poi(
                origin, boarding, poi, "category", stations, client, eta_service, eta_context,
                user_walk_limit_m, expected_wait_s,
            )
        except Exception as exc:
            audits.append({
                "destination": poi.name, "status": "route_api_failed",
                "reason": f"{type(exc).__name__}: {exc}", "score_s": None,
            })
            continue
        audits.append({
            "destination": poi.name,
            "straight_distance_m": round(poi.straight_distance_m),
            "status": result["status"], "reason": result["reason"],
            "score_s": round(result.get("score_s", 0)) or None,
        })
        if result["recommended_mode"] in {"walk", "drt"}:
            valid.append(result)
    if not valid:
        return {
            "status": "no_feasible_destination", "mode": "category",
            "recommended_mode": "none", "candidate_audit": audits,
        }
    best = min(valid, key=lambda item: item.get("score_s", float("inf")))
    # 응답에서 "3개 후보 목록 -> 그중 확정된 목적지" 순서로 읽히도록, candidate_audit을
    # destination/direct_walk 등 확정 결과 필드보다 앞에 오도록 재배치한다.
    ordered: dict = {
        "status": best["status"],
        "mode": best["mode"],
        "recommended_mode": best["recommended_mode"],
        "candidate_audit": audits,
        "requires_user_confirmation": True,
    }
    for key, value in best.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


async def plan_specific(
    place_name: str,
    origin: Coordinate,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    eta_service: ETAService,
    eta_context: ETAContext,
    user_walk_limit_m: float = DEFAULT_WALK_LIMIT_M,
    expected_wait_s: float = 300,
) -> dict:
    if not is_inside_service_area(origin, stations):
        return {
            "status": "outside_service_area", "mode": "specific",
            "recommended_mode": "other_transit", "reason": "현재 위치가 DRT 서비스 범위 밖입니다.",
        }
    boarding = await best_station_access(origin, "현재 위치", stations, client, user_walk_limit_m)
    if boarding is None:
        return {
            "status": "no_accessible_boarding_station", "mode": "specific",
            "recommended_mode": "other_transit",
            "reason": "서비스 지역 안이지만 보행 한도 내 승차 정류장이 없습니다.",
        }

    boarding_station = boarding["station"]
    search_result = await search_by_name(
        client, place_name, Coordinate(boarding_station.lat, boarding_station.lon)
    )
    if search_result["status"] == "search_failed":
        return {
            "status": "destination_search_failed", "mode": "specific",
            "recommended_mode": "none", "reason": search_result["reason"],
        }
    # search_by_name이 이름 정확매치가 있으면 이미 그것만 추려서 돌려주므로(narrow_exact_matches),
    # 여기서는 남은 후보가 1곳인지 여러 곳인지만 보면 된다.
    pois = search_result["candidates"]
    if not pois:
        return {
            "status": "destination_not_found", "mode": "specific",
            "recommended_mode": "needs_confirmation", "requires_user_confirmation": True,
        }
    # 동명(同名) 후보가 전국 반경(33km)까지 잡히므로, 정류장 커버리지 밖(=DRT로 갈 수 없는
    # 지역)의 후보는 사용자 확인 목록에서 미리 제거한다. API 호출 없이 좌표만으로 판정한다.
    pois = [poi for poi in pois if is_inside_service_area(poi.coord, stations)]
    if not pois:
        return {
            "status": "destination_outside_service_area", "mode": "specific",
            "recommended_mode": "other_transit",
            "reason": "이름이 일치하는 장소를 찾았지만 모두 DRT 서비스 범위 밖입니다.",
        }
    if len(pois) > 1:
        return {
            "status": "needs_destination_confirmation", "mode": "specific",
            "recommended_mode": "needs_confirmation",
            "candidates": [poi_to_dict(poi) for poi in pois],
            "requires_user_confirmation": True,
        }
    poi = pois[0]
    try:
        result = await evaluate_poi(
            origin, boarding, poi, "specific", stations, client, eta_service, eta_context,
            user_walk_limit_m, expected_wait_s,
        )
    except Exception as exc:
        return {
            "status": "route_api_failed", "mode": "specific",
            "recommended_mode": "none", "destination": poi,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    result["requires_user_confirmation"] = True
    return result


def serialize_result(result: dict) -> dict:
    output = dict(result)
    poi = output.get("destination")
    if isinstance(poi, POI):
        output["destination"] = poi_to_dict(poi)
    for key in ("boarding", "alighting"):
        access = output.get(key)
        if access:
            station, walk = access["station"], access["walk"]
            output[key] = {
                "station_id": station.station_id, "name": station.name,
                "station_type": station.station_type,
                "walk_distance_m": round(walk.distance_m),
                "walk_duration_s": round(walk.duration_s),
            }
    for key in ("vehicle", "direct_walk"):
        route = output.get(key)
        if isinstance(route, Route):
            output[key] = {
                "distance_m": round(route.distance_m),
                "duration_s": round(route.duration_s), "source": route.source,
            }
    if output.get("score_s") is not None:
        output["estimated_total_minutes"] = round(output["score_s"] / 60, 1)
    if output.get("total_travel_time_s") is not None:
        output["total_travel_time_min"] = round(output["total_travel_time_s"] / 60, 1)
    return output


async def plan_route(
    query: str,
    origin: Coordinate,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    eta_service: ETAService,
    eta_context: ETAContext,
    *,
    is_specific: bool = False,
    max_walk_m: float = DEFAULT_WALK_LIMIT_M,
    expected_wait_s: float = 300,
) -> dict:
    planner = plan_specific if is_specific else plan_category
    result = await planner(
        query, origin, stations, client, eta_service, eta_context, max_walk_m, expected_wait_s
    )
    return serialize_result(result)
